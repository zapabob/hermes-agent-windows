import sqlite3, json, re
from pathlib import Path

ROOT = Path(r"C:\Users\downl\Documents\New project\hermes-agent")
HERMES_HOME = Path.home() / ".hermes"

print("=== HERMES_HOME:", HERMES_HOME, "exists:", HERMES_HOME.exists())

def kanban_tables(dbpath):
    if not dbpath.exists():
        return None
    try:
        c = sqlite3.connect(f"file:{dbpath.as_posix()}?mode=ro", uri=True)
        tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        c.close()
        return tables
    except Exception as e:
        return f"ERROR {e}"

print("\n=== Kanban boards ===")
boards_dir = HERMES_HOME / "kanban" / "boards"
if boards_dir.exists():
    for b in sorted(boards_dir.iterdir()):
        if b.is_dir():
            db = b / "kanban.db"
            print(f"  {b.name}: tables={kanban_tables(db)}")
else:
    print("  no boards dir")
default_db = HERMES_HOME / "kanban.db"
print("  default kanban.db:", default_db, default_db.exists())

print("\n=== state.db tables ===")
state = HERMES_HOME / "state.db"
def relevant_tables(dbpath):
    try:
        c = sqlite3.connect(f"file:{dbpath.as_posix()}?mode=ro", uri=True)
        alltables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        c.close()
        return alltables
    except Exception as e:
        return f"ERROR {e}"
st = relevant_tables(state)
print(f"  total tables: {len(st)}")
print(f"  all: {st}")

print("\n=== Kanban task counts ===")
def cnt(dbpath):
    if not dbpath.exists():
        return None
    c = sqlite3.connect(f"file:{dbpath.as_posix()}?mode=ro", uri=True)
    try:
        n = c.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        c.close()
        return n
    except Exception as e:
        return f"ERR {e}"
print("  default:", cnt(default_db))
for b in sorted(boards_dir.iterdir()):
    if b.is_dir():
        print(f"  {b.name}:", cnt(b/"kanban.db"))

print("\n=== line-personal-bridge ===")
lpb = HERMES_HOME / "plugins" / "line-personal-bridge"
if lpb.exists():
    print("  files:", [f.name for f in lpb.iterdir()])
    node_dir = lpb / "node"
    if node_dir.exists():
        print("  node files:", [f.name for f in node_dir.iterdir()][:40])
