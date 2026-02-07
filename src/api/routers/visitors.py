"""
TrippixnBot - Visitors Router
=============================

Track and count portfolio visitors.

Author: حَـــــنَّـــــا
"""

import sqlite3
from datetime import datetime, date
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel

from src.core import log


# Models

class VisitorData(BaseModel):
    """Visitor count response."""
    total: int
    today: int = 0
    tracked: bool = False


# Database

DB_PATH = Path("data/visitors.db")


def get_db() -> sqlite3.Connection:
    """Get database connection."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize visitors database."""
    conn = get_db()
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS visitors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            visited_at TEXT NOT NULL,
            visit_date TEXT NOT NULL
        )
    ''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_visit_date ON visitors(visit_date)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_ip_date ON visitors(ip, visit_date)')
    conn.commit()
    conn.close()
    log.debug("Visitors DB Initialized", [("Path", str(DB_PATH))])


# Initialize on import
init_db()


# Router

router = APIRouter(tags=["Visitors"])


@router.get("/visitors")
async def get_visitors() -> VisitorData:
    """Get total visitor count."""
    conn = get_db()
    c = conn.cursor()

    # Count unique visitor sessions (unique IP per day)
    c.execute("SELECT COUNT(DISTINCT ip || '-' || visit_date) FROM visitors")
    total = c.fetchone()[0] or 0

    # Count today's visitors
    today = date.today().isoformat()
    c.execute("SELECT COUNT(DISTINCT ip) FROM visitors WHERE visit_date = ?", (today,))
    today_count = c.fetchone()[0] or 0

    conn.close()

    return VisitorData(total=total, today=today_count)


@router.post("/visitors/track")
async def track_visitor(request: Request) -> VisitorData:
    """Track a visitor and return updated count."""
    # Get client IP (handle proxies)
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"

    today = date.today().isoformat()
    now = datetime.utcnow().isoformat()

    conn = get_db()
    c = conn.cursor()

    # Check if already tracked today
    c.execute("SELECT 1 FROM visitors WHERE ip = ? AND visit_date = ?", (ip, today))
    already_tracked = c.fetchone() is not None

    if not already_tracked:
        c.execute(
            "INSERT INTO visitors (ip, visited_at, visit_date) VALUES (?, ?, ?)",
            (ip, now, today)
        )
        conn.commit()
        log.debug("Visitor Tracked", [("IP", ip[:16] + "...")])

    # Get counts
    c.execute("SELECT COUNT(DISTINCT ip || '-' || visit_date) FROM visitors")
    total = c.fetchone()[0] or 0

    c.execute("SELECT COUNT(DISTINCT ip) FROM visitors WHERE visit_date = ?", (today,))
    today_count = c.fetchone()[0] or 0

    conn.close()

    return VisitorData(total=total, today=today_count, tracked=not already_tracked)


__all__ = ["router"]
