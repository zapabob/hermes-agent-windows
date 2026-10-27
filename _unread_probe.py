import sqlite3, os
paths = [
    r"C:\Users\downl\.hermes\state.db",
    r"C:\Users\downl\.hermes\profiles\delivery-worker\state.db",
]
for p in paths:
    print("=====", p, "exists=", os.path.exists(p))
for p in paths:
    if not os.path.exists(p):
        continue
    con = sqlite3.connect("file:"+p+"?mode=ro", uri=True)
    c = con.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in c.fetchall()]
    print("  tables:", tables)
    for t in tables:
        try:
            c.execute(f"PRAGMA table_info({t})")
            cols = [r[1] for r in c.fetchall()]
            c.execute(f"SELECT COUNT(*) FROM {t}")
            n = c.fetchone()[0]
            print(f"  {t}: n={n} cols={cols[:8]}")
        except Exception as e:
            print(f"  {t}: ERR {e}")
    con.close()
print("DONE")
