// Test fixtures for the `ctx.files` suites: links that behave the same on
// every host without needing a privileged account.
//
// - Directory links are real symlinks on POSIX and NTFS junctions on Windows.
//   A junction is a reparse point that realpath/lstat resolve like a symlink,
//   and creating one needs no elevation, so the Windows lane exercises the
//   real reparse-point refusal instead of skipping.
// - File symlinks on Windows need SeCreateSymbolicLinkPrivilege (Developer
//   Mode or an elevated token). When the host lacks it `canLinkFiles` is
//   false and file-symlink cases are skipped with that reason, not faked.

import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

export function linkDir(target: string, link: string): void {
  fs.symlinkSync(target, link, process.platform === 'win32' ? 'junction' : 'dir')
}

export function linkFile(target: string, link: string): void {
  fs.symlinkSync(target, link, 'file')
}

function probeFileLinks(): boolean {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hermes-plugin-files-probe-'))

  try {
    const target = path.join(dir, 'target')
    fs.writeFileSync(target, 'x')
    linkFile(target, path.join(dir, 'link'))

    return true
  } catch {
    return false
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
}

/** True when this host can create file symlinks (always on POSIX). */
export const canLinkFiles = probeFileLinks()
