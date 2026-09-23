"""
La nota de privacidad dice el mismo plazo de conservación que se despliega.

``web/app/src/views/public/PrivacyView.vue`` anuncia cuántos días se guarda el
registro de actividad, que anota la IP de cada visita. Si
``general.logs.retentionDays`` cambia en ``SecOpsConfig.json`` y la nota no,
la nota pasa a decir algo falso sin que nada falle. Este test lo impide.
"""
import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PRIVACY_VIEW = _REPO_ROOT / "web" / "app" / "src" / "views" / "public" / "PrivacyView.vue"
_CONFIG = _REPO_ROOT / "API" / "SecOpsConfig.json"


def test_the_privacy_note_announces_the_deployed_log_retention():
    view_source = _PRIVACY_VIEW.read_text(encoding="utf-8")
    announced = re.search(r"const LOG_RETENTION_DAYS = (\d+)", view_source)
    deployed = json.loads(_CONFIG.read_text(encoding="utf-8"))["general"]["logs"]["retentionDays"]

    assert announced is not None, "PrivacyView.vue ya no declara LOG_RETENTION_DAYS"
    assert int(announced.group(1)) == deployed, (
        f"La nota de privacidad anuncia {announced.group(1)} días y se despliegan {deployed}"
    )
