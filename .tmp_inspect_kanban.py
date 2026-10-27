import sqlite3, json, os

def dump_tables(path):
    try:
        c=sqlite3.connect(f"file:{path}?mode=ro",uri=True)
        tabs=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        c.close()
        return tabs
    except Exception as e:
        return f"ERR {e}"

print("=== kanban DB tables ===")
for p in [
    "C:/Users/downl/.hermes/kanban.db",
    "C:/Users/downl/.hermes/kanban/boards/ai-company/kanban.db",
    "C:/Users/downl/.hermes/kanban/boards/hakuapulse-lite-free/kanban.db",
    "C:/Users/downl/.hermes/kanban/boards/sedori-ops/kanban.db",
]:
    print(p, "=>", dump_tables(p))

print()
print("=== state.db tables ===")
p="C:/Users/downl/.hermes/profiles/delivery-worker/state.db"
tabs=dump_tables(p)
print(tabs)

def count_tables(path, tablist):
    try:
        c=sqlite3.connect(f"file:{path}?mode=ro",uri=True)
        out={}
        for t in tablist:
            try:
                n=c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                out[t]=n
            except Exception as e:
                out[t]=f"ERR {e}"
        c.close()
        return out
    except Exception as e:
        return f"ERR {e}"

print()
print("=== state.db counts ===")
print(json.dumps(count_tables(p, ["sessions","gateway_routing","messages","pending_messages","channel_directory"]), indent=2, ensure_ascii=False))

# sessions by source
try:
    c=sqlite3.connect(f"file:{p}?mode=ro",uri=True)
    rows=c.execute("SELECT source, COUNT(*) FROM sessions GROUP BY source ORDER BY 2 DESC").fetchall()
    c.close()
    print()
    print("=== sessions by source ===")
    for r in rows:
        print("   ", r)
except Exception as e:
    print("ERR sessions", e)