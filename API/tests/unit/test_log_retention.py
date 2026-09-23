"""
Tests de la retención del registro de actividad (``log_retention.py``).

El registro guarda la IP de cada visita. Se fija que el fichero del día se
archiva con la fecha de ayer, que no se pisa un archivado existente y que se
borran solo los archivados que pasan del plazo.
"""
from datetime import date

import pytest

from src.modules.system.services.log_retention import apply_log_retention

pytestmark = pytest.mark.unit

_TODAY = date(2026, 9, 23)


def _write(path, text="linea\n"):
    path.write_text(text, encoding="utf-8")
    return path


def test_the_current_log_is_archived_with_yesterdays_date(tmp_path):
    log_file = _write(tmp_path / "secops.log")

    result = apply_log_retention(log_file, _TODAY, retention_days=30)

    assert result.archived_file == tmp_path / "secops.log.2026-09-22"
    assert result.archived_file.read_text(encoding="utf-8") == "linea\n"
    assert not log_file.exists()


def test_an_empty_or_missing_log_is_not_archived(tmp_path):
    assert apply_log_retention(tmp_path / "secops.log", _TODAY, 30).archived_file is None

    empty_log = _write(tmp_path / "secops.log", "")
    assert apply_log_retention(empty_log, _TODAY, 30).archived_file is None
    assert empty_log.exists()


def test_an_existing_archive_for_that_day_is_not_overwritten(tmp_path):
    """Si la pasada se repite el mismo día, no se pierde el archivado anterior."""
    _write(tmp_path / "secops.log.2026-09-22", "archivado\n")
    log_file = _write(tmp_path / "secops.log", "nuevo\n")

    result = apply_log_retention(log_file, _TODAY, 30)

    assert result.archived_file is None
    assert (tmp_path / "secops.log.2026-09-22").read_text(encoding="utf-8") == "archivado\n"
    assert log_file.read_text(encoding="utf-8") == "nuevo\n"


def test_only_archives_past_the_retention_period_are_deleted(tmp_path):
    kept = _write(tmp_path / "secops.log.2026-08-24")      # justo en el límite de 30 días
    expired = _write(tmp_path / "secops.log.2026-08-23")
    unrelated = _write(tmp_path / "secops.log.backup")
    other_log = _write(tmp_path / "otro.log.2026-01-01")

    result = apply_log_retention(tmp_path / "secops.log", _TODAY, retention_days=30)

    assert result.deleted_files == [expired]
    assert kept.exists() and unrelated.exists() and other_log.exists()
    assert not expired.exists()


def test_a_retention_below_one_day_is_treated_as_one(tmp_path):
    yesterday = _write(tmp_path / "secops.log.2026-09-22")
    two_days_ago = _write(tmp_path / "secops.log.2026-09-21")

    apply_log_retention(tmp_path / "secops.log", _TODAY, retention_days=0)

    assert yesterday.exists()
    assert not two_days_ago.exists()
