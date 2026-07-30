from __future__ import annotations

import os
import sqlite3
import stat
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from services import database
from config import ensure_private_data_directory
from services.database import (
    DATABASE_BUSY_TIMEOUT_MS,
    connect,
    ensure_database_initialized,
)


def test_connect_waits_for_reader_then_enables_wal(tmp_path):
    db_path = tmp_path / "wal-transition.db"
    blocker = sqlite3.connect(db_path)
    blocker.execute("CREATE TABLE probe (value TEXT)")
    blocker.commit()
    blocker.execute("BEGIN")
    blocker.execute("SELECT * FROM probe").fetchall()

    def open_managed_connection() -> str:
        with connect(db_path) as connection:
            return str(connection.execute("PRAGMA journal_mode").fetchone()[0])

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(open_managed_connection)
        time.sleep(0.15)
        assert not future.done()
        blocker.commit()
        blocker.close()
        assert future.result(timeout=5).lower() == "wal"


def test_connect_waits_for_short_lived_writer(tmp_path):
    db_path = tmp_path / "writer-contention.db"
    with connect(db_path) as connection:
        connection.execute("CREATE TABLE probe (value TEXT)")
        connection.commit()

    blocker = connect(db_path)
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute("INSERT INTO probe(value) VALUES ('blocker')")

    def write_after_blocker() -> None:
        with connect(db_path) as connection:
            connection.execute("INSERT INTO probe(value) VALUES ('worker')")
            connection.commit()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(write_after_blocker)
        time.sleep(0.15)
        assert not future.done()
        blocker.commit()
        blocker.close()
        future.result(timeout=5)

    with connect(db_path) as connection:
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == DATABASE_BUSY_TIMEOUT_MS
        assert connection.execute("SELECT COUNT(*) FROM probe").fetchone()[0] == 2


def test_hot_path_database_ensure_runs_maintenance_once_per_process_path(tmp_path, monkeypatch):
    db_path = tmp_path / "initialized-once.db"
    prompt_sync_calls = 0
    report_prompt_sync_calls = 0

    def record_prompt_sync(_connection) -> None:
        nonlocal prompt_sync_calls
        prompt_sync_calls += 1

    def record_report_prompt_sync(_connection) -> None:
        nonlocal report_prompt_sync_calls
        report_prompt_sync_calls += 1

    monkeypatch.setattr(
        "services.prompt_templates.sync_builtin_prompt_definitions",
        record_prompt_sync,
    )
    monkeypatch.setattr(
        "services.wechat_reports.sync_builtin_report_prompt_definitions",
        record_report_prompt_sync,
    )

    assert database.initialize_database(db_path) == db_path
    assert database.initialize_database(db_path) == db_path
    assert ensure_database_initialized(db_path) == db_path

    assert prompt_sync_calls == 1
    assert report_prompt_sync_calls == 1
    with connect(db_path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()[0] == database.SCHEMA_VERSION


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits are required")
def test_database_and_data_directory_are_private(tmp_path):
    data_dir = tmp_path / "private-data"
    db_path = data_dir / "app.db"

    with database.connect(db_path) as connection:
        connection.execute("CREATE TABLE privacy_check(value TEXT)")
        connection.execute("INSERT INTO privacy_check(value) VALUES ('private')")
        connection.commit()

        assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700
        assert stat.S_IMODE(db_path.stat().st_mode) == 0o600
        for sidecar in (Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
            if sidecar.exists():
                assert stat.S_IMODE(sidecar.stat().st_mode) == 0o600


def test_private_data_directory_rejects_broad_project_root():
    with pytest.raises(ValueError, match="专用子目录"):
        ensure_private_data_directory(ROOT)
