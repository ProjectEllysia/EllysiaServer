"""
Las imágenes de marca no se replican en ``API/resources``.

El original de cada imagen está en la SPA (``web/app/src/assets/images/``).
Cuando un informe de la API necesita una, se copia reducida al módulo que la
usa (``features/<módulo>/resources/``). Una copia completa del árbol de la SPA
dentro de ``API/resources`` no la carga nada, pero viaja en cada imagen de
Docker y pesa megas.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_RESOURCES_DIRECTORY = Path(__file__).resolve().parents[2] / "resources"
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}


def test_api_resources_holds_no_brand_images():
    images = sorted(
        path.relative_to(_RESOURCES_DIRECTORY).as_posix()
        for path in _RESOURCES_DIRECTORY.rglob("*")
        if path.suffix.lower() in _IMAGE_SUFFIXES
    )
    assert images == [], f"imágenes que deberían vivir en la SPA o en su módulo: {images}"
