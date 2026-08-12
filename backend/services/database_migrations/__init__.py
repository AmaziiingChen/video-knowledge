"""Versioned SQLite migration registry.

Historical segments are immutable. New migrations belong in the final segment
until it approaches the architecture line budget, then that segment is archived
and a new one is started. Registry discovery keeps execution ordered by the
numeric migration prefix rather than source-file layout.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from types import ModuleType

from services.database_migrations import segment_01, segment_02, segment_03, segment_04


SCHEMA_VERSION = 93
Migration = Callable[[sqlite3.Connection], None]
_MIGRATION_NAME = re.compile(r"^_migration_(\d{3})_")
_SEGMENTS = (segment_01, segment_02, segment_03, segment_04)
_INTENTIONAL_VERSION_GAPS = {49, 78}


def _discover_migrations(modules: tuple[ModuleType, ...]) -> tuple[tuple[int, Migration], ...]:
    discovered: dict[int, Migration] = {}
    for module in modules:
        for name in dir(module):
            match = _MIGRATION_NAME.match(name)
            if not match:
                continue
            version = int(match.group(1))
            if version in discovered:
                raise RuntimeError(f"duplicate database migration version: {version}")
            migration = getattr(module, name)
            if callable(migration):
                discovered[version] = migration
    migrations = tuple(sorted(discovered.items()))
    expected_versions = set(range(1, SCHEMA_VERSION + 1)) - _INTENTIONAL_VERSION_GAPS
    if set(discovered) != expected_versions:
        missing = sorted(expected_versions - set(discovered))
        unexpected = sorted(set(discovered) - expected_versions)
        raise RuntimeError(
            f"database migration registry mismatch; missing={missing}, unexpected={unexpected}"
        )
    return migrations


MIGRATIONS = _discover_migrations(_SEGMENTS)


def migration_named(name: str) -> Migration:
    """Return an individual migration for repair tests and maintenance tools."""
    if not _MIGRATION_NAME.match(name):
        raise AttributeError(name)
    for module in _SEGMENTS:
        migration = getattr(module, name, None)
        if callable(migration):
            return migration
    raise AttributeError(name)


__all__ = ["MIGRATIONS", "SCHEMA_VERSION", "migration_named"]
