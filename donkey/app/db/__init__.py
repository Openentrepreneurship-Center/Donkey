"""MySQL DB layer for consultation / log / summary persistence."""

from app.db.session import get_session, init_db, is_db_configured

__all__ = ["get_session", "init_db", "is_db_configured"]
