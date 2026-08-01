import os
import sqlite3
from pathlib import Path

root = Path(os.environ["APPDATA"]) / "botbuilder-desktop" / "data" / "projects"
for db in sorted(root.glob("bot_*/user_data.db")):
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    print("==", db.parent.name, "tables", sorted(x for x in tables if "publish" in x or x == "channel_posts"))
    if "publisher_posts" in tables:
        rows = conn.execute(
            "SELECT id, status, telegram_message_id, substr(COALESCE(text_html,''),1,50) AS t "
            "FROM publisher_posts ORDER BY id"
        ).fetchall()
        print(" publisher_posts", len(rows))
        for r in rows:
            print(" ", dict(r))
    if "channel_posts" in tables:
        n = conn.execute("SELECT COUNT(*) FROM channel_posts").fetchone()[0]
        print(" channel_posts", n)
    conn.close()
