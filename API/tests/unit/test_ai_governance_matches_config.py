"""La página «Gobierno de la IA» dice el proveedor y el modelo que se despliegan.

``web/app/src/views/public/AiGovernanceView.vue`` anuncia a qué proveedor y con
qué modelo se envían los datos. Si ``tools.scribe`` cambia en
``SecOpsConfig.json`` y la página no, la página pasa a decir algo falso sin que
nada falle. Este test lo impide.

También ata los enlaces que apuntan a ella: cada aviso de «generado con IA»
enlaza a ``/gobierno-ia#<herramienta>``, y esa ancla tiene que existir.
"""
import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[3]
_VIEW = _REPO_ROOT / "web" / "app" / "src" / "views" / "public" / "AiGovernanceView.vue"
_CONFIG = _REPO_ROOT / "API" / "SecOpsConfig.json"
_TEMPLATES = _REPO_ROOT / "API" / "src" / "modules" / "tools" / "herald" / "templates" / "es"


def _scribe_config() -> dict:
    return json.loads(_CONFIG.read_text(encoding="utf-8"))["tools"]["scribe"]


def test_the_page_announces_the_deployed_default_provider():
    view = _VIEW.read_text(encoding="utf-8")
    announced = re.search(r"const AI_PROVIDER_NAME = '([^']+)'", view)

    assert announced is not None, "AiGovernanceView.vue ya no declara AI_PROVIDER_NAME"
    assert announced.group(1).lower() == _scribe_config()["defaultStrategy"].lower(), (
        f"La página anuncia {announced.group(1)} y el proveedor por defecto es "
        f"{_scribe_config()['defaultStrategy']}"
    )


def test_the_page_announces_the_deployed_default_model():
    view = _VIEW.read_text(encoding="utf-8")
    announced = re.search(r"const AI_MODEL = '([^']+)'", view)
    config = _scribe_config()
    deployed = config["strategies"][config["defaultStrategy"]]["model"]

    assert announced is not None, "AiGovernanceView.vue ya no declara AI_MODEL"
    assert announced.group(1) == deployed, f"La página anuncia {announced.group(1)} y se despliega {deployed}"


def test_every_tool_that_uses_ai_has_its_section_on_the_page():
    """Cada módulo con IA en la config tiene su apartado, que es el ancla de sus avisos."""
    view = _VIEW.read_text(encoding="utf-8")
    tools = re.search(r"const TOOLS = \[([^\]]*)\]", view)
    assert tools is not None, "AiGovernanceView.vue ya no declara TOOLS"
    documented = set(re.findall(r"'([a-z]+)'", tools.group(1)))

    assert documented == set(_scribe_config()["modules"]), (
        "La página documenta herramientas distintas de las que usan IA en tools.scribe.modules"
    )


def test_the_campaign_email_links_to_an_existing_anchor():
    """El correo enlaza a ``/gobierno-ia#aegis``; si el apartado se renombra el enlace se rompe."""
    view = _VIEW.read_text(encoding="utf-8")
    assert "'aegis'" in view

    campaign = (_TEMPLATES / "campaign.html.j2").read_text(encoding="utf-8")
    assert "ai_governance_url" in campaign
