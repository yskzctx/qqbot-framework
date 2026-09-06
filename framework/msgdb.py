"""消息数据库：把 QQ 收到的全部消息存入 SQLite，支持查询与按规则清理。

存储位置：QQBotData/data/messages.db
清理规则（面板「数据库」页配置，config -> message_db）：
- retention_days: 保留最近 N 天（0 = 不按天清理）
- daily_clear_time: 每天 HH:MM 清空全部（空 = 不定时清空）
"""
import logging
import os
import sqlite3
import threading

log = logging.getLogger("msgdb")
from datetime import datetime, timedelta

from framework.paths import DATA_DIR

DB_PATH = os.path.join(DATA_DIR, "data", "messages.db")


class MessageDB:
    def __init__(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self._lock = threading.Lock()
        self._create()

    def _connect(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def _create(self):
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("""CREATE TABLE IF NOT EXISTS messages(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    time TEXT NOT NULL,
                    message_type TEXT,
                    chat_id TEXT,
                    user_id TEXT,
                    nickname TEXT,
                    raw_message TEXT,
                    message_id INTEGER)""")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_ts ON messages(ts)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_chat ON messages(chat_id)")
                conn.commit()
            finally:
                conn.close()

    # ---------- 写入 ----------

    def add(self, event: dict):
        try:
            msg_type = event.get("message_type", "private")
            chat_id = str(event.get("group_id") or event.get("user_id") or "")
            user_id = str(event.get("user_id") or "")
            sender = event.get("sender") or {}
            nickname = str(sender.get("nickname") or sender.get("card") or user_id)
            ts = event.get("time") or datetime.now().timestamp()
            row = (float(ts),
                   datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S"),
                   msg_type, chat_id, user_id, nickname,
                   str(event.get("raw_message", "")),
                   event.get("message_id"))
            with self._lock:
                conn = self._connect()
                try:
                    conn.execute(
                        "INSERT INTO messages (ts, time, message_type, chat_id, "
                        "user_id, nickname, raw_message, message_id) "
                        "VALUES (?,?,?,?,?,?,?,?)", row)
                    conn.commit()
                finally:
                    conn.close()
        except Exception as e:
            logging.getLogger("msgdb").warning("消息入库失败: %s", e)

    # ---------- 查询 ----------

    def query(self, limit=100, offset=0, msg_type=None, chat_id=None,
              keyword=None) -> dict:
        where, params = [], []
        if msg_type in ("group", "private"):
            where.append("message_type=?")
            params.append(msg_type)
        if chat_id:
            where.append("chat_id=?")
            params.append(str(chat_id))
        if keyword:
            where.append("raw_message LIKE ?")
            params.append(f"%{keyword}%")
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        with self._lock:
            conn = self._connect()
            try:
                total = conn.execute(
                    f"SELECT COUNT(*) FROM messages {clause}", params).fetchone()[0]
                rows = conn.execute(
                    f"SELECT * FROM messages {clause} ORDER BY id DESC LIMIT ? OFFSET ?",
                    params + [limit, offset]).fetchall()
            finally:
                conn.close()
        return {"total": total, "rows": [dict(r) for r in rows]}

    def stats(self) -> dict:
        with self._lock:
            conn = self._connect()
            try:
                total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
                first = conn.execute("SELECT MIN(time) FROM messages").fetchone()[0]
                days = conn.execute("""
                    SELECT substr(time, 1, 10) AS day, COUNT(*) AS c
                    FROM messages GROUP BY day ORDER BY day DESC LIMIT 7""").fetchall()
            finally:
                conn.close()
        return {"total": total,
                "size_mb": round(os.path.getsize(DB_PATH) / 1048576, 2)
                           if os.path.exists(DB_PATH) else 0,
                "first_time": first,
                "days": [dict(d) for d in days]}

    # ---------- 清理 ----------

    def clear_all(self):
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("DELETE FROM messages")
                conn.commit()
                conn.execute("VACUUM")
            finally:
                conn.close()

    def clear_before(self, days: int) -> int:
        cutoff = (datetime.now() - timedelta(days=days)).timestamp()
        with self._lock:
            conn = self._connect()
            try:
                cur = conn.execute("DELETE FROM messages WHERE ts < ?", (cutoff,))
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()
