"""Owned Windows profiles behind actual dispatch and actual CLI workers.

The HTTP adapter only carries JSON-RPC and reads fixture-owned effects. It
does not replace command handlers, workers, approval, or skill persistence.
"""
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import queue
import sys
import threading
import uuid

import psutil
import yaml

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
EVIDENCE = Path(sys.argv[1]).resolve()
PROFILES = EVIDENCE / "profiles"
PROFILES.mkdir()

with redirect_stdout(io.StringIO()):
    from hermes_constants import reset_hermes_home_override, set_hermes_home_override
    from hermes_state import SessionDB
    from tools import write_approval as wa
    from tui_gateway import server


class CaptureTransport:
    def __init__(self, rid):
        self.rid = rid
        self.responses = queue.Queue()

    def write(self, response):
        if response.get("id") == self.rid:
            self.responses.put(response)

    def close(self):
        pass


profiles = {}
for label in ("owner", "foreign"):
    home = PROFILES / label
    home.mkdir()
    config = {
        "model": {"default": "f04-no-inference"},
        "mcp_servers": {},
        "skills": {"write_approval": True},
        "terminal": {"cwd": str(home)},
        "dashboard": {"turn_isolation": False},
        "sessions": {"auto_prune": False, "auto_archive": False},
        "checkpoints": {"auto_prune": False},
    }
    (home / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    key = f"f04-stored-{label}-{uuid.uuid4().hex}"
    db = SessionDB(home / "state.db")
    db.create_session(key, source="desktop", model="f04-no-inference")
    db.close()
    records = {}
    token = set_hermes_home_override(home)
    try:
        for action in ("approve", "reject"):
            name = f"f04-{label}-{action}-{uuid.uuid4().hex[:8]}"
            content = (f"---\nname: {name}\ndescription: Inspect a harmless fixture.\n"
                       "---\n# Fixture\n\n日本語 pending review effect.\n")
            record = wa.stage_write(
                wa.SKILLS, {"action": "create", "name": name, "content": content},
                summary=f"{label} {action} 日本語", origin="foreground",
            )
            assert (home / "pending" / "skills" / f"{record['id']}.json").is_file()
            records[action] = {"id": record["id"], "name": name, "content": content}
    finally:
        reset_hermes_home_override(token)
    rid = f"f04-runtime-{label}"
    server._sessions[rid] = {
        "session_key": key, "profile_home": str(home), "agent": None,
        "slash_worker": None, "running": False, "source": "desktop",
        "history": [], "history_lock": threading.Lock(),
        "transport": CaptureTransport(None),
    }
    profiles[label] = {"home": str(home), "runtime": rid, "stored": key, "records": records}

calls = []
attempts = []
worker_births = {}


def snapshot():
    result = {}
    for label, spec in profiles.items():
        home = Path(spec["home"])
        files = {}
        for action, record in spec["records"].items():
            target = home / "skills" / record["name"] / "SKILL.md"
            files[action] = target.read_text(encoding="utf-8") if target.exists() else None
        result[label] = {
            "pending": sorted(p.stem for p in (home / "pending" / "skills").glob("*.json")),
            "files": files,
            "approval": yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))["skills"]["write_approval"],
        }
    return result


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/rpc":
            attempts.append(request)
            assert request["method"] in {"commands.catalog", "complete.slash", "slash.exec"}
            transport = CaptureTransport(request["id"])
            response = server.dispatch(request, transport)
            if response is None:
                response = transport.responses.get(timeout=60)
            calls.append({"request": request, "response": response, "effects": snapshot()})
            for label, spec in profiles.items():
                worker = server._sessions[spec["runtime"]].get("slash_worker")
                if worker and label not in worker_births:
                    parent = psutil.Process(worker.proc.pid)
                    worker_births[label] = {
                        "pid": worker.proc.pid, "created": parent.create_time(),
                        "descendants": [{"pid": child.pid, "created": child.create_time()}
                                        for child in parent.children(recursive=True)],
                    }
        elif self.path == "/state":
            response = {"profiles": profiles, "effects": snapshot(), "calls": calls, "attempts": attempts}
        elif self.path == "/close":
            closed = []
            for label, spec in profiles.items():
                worker = server._sessions[spec["runtime"]].get("slash_worker")
                if worker:
                    drains = [t for t in threading.enumerate()
                              if getattr(getattr(t, "_target", None), "__self__", None) is worker]
                    drain_names = [t._target.__name__ for t in drains]
                    worker.close()
                    for drain in drains:
                        drain.join(timeout=2)
                    assert set(drain_names) == {"_drain_stdout", "_drain_stderr"}
                    birth = worker_births[label]
                    same_birth = False
                    try:
                        same_birth = psutil.Process(birth["pid"]).create_time() == birth["created"]
                    except psutil.NoSuchProcess:
                        pass
                    descendants = []
                    for child_birth in birth["descendants"]:
                        alive = False
                        cleanup_needed = False
                        try:
                            child = psutil.Process(child_birth["pid"])
                            if child.create_time() == child_birth["created"]:
                                try:
                                    child.wait(timeout=5)
                                except psutil.TimeoutExpired:
                                    cleanup_needed = True
                                    # Only this observed descendant's matching birth is owned.
                                    if child.create_time() == child_birth["created"]:
                                        child.terminate()
                                        child.wait(timeout=3)
                                try:
                                    alive = child.create_time() == child_birth["created"] and child.is_running()
                                except psutil.NoSuchProcess:
                                    pass
                        except psutil.NoSuchProcess:
                            pass
                        descendants.append({**child_birth, "same_birth_alive": alive,
                                            "cleanup_needed": cleanup_needed})
                    closed.append({"profile": label, **birth, "exit": worker.proc.poll(),
                                   "same_birth_alive": same_birth,
                                   "descendants": descendants,
                                   "drain_threads": [{"name": name, "alive": t.is_alive()}
                                                     for name, t in zip(drain_names, drains)],
                                   "pipes_closed": all(p.closed for p in (worker.proc.stdin, worker.proc.stdout, worker.proc.stderr))})
            response = {"closed": closed, "effects": snapshot(), "calls": calls, "attempts": attempts}
            assert all(row["exit"] is not None and not row["same_birth_alive"] and row["pipes_closed"]
                       and not any(t["alive"] for t in row["drain_threads"]) for row in closed)
            (EVIDENCE / "backend-receipt.json").write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")
            threading.Thread(target=httpd.shutdown, daemon=True).start()
        else:
            raise AssertionError(self.path)
        body = json.dumps(response, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
sys.stdout.write(json.dumps({"port": httpd.server_port, "profiles": profiles}) + "\n")
sys.stdout.flush()
try:
    httpd.serve_forever(poll_interval=0.1)
finally:
    httpd.server_close()
    server._pool.shutdown(wait=True)
