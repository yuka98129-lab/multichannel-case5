"""
案件5 - キュー(順番待ちの列)のデータベース
本番は Supabase(PostgreSQL)想定。この環境からは接続できないので、手元の SQLite で代用している。
テーブルの形は講座の inquiry_queue と同じ。
"""
import os
import sqlite3
import time

DB_PATH = os.environ.get("CASE5_DB", os.path.join(os.path.dirname(__file__), "queue.db"))


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(reset=False):
    if reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS inquiry_queue (
              id            INTEGER PRIMARY KEY AUTOINCREMENT,
              channel       TEXT NOT NULL,
              external_id   TEXT UNIQUE,          -- 重複防止の鍵(同じ番号は2回保存できない)
              raw_content   TEXT NOT NULL,
              category      TEXT,
              is_urgent     INTEGER DEFAULT 0,
              status        TEXT DEFAULT 'pending',  -- pending / classified / notified / failed
              error         TEXT,
              received_at   REAL,
              classified_at REAL,
              notified_at   REAL
            );
            CREATE INDEX IF NOT EXISTS idx_inquiry_status ON inquiry_queue(status, received_at);

            -- 「送ったつもり」の記録(本物のSlack/LINEには送れないので、ここに残す)
            CREATE TABLE IF NOT EXISTS outbox (
              id         INTEGER PRIMARY KEY AUTOINCREMENT,
              kind       TEXT NOT NULL,      -- slack / line_push
              target     TEXT NOT NULL,      -- Slackチャネル名 or LINEのユーザーID
              body       TEXT NOT NULL,
              ref        TEXT,               -- 元の問い合わせ番号
              sent_at    REAL
            );
            """
        )


def insert_inquiry(channel, external_id, raw_content, status="pending"):
    """保存できたら True。同じ external_id が既にあれば False(= 重複なので処理しない)。"""
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO inquiry_queue (channel, external_id, raw_content, status, received_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (channel, external_id, raw_content, status, time.time()),
            )
        return True
    except sqlite3.IntegrityError:
        return False


def update_inquiry(external_id, **fields):
    sets = ", ".join(f"{k} = ?" for k in fields)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE inquiry_queue SET {sets} WHERE external_id = ?",
            (*fields.values(), external_id),
        )


def fetch_rows(statuses, limit=20):
    marks = ",".join("?" for _ in statuses)
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM inquiry_queue WHERE status IN ({marks}) ORDER BY received_at LIMIT ?",
            (*statuses, limit),
        ).fetchall()


def get_row(external_id):
    with get_conn() as conn:
        return conn.execute(
            "SELECT * FROM inquiry_queue WHERE external_id = ?", (external_id,)
        ).fetchone()
