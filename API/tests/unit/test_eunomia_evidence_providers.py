"""El registro de proveedores de evidencia automática y la regla de que Eunomia no conoce a nadie."""

import re
from datetime import date
from pathlib import Path

import pytest

from src.modules.features.eunomia.services import providers as providers_module
from src.modules.features.eunomia.services.providers import AutomaticEvidence, EvidenceProviderRegistry

pytestmark = pytest.mark.unit

_PACKAGE = Path(providers_module.__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch):
    monkeypatch.setattr(EvidenceProviderRegistry, "_providers", {})


def test_a_provider_appears_on_the_controls_it_declares():
    EvidenceProviderRegistry.register(
        "demo.scans", name="Escaneos", controls={"nis2": ("RE.6.10",)},
        collect=lambda owner, framework, identifier: [AutomaticEvidence(
            "Último escaneo", "Hace 3 días", date(2026, 10, 7), "/themis/escaneos")],
    )

    found = EvidenceProviderRegistry.collect(7, "nis2", "RE.6.10")

    assert [(item["providerKey"], item["title"], item["status"], item["link"]) for item in found] == [
        ("demo.scans", "Último escaneo", "ok", "/themis/escaneos")]
    assert EvidenceProviderRegistry.collect(7, "nis2", "RE.3.1") == []
    assert EvidenceProviderRegistry.collect(7, "ens", "RE.6.10") == []


def test_the_provider_receives_the_effective_owner_and_the_control():
    seen = []
    EvidenceProviderRegistry.register(
        "demo.spy", name="Espía", controls={"nis2": ("RE.8.1",)},
        collect=lambda owner, framework, identifier: seen.append((owner, framework, identifier)) or [],
    )

    EvidenceProviderRegistry.collect(42, "nis2", "RE.8.1")

    assert seen == [(42, "nis2", "RE.8.1")]


def test_a_failing_provider_is_shown_as_unavailable_and_the_rest_still_answer():
    def boom(owner, framework, identifier):
        raise RuntimeError("se cayó")

    EvidenceProviderRegistry.register("a.broken", name="Roto", controls={"nis2": ("RE.8.1",)}, collect=boom)
    EvidenceProviderRegistry.register(
        "b.fine", name="Bien", controls={"nis2": ("RE.8.1",)},
        collect=lambda *_: [AutomaticEvidence("Dato", "1")],
    )

    found = EvidenceProviderRegistry.collect(1, "nis2", "RE.8.1")

    assert [(item["providerKey"], item["status"]) for item in found] == [("a.broken", "unavailable"), ("b.fine", "ok")]


def test_registering_the_same_key_twice_keeps_the_last():
    for name in ("Uno", "Dos"):
        EvidenceProviderRegistry.register("demo.same", name=name, controls={"nis2": ("RE.8.1",)},
                                          collect=lambda *_: [AutomaticEvidence("x", "y")])

    assert [item.name for item in EvidenceProviderRegistry.providers_for("nis2", "RE.8.1")] == ["Dos"]


def test_no_eunomia_file_imports_the_modules_that_feed_it():
    forbidden = re.compile(r"^\s*(from|import)\s+src\.modules\.features\.(themis|aegis|hygeia|iris|acheron)\b", re.M)
    offenders = [str(path.relative_to(_PACKAGE)) for path in _PACKAGE.rglob("*.py")
                 if forbidden.search(path.read_text(encoding="utf-8"))]

    assert offenders == []
