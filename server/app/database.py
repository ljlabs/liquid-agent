"""
SQLite persistence layer for sessions and messages.

Provides async wrappers around sqlite3 (which is sync) so the rest of the
app can stay fully async without blocking the event loop on DB I/O.
"""

from __future__ import annotations

import aiosqlite
import time
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).parent.parent / "data" / "sessions.db"

_db: Optional[aiosqlite.Connection] = None


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _db = await aiosqlite.connect(str(DB_PATH))
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
        await _init_schema(_db)
    return _db


async def close_db() -> None:
    global _db
    if _db is not None:
        await _db.close()
        _db = None


async def _init_schema(db: aiosqlite.Connection) -> None:
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id              TEXT PRIMARY KEY,
            title           TEXT NOT NULL DEFAULT 'New Session',
            cwd             TEXT NOT NULL DEFAULT '',
            model           TEXT NOT NULL DEFAULT 'claude-sonnet-4-6',
            permission_mode TEXT NOT NULL DEFAULT 'default',
            status          TEXT NOT NULL DEFAULT 'idle',
            created_at      REAL NOT NULL,
            updated_at      REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            role        TEXT NOT NULL,
            type        TEXT NOT NULL DEFAULT 'text',
            content     TEXT NOT NULL DEFAULT '',
            tool_name   TEXT,
            tool_id     TEXT,
            tool_input  TEXT,
            created_at  REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
    """)
    await db.commit()


# ------------------------------------------------------------------
# Session CRUD
# ------------------------------------------------------------------

async def create_session(
    *,
    session_id: str,
    title: str = "New Session",
    cwd: str = "",
    model: str = "claude-sonnet-4-6",
    permission_mode: str = "default",
) -> dict:
    now = time.time()
    db = await get_db()
    await db.execute(
        """INSERT INTO sessions (id, title, cwd, model, permission_mode, status, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 'idle', ?, ?)""",
        (session_id, title, cwd, model, permission_mode, now, now),
    )
    await db.commit()
    return await get_session(session_id)


async def get_session(session_id: str) -> Optional[dict]:
    db = await get_db()
    cursor = await db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def update_session(session_id: str, **fields) -> None:
    if not fields:
        return
    fields["updated_at"] = time.time()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [session_id]
    db = await get_db()
    await db.execute(f"UPDATE sessions SET {set_clause} WHERE id = ?", values)
    await db.commit()


async def list_sessions(limit: int = 50) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?", (limit,)
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def delete_session(session_id: str) -> bool:
    db = await get_db()
    cursor = await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    await db.commit()
    return cursor.rowcount > 0


# ------------------------------------------------------------------
# Message CRUD
# ------------------------------------------------------------------

async def add_message(
    *,
    session_id: str,
    role: str,
    type: str = "text",
    content: str = "",
    tool_name: str | None = None,
    tool_id: str | None = None,
    tool_input: str | None = None,
) -> int:
    now = time.time()
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO messages (session_id, role, type, content, tool_name, tool_id, tool_input, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, role, type, content, tool_name, tool_id, tool_input, now),
    )
    await db.commit()
    # Bump session updated_at
    await update_session(session_id)
    return cursor.lastrowid


async def get_messages(session_id: str) -> list[dict]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY id", (session_id,)
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def get_message_count(session_id: str) -> int:
    db = await get_db()
    cursor = await db.execute(
        "SELECT COUNT(*) as cnt FROM messages WHERE session_id = ?", (session_id,)
    )
    row = await cursor.fetchone()
    return row["cnt"] if row else 0
