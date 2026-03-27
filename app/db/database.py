"""SQLite 会话数据库"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
from contextlib import contextmanager


class ConversationDatabase:
    def __init__(self, db_path: str = "conversations.db"):
        self.db_path = Path(db_path)
        self._init_database()
    
    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _init_database(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    title TEXT,
                    message_count INTEGER DEFAULT 0,
                    last_activity TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            
            # 迁移：添加 title 字段（如果不存在）
            try:
                cursor.execute("ALTER TABLE conversations ADD COLUMN title TEXT")
            except sqlite3.OperationalError:
                pass  # 字段已存在
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    qdrant_records TEXT,
                    extra_payload TEXT,
                    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id)")
            
            # 迁移：添加 qdrant_records 字段（如果不存在）
            try:
                cursor.execute("ALTER TABLE messages ADD COLUMN qdrant_records TEXT")
            except sqlite3.OperationalError:
                pass  # 字段已存在
            # 迁移：添加 extra_payload 字段（如果不存在）
            try:
                cursor.execute("ALTER TABLE messages ADD COLUMN extra_payload TEXT")
            except sqlite3.OperationalError:
                pass  # 字段已存在
    
    def create_conversation(self, conversation_id: str, title: str = None) -> None:
        now = datetime.now().isoformat()
        with self._get_connection() as conn:
            conn.cursor().execute(
                "INSERT OR IGNORE INTO conversations (conversation_id, title, message_count, last_activity, created_at) VALUES (?, ?, 0, ?, ?)",
                (conversation_id, title, now, now)
            )
    
    def update_conversation_title(self, conversation_id: str, title: str) -> None:
        """更新会话标题"""
        with self._get_connection() as conn:
            conn.cursor().execute(
                "UPDATE conversations SET title = ? WHERE conversation_id = ?",
                (title, conversation_id)
            )
    
    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        timestamp: Optional[str] = None,
        qdrant_records: Optional[str] = None,
        extra_payload: Optional[str] = None,
    ) -> None:
        timestamp = timestamp or datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO messages (conversation_id, role, content, timestamp, qdrant_records, extra_payload) VALUES (?, ?, ?, ?, ?, ?)",
                (conversation_id, role, content, timestamp, qdrant_records, extra_payload),
            )
            cursor.execute("UPDATE conversations SET message_count = message_count + 1, last_activity = ? WHERE conversation_id = ?",
                          (timestamp, conversation_id))
    
    def get_conversations(self) -> List[Dict]:
        with self._get_connection() as conn:
            rows = conn.cursor().execute("SELECT conversation_id, title, message_count, last_activity FROM conversations ORDER BY last_activity DESC").fetchall()
            return [{"conversation_id": r["conversation_id"], "title": r["title"], "message_count": r["message_count"], "last_activity": r["last_activity"]} for r in rows]
    
    def get_messages(self, conversation_id: str) -> List[Dict]:
        with self._get_connection() as conn:
            rows = conn.cursor().execute(
                "SELECT role, content, timestamp, qdrant_records, extra_payload FROM messages WHERE conversation_id = ? ORDER BY id ASC",
                (conversation_id,),
            ).fetchall()
            return [
                {
                    "role": r["role"],
                    "content": r["content"],
                    "timestamp": r["timestamp"],
                    "qdrant_records": r["qdrant_records"],
                    "extra_payload": r["extra_payload"],
                }
                for r in rows
            ]
    
    def conversation_exists(self, conversation_id: str) -> bool:
        with self._get_connection() as conn:
            row = conn.cursor().execute("SELECT COUNT(*) as count FROM conversations WHERE conversation_id = ?", (conversation_id,)).fetchone()
            return row["count"] > 0
    
    def delete_conversation(self, conversation_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            cursor.execute("DELETE FROM conversations WHERE conversation_id = ?", (conversation_id,))
            return cursor.rowcount > 0


_db_instance: Optional[ConversationDatabase] = None

def get_database(db_path: str = None) -> ConversationDatabase:
    global _db_instance
    if _db_instance is None:
        if db_path is None:
            # 默认在 app/db/ 目录下创建数据库
            db_dir = Path(__file__).parent
            db_path = str(db_dir / "conversations.db")
        _db_instance = ConversationDatabase(db_path)
    return _db_instance
