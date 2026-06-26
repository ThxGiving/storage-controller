"""Tests for backup creation, validation, and restore staging (Phase 7).

Uses a temporary data directory to avoid touching real data.  The SQLite
backup API is exercised against a real (though tiny) database file.
"""

from __future__ import annotations

import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from app.backup import (
    BACKUP_FORMAT_VERSION,
    ValidationResult,
    _build_archive_sync,
    _current_schema_revision,
    _extract_to_staging_sync,
    _sha256_bytes,
    _validate_archive_sync,
    complete_pending_restore,
    list_backup_files,
)


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture
def db_path(data_dir: Path) -> Path:
    """Create a minimal valid SQLite database with an alembic_version table."""
    p = data_dir / "storage-controller.db"
    conn = sqlite3.connect(str(p))
    conn.execute(
        "CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)"
    )
    conn.execute("INSERT INTO alembic_version VALUES ('0012_backups')")
    conn.execute("CREATE TABLE units (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO units VALUES (1, 'TK-Fleisch')")
    conn.commit()
    conn.close()
    return p


@pytest.fixture
def archive_bytes(db_path: Path, data_dir: Path) -> bytes:
    """A valid backup archive built from the test database."""
    (data_dir / "reports").mkdir()
    (data_dir / "reports" / "uuid-abc").mkdir()
    (data_dir / "reports" / "uuid-abc" / "report.pdf").write_bytes(b"%PDF test")
    (data_dir / "uploads").mkdir()
    (data_dir / "uploads" / "logo_test.png").write_bytes(b"\x89PNG test")

    archive, _ = _build_archive_sync(
        db_path=db_path,
        data_dir=data_dir,
        schema_revision="0012_backups",
        app_version="0.9.0",
        note="unit test",
    )
    return archive


# ── Archive structure ──────────────────────────────────────────────────────────


def test_archive_is_valid_zip(archive_bytes: bytes):
    assert zipfile.is_zipfile(io.BytesIO(archive_bytes))


