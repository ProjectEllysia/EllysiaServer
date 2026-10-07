"""La versión de la declaración que acepta el usuario es la que valida el servidor.

La interfaz manda con cada autorización la versión del texto que enseñó
(``authorizationDeclaration.js``) y el servidor la compara con la suya
(``AUTHORIZATION_DECLARATION_VERSION``). Si una cambia y la otra no, toda
autorización se rechazaría con un 409 de «el texto ha cambiado» sin que ningún
test del servidor lo viera. Este test lo impide.
"""
import re
from pathlib import Path

import pytest

from src.modules.features.themis.managers.authorized_target import AUTHORIZATION_DECLARATION_VERSION

pytestmark = pytest.mark.unit

_SPA_CONSTANT = (
    Path(__file__).resolve().parents[3]
    / "web" / "app" / "src" / "components" / "themis" / "authorizationDeclaration.js"
)


def test_authorization_declaration_version_matches_the_spa():
    announced = re.search(
        r"export const AUTHORIZATION_DECLARATION_VERSION = '([^']+)'",
        _SPA_CONSTANT.read_text(encoding="utf-8"),
    )

    assert announced is not None, "authorizationDeclaration.js ya no declara AUTHORIZATION_DECLARATION_VERSION"
    assert announced.group(1) == AUTHORIZATION_DECLARATION_VERSION, (
        f"La interfaz envía la versión {announced.group(1)} y el servidor espera "
        f"{AUTHORIZATION_DECLARATION_VERSION}"
    )
