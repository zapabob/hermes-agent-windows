"""Explicit source export and bounded sandbox snapshots; never mount host homes."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat

_MAX_BYTES = 16 * 1024 * 1024
_MAX_FILE = 512 * 1024
_MAX_FILES = 2048
_SKIP = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.pytest_cache', '.ruff_cache'}
_SECRETS = {'auth.json', 'credentials', 'credentials.json', '.netrc', '.npmrc', '.pypirc',
            'id_rsa', 'id_ed25519', '.aws', '.ssh', '.codex', '.hermes', '.config'}


def relative_path(value: str) -> str:
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value
            or '\0' in value or any(ord(c) < 32 for c in value)
            or PurePosixPath(value).is_absolute() or any(p in ('', '.', '..') for p in value.split('/'))):
        raise ValueError('Unsafe source path')
    if any(p.lower() in _SECRETS or p.lower().startswith('.env')
           or p.lower().endswith(('.pem', '.key', '.p12', '.pfx')) for p in value.split('/')):
        raise ValueError('Credential files cannot enter an engineering workspace')
    return value


def read_sources(root: Path, selected: tuple[str, ...]) -> dict[str, bytes]:
    root = Path(root)
    for ancestor in (root, *root.parents):
        info = ancestor.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Source reparse path is not admitted')
    root = root.resolve(strict=True)
    if not root.is_dir() or type(selected) is not tuple or not selected:
        raise ValueError('Explicit non-secret source paths are required')
    files: dict[str, bytes] = {}
    total = 0

    def visit(path: Path):
        nonlocal total
        relative = relative_path(path.relative_to(root).as_posix())
        if any(part in _SKIP for part in PurePosixPath(relative).parts):
            return
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Source links and reparse points are not admitted')
        if stat.S_ISDIR(info.st_mode):
            for child in sorted(path.iterdir()):
                # An explicitly selected credential path is rejected above;
                # known credentials nested in a selected source directory are omitted.
                try:
                    relative_path(child.relative_to(root).as_posix())
                except ValueError:
                    continue
                visit(child)
        elif stat.S_ISREG(info.st_mode):
            if info.st_nlink != 1 or info.st_size > _MAX_FILE:
                raise ValueError('Source link or file size exceeds policy')
            # no-follow open plus descriptor identity protects a raced symlink.
            flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_BINARY', 0)
            fd = os.open(path, flags)
            with os.fdopen(fd, 'rb') as handle:
                current = os.fstat(handle.fileno())
                if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
                    raise ValueError('Source changed during admission')
                data = handle.read(_MAX_FILE + 1)
            total += len(data)
            if len(data) > _MAX_FILE or total > _MAX_BYTES or len(files) >= _MAX_FILES:
                raise ValueError('Source export budget exceeded')
            files[relative] = data
        else:
            raise ValueError('Special files are not admitted')

    for name in selected:
        relative_path(name)
        path = root / name
        # Reject symlinked ancestors before descending.
        for ancestor in (path, *path.parents):
            if ancestor == root:
                break
            info = ancestor.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Source links and reparse points are not admitted')
        visit(path)
    if not files:
        raise ValueError('No source files selected')
    return files


def digest(files: dict[str, bytes]) -> str:
    manifest = {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())}
    return hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _python(env, source: str, payload: dict, *, root=False) -> str:
    result = env.execute_clean(('/usr/local/bin/python', '-I', '-S', '-c', source),
                               stdin=json.dumps(payload), root=root, timeout=60)
    if type(result.get('returncode')) is not int or result['returncode'] != 0:
        raise RuntimeError('Sandbox file transfer did not complete')
    return result['output']


def import_sources(env, files: dict[str, bytes], protected: tuple[str, ...]) -> dict[str, bytes]:
    guards = {name: data for name, data in files.items()
              if any(name == p or name.startswith(p + '/') for p in protected)}
    if not guards:
        raise ValueError('At least one existing acceptance probe must be protected')
    for name, data in files.items():
        directory = str(PurePosixPath(name).parent)
        _python(env, '''import json,os,pathlib,sys
p=json.load(sys.stdin); current=pathlib.Path('/workspace')
for component in pathlib.PurePosixPath(p['directory']).parts:
    current=current/component
    if not current.exists(): current.mkdir(mode=0o1777)
    os.chmod(current,0o1777)
''', {'directory':directory}, root=True)
        _python(env, '''import base64,json,os,pathlib,sys
p=json.load(sys.stdin); f=pathlib.Path('/workspace')/p['name']
with f.open('xb') as h: h.write(base64.b64decode(p['data'],validate=True))
os.chmod(f,0o444 if p['protected'] else 0o644)
''', {'name':name,'data':base64.b64encode(data).decode(),'protected':name in guards}, root=name in guards)
    return guards


def snapshot(env) -> dict[str, bytes]:
    # Trusted interpreter from the immutable image, never model-written scripts,
    # mutable shell snapshots, PATH, conftest, or ambient PYTHONPATH.
    names = json.loads(_python(env, '''import json,os,pathlib,stat,sys
p=json.load(sys.stdin); names=[]; total=0
for directory,dirs,files in os.walk('/workspace',followlinks=False):
    for name in dirs+files:
        f=pathlib.Path(directory)/name
        if f.is_symlink(): raise RuntimeError('symlink in result')
    dirs[:]=[x for x in dirs if x not in p['skip']]
    for name in files:
        f=pathlib.Path(directory)/name; s=f.stat()
        if not stat.S_ISREG(s.st_mode) or s.st_nlink!=1 or s.st_size>p['max_file']: raise RuntimeError('invalid file')
        total+=s.st_size
        names.append(f.relative_to('/workspace').as_posix())
        if total>p['max_bytes'] or len(names)>p['max_files']: raise RuntimeError('result too large')
print(json.dumps(sorted(names)))
''', {'skip':sorted(_SKIP),'max_file':_MAX_FILE,'max_bytes':_MAX_BYTES,'max_files':_MAX_FILES}))
    if type(names) is not list or len(names) > _MAX_FILES:
        raise RuntimeError('Invalid sandbox manifest')
    result = {}
    for name in names:
        relative_path(name)
        chunks = []
        # Small responses cannot be silently truncated by the native bounded capture.
        for offset in range(0, _MAX_FILE + 1, 8192):
            raw = json.loads(_python(env, '''import base64,json,pathlib,sys
p=json.load(sys.stdin); f=pathlib.Path('/workspace')/p['name']
if f.is_symlink(): raise RuntimeError('symlink')
with f.open('rb') as h:
    h.seek(p['offset']); data=h.read(8192)
print(json.dumps(base64.b64encode(data).decode()))
''', {'name':name,'offset':offset}))
            data = base64.b64decode(raw, validate=True)
            chunks.append(data)
            if len(data) < 8192:
                break
        content = b''.join(chunks)
        if len(content) > _MAX_FILE:
            raise RuntimeError('File grew during snapshot')
        result[name] = content
    if sum(map(len, result.values())) > _MAX_BYTES:
        raise RuntimeError('Result exceeded export budget')
    return result


def write_result(directory: Path, files: dict[str, bytes]) -> None:
    directory.mkdir(mode=0o700)
    for name, content in files.items():
        relative_path(name)
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