def test_archive_contains_manifest(archive_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
        assert "manifest.json" in zf.namelist()


def test_archive_contains_database(archive_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
        assert "db/database.sqlite" in zf.namelist()


def test_archive_contains_report_file(archive_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
        assert "reports/uuid-abc/report.pdf" in zf.namelist()


def test_archive_contains_upload_file(archive_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
        assert "uploads/logo_test.png" in zf.namelist()


# ── Manifest content ───────────────────────────────────────────────────────────


def test_manifest_format_version(archive_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
        m = json.loads(zf.read("manifest.json"))
    assert m["format_version"] == BACKUP_FORMAT_VERSION


def test_manifest_app_version(archive_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
        m = json.loads(zf.read("manifest.json"))
    assert m["app_version"] == "0.9.0"


def test_manifest_schema_revision(archive_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
        m = json.loads(zf.read("manifest.json"))
    assert m["schema_revision"] == "0012_backups"


def test_manifest_checksums_present(archive_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
        m = json.loads(zf.read("manifest.json"))
    for entry in m["files"]:
        assert "sha256" in entry
        assert len(entry["sha256"]) == 64  # SHA-256 hex


def test_manifest_checksums_correct(archive_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
        m = json.loads(zf.read("manifest.json"))
        for entry in m["files"]:
            actual = _sha256_bytes(zf.read(entry["path"]))
            assert actual == entry["sha256"], f"Checksum mismatch for {entry['path']}"


# ── Database snapshot integrity ────────────────────────────────────────────────


def test_backup_db_is_valid_sqlite(archive_bytes: bytes):
    with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
        db_bytes = zf.read("db/database.sqlite")

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        f.write(db_bytes)
        tmp_path = Path(f.name)
    try:
        conn = sqlite3.connect(str(tmp_path))
        rows = conn.execute("PRAGMA integrity_check").fetchall()
        conn.close()
        assert rows == [("ok",)]
    finally:
        tmp_path.unlink(missing_ok=True)


def test_backup_db_contains_source_data(archive_bytes: bytes):
    """The backup database should contain the units table with the seeded row."""
    with zipfile.ZipFile(io.BytesIO(archive_bytes), "r") as zf:
        db_bytes = zf.read("db/database.sqlite")

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        f.write(db_bytes)
        tmp_path = Path(f.name)
    try:
        conn = sqlite3.connect(str(tmp_path))
        rows = conn.execute("SELECT name FROM units").fetchall()
        conn.close()
        assert ("TK-Fleisch",) in rows
    finally:
        tmp_path.unlink(missing_ok=True)


# ── Schema revision helper ────────────────────────────────────────────────────


def test_current_schema_revision(db_path: Path):
    rev = _current_schema_revision(db_path)
    assert rev == "0012_backups"


def test_current_schema_revision_missing_table(tmp_path: Path):
    p = tmp_path / "empty.db"
    conn = sqlite3.connect(str(p))
    conn.close()
    # Should return "0000" rather than raising.
    assert _current_schema_revision(p) == "0000"


# ── Validation — happy path ───────────────────────────────────────────────────


def test_validate_valid_archive(archive_bytes: bytes, db_path: Path):
    result = _validate_archive_sync(archive_bytes, db_path)
    assert result.valid is True
    assert result.issues == []
    assert result.manifest_summary is not None
    assert result.manifest_summary["app_version"] == "0.9.0"


def test_validate_returns_file_count(archive_bytes: bytes, db_path: Path):
    result = _validate_archive_sync(archive_bytes, db_path)
    assert result.manifest_summary["file_count"] >= 3  # db + report + upload


# ── Validation — failure cases ────────────────────────────────────────────────


def test_validate_not_a_zip(db_path: Path):
    result = _validate_archive_sync(b"not a zip file at all", db_path)
    assert result.valid is False
    assert any("ZIP" in issue or "zip" in issue for issue in result.issues)


def test_validate_missing_manifest(db_path: Path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("db/database.sqlite", b"dummy")
    result = _validate_archive_sync(buf.getvalue(), db_path)
    assert result.valid is False
    assert any("manifest" in i.lower() for i in result.issues)


def test_validate_unsupported_format_version(archive_bytes: bytes, db_path: Path):
    # Tamper with the manifest to set an unsupported format version.
    buf = io.BytesIO(archive_bytes)
    with zipfile.ZipFile(buf, "r") as zf_in:
        names = zf_in.namelist()
        files = {n: zf_in.read(n) for n in names}

    m = json.loads(files["manifest.json"])
    m["format_version"] = 999
    files["manifest.json"] = json.dumps(m).encode()

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf_out:
        for name, data in files.items():
            zf_out.writestr(name, data)

    result = _validate_archive_sync(out.getvalue(), db_path)
    assert result.valid is False
    assert any("999" in i for i in result.issues)


def test_validate_checksum_mismatch(archive_bytes: bytes, db_path: Path):
    buf = io.BytesIO(archive_bytes)
    with zipfile.ZipFile(buf, "r") as zf_in:
        names = zf_in.namelist()
        files = {n: zf_in.read(n) for n in names}

    # Corrupt one of the report files.
    for name in names:
        if name.startswith("reports/"):
            files[name] = b"corrupted data"
            break

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf_out:
        for name, data in files.items():
            zf_out.writestr(name, data)

    result = _validate_archive_sync(out.getvalue(), db_path)
    assert result.valid is False
    assert any("Checksum" in i or "checksum" in i for i in result.issues)


def test_validate_newer_schema_rejected(archive_bytes: bytes, tmp_path: Path):
    """A backup with a higher schema revision than the live DB should be rejected."""
    # Create a live DB at an older schema revision.
    old_db = tmp_path / "old.db"
    conn = sqlite3.connect(str(old_db))
    conn.execute(
        "CREATE TABLE alembic_version (version_num TEXT NOT NULL PRIMARY KEY)"
    )
    conn.execute("INSERT INTO alembic_version VALUES ('0001_initial')")
    conn.commit()
    conn.close()

    result = _validate_archive_sync(archive_bytes, old_db)
    assert result.valid is False
    assert any("schema" in i.lower() or "revision" in i.lower() for i in result.issues)


def test_validate_path_traversal_rejected(db_path: Path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        m = {
            "format_version": 1,
            "app_version": "0.9.0",
            "schema_revision": "0012_backups",
            "created_at": "2026-06-26T00:00:00+00:00",
            "files": [{"path": "../etc/passwd", "size": 5, "sha256": _sha256_bytes(b"hello")}],
        }
        zf.writestr("manifest.json", json.dumps(m).encode())
        zf.writestr("../etc/passwd", b"hello")

    result = _validate_archive_sync(buf.getvalue(), db_path)
    assert result.valid is False
    assert any("traversal" in i.lower() or "unsafe" in i.lower() for i in result.issues)


# ── Staging extraction ────────────────────────────────────────────────────────


def test_extract_to_staging(archive_bytes: bytes, tmp_path: Path):
    staging = tmp_path / "staging"
    _extract_to_staging_sync(archive_bytes, staging)
    assert (staging / "db" / "database.sqlite").is_file()
    assert (staging / "reports" / "uuid-abc" / "report.pdf").is_file()
    assert (staging / "uploads" / "logo_test.png").is_file()
    # manifest.json should NOT be extracted as a data file
    assert not (staging / "manifest.json").is_file()


def test_extract_overwrites_existing_staging(archive_bytes: bytes, tmp_path: Path):
    staging = tmp_path / "staging"
    # Create a stale file in the staging directory.
    staging.mkdir()
    (staging / "stale.txt").write_text("old")
    _extract_to_staging_sync(archive_bytes, staging)
    assert not (staging / "stale.txt").exists()


# ── complete_pending_restore ──────────────────────────────────────────────────


def test_complete_pending_restore_no_marker(tmp_path: Path, db_path: Path):
    data_dir = db_path.parent
    # No marker file — should return False and not modify anything.
    result = complete_pending_restore(data_dir, db_path)
    assert result is False


def test_complete_pending_restore_replaces_db(
    archive_bytes: bytes, data_dir: Path, db_path: Path
):
    """After staging an archive and completing the restore, the live DB should
    contain the data from the backup."""
    staging = data_dir / ".restore_staging"
    _extract_to_staging_sync(archive_bytes, staging)

    # Write the marker file.
    marker = data_dir / ".restore_pending"
    marker.write_text(
        json.dumps(
            {
                "staging_dir": str(staging),
                "safety_backup": "safety.zip",
                "initiated_at": "2026-06-26T10:00:00+00:00",
            }
        )
    )

    result = complete_pending_restore(data_dir, db_path)
    assert result is True

    # Marker and staging directory should be gone.
    assert not marker.exists()
    assert not staging.exists()

    # The live DB should now contain the seeded data from the backup.
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT name FROM units").fetchall()
    conn.close()
    assert ("TK-Fleisch",) in rows


def test_complete_pending_restore_removes_marker_on_success(
    archive_bytes: bytes, data_dir: Path, db_path: Path
):
    staging = data_dir / ".restore_staging"
    _extract_to_staging_sync(archive_bytes, staging)
    marker = data_dir / ".restore_pending"
    marker.write_text(
        json.dumps({"staging_dir": str(staging), "safety_backup": "", "initiated_at": ""})
    )
    complete_pending_restore(data_dir, db_path)
    assert not marker.exists()


# ── list_backup_files ─────────────────────────────────────────────────────────


def test_list_backup_files_empty(data_dir: Path):
    assert list_backup_files(data_dir) == []


def test_list_backup_files_finds_archives(archive_bytes: bytes, data_dir: Path):
    backups_dir = data_dir / "backups"
    backups_dir.mkdir()
    (backups_dir / "backup_2026-06-26T10-00-00Z.zip").write_bytes(archive_bytes)
    (backups_dir / "backup_2026-06-27T10-00-00Z.zip").write_bytes(archive_bytes)

    results = list_backup_files(data_dir)
    assert len(results) == 2
    # Newest first.
    assert "2026-06-27" in results[0]["filename"]


def test_list_backup_files_includes_manifest_summary(archive_bytes: bytes, data_dir: Path):
    backups_dir = data_dir / "backups"
    backups_dir.mkdir()
    (backups_dir / "backup_2026-06-26T10-00-00Z.zip").write_bytes(archive_bytes)

    results = list_backup_files(data_dir)
    assert results[0]["manifest"] is not None
    assert results[0]["manifest"]["app_version"] == "0.9.0"
