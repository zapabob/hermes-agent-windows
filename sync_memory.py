import sqlite3
import os

db_path = os.path.expanduser('~/.hermes/ebbinghaus_memory.db')
conn = sqlite3.connect(db_path)
cur = conn.cursor()

# Check table schema
cur.execute('PRAGMA table_info(memories)')
print('Table info:', cur.fetchall())

# Count total rows
cur.execute('SELECT count(*) FROM memories')
print('Total rows:', cur.fetchone())

# Sample rows
cur.execute('SELECT * FROM memories LIMIT 5')
print('Sample rows:')
for r in cur.fetchall():
    print(r)

conn.close()