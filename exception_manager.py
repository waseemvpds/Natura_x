"""Exception-facing helpers; persistence and identity live in Database."""
from __future__ import annotations

from database import Database


def active_exceptions(database: Database):
    return database.list_exceptions(include_resolved=False)
