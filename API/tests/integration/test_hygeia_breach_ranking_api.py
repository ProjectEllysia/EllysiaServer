"""
Tests de integración HTTP del ranking de incumplimientos de umbral
(``GET /hygeia/stats/breach-ranking``).

Lo que el endpoint ordena son **aperturas de anomalía** dentro del periodo,
porque cada apertura es un cruce de umbral sostenido que el detector ya dejó
escrito. El campo ``breach_counters`` del activo mide otra cosa —los latidos
consecutivos que lleva en rojo ahora mismo— y viaja aparte como
``currentBreachStreak``; varios de estos tests existen precisamente para fijar
que los dos números no se confunden.

Las anomalías se siembran por repositorio, con ``opened_at`` elegido: por HTTP
no hay forma de colocar un incumplimiento en un instante concreto del pasado.
"""

import secrets
from datetime import timedelta

import pytest

from src.modules.features.hygeia.model import Anomaly, MonitoredAsset
from src.modules.features.hygeia.repositories import AnomalyRepository, MonitoredAssetRepository
from src.modules.infrastructure import UnitOfWork
from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration


def _create_asset(app, user_id: int, hostname: str, breach_counters: dict = None) -> int:
    """Da de alta un activo del usuario, con sus contadores de racha, y devuelve su id."""
    with app.app_context():
        with UnitOfWork() as uow:
            asset = MonitoredAsset(
                hostname=hostname, agent_key_id=secrets.token_hex(8), agent_key_hash="dummy",
                heartbeat_interval_sec=15, user_id=user_id, status="online",
                last_seen_at=utcnow_naive(), breach_counters=breach_counters,
            )
            MonitoredAssetRepository(uow).save(asset)
            return asset.id


def _open_breaches(  # pylint: disable=too-many-arguments
    app, asset_id: int, count: int, *, metric: str = "cpu.usagePct",
    kind: str = "cpu_spike", age: timedelta = timedelta(hours=1), state: str = "resolved",
) -> None:
    """Siembra ``count`` anomalías del activo abiertas hace ``age``."""
    with app.app_context():
        with UnitOfWork() as uow:
            repo = AnomalyRepository(uow)
            opened_at = utcnow_naive() - age
            for _ in range(count):
                repo.save(Anomaly(
                    asset_id=asset_id, kind=kind, severity="warning", metric=metric,
                    state=state, opened_at=opened_at,
                ))


def _get(client, headers: dict, **query) -> tuple:
    """Hace el GET del ranking y devuelve ``(status, cuerpo)``."""
    response = client.get(
        "/hygeia/stats/breach-ranking", query_string=query, headers=headers,
    )
    return response.status_code, response.get_json()


def _entry(body: dict, hostname: str) -> dict:
    """La entrada del ranking de un activo, por hostname."""
    return next(entry for entry in body["assets"] if entry["hostname"] == hostname)


@pytest.fixture()
def three_assets_with_breaches(app, regular_user):
    """Tres activos con incumplimientos conocidos y rachas que no los acompañan.

    ``host-ruidoso`` cruzó cinco veces y ya se recuperó (racha ``0``);
    ``host-tranquilo`` cruzó dos veces pero sigue en rojo ahora mismo (racha
    ``3``); ``host-limpio`` no cruzó nunca. Ordenar por la racha en vez de por
    las aperturas invertiría los dos primeros, que es justo el error que este
    fixture existe para detectar.
    """
    noisy = _create_asset(app, regular_user.id, "host-ruidoso", breach_counters={"cpu_spike": 0})
    quiet = _create_asset(
        app, regular_user.id, "host-tranquilo", breach_counters={"cpu_spike": 3},
    )
    _create_asset(app, regular_user.id, "host-limpio")
    _open_breaches(app, noisy, 5)
    _open_breaches(app, quiet, 2, metric="memory.usagePct", kind="mem_high", state="open")


def test_the_ranking_orders_by_breaches_in_the_period(
    client, three_assets_with_breaches, regular_user, auth_headers,
):
    """El activo que más veces cruzó encabeza el ranking, aunque hoy esté sano."""
    status, body = _get(client, auth_headers(regular_user), period="24h")

    assert status == 200
    assert [entry["hostname"] for entry in body["assets"]] == [
        "host-ruidoso", "host-tranquilo", "host-limpio",
    ]
    assert [entry["breachCount"] for entry in body["assets"]] == [5, 2, 0]
    assert body["totalBreaches"] == 7
    assert body["assetCount"] == 3


def test_the_live_streak_travels_apart_from_the_count(
    client, three_assets_with_breaches, regular_user, auth_headers,
):
    """``currentBreachStreak`` es la racha viva, no el recuento del periodo.

    El activo ruidoso acumula cinco incumplimientos con la racha a cero, y el
    tranquilo dos con la racha a tres: si alguno de los dos números se colara
    en el sitio del otro, este test cae.
    """
    _, body = _get(client, auth_headers(regular_user), period="24h")

    assert _entry(body, "host-ruidoso")["currentBreachStreak"] == 0
    assert _entry(body, "host-tranquilo")["currentBreachStreak"] == 3
    assert _entry(body, "host-limpio")["currentBreachStreak"] == 0


def test_an_asset_without_breaches_is_listed_as_zero(
    client, three_assets_with_breaches, regular_user, auth_headers,
):
    """Un activo que no cruzó ningún umbral aparece con ``0``, no se omite.

    A diferencia del ranking por métrica, aquí el cero es un dato conocido —no
    cruzó nada— y no una ausencia de dato, así que el activo tiene que salir.
    """
    _, body = _get(client, auth_headers(regular_user), period="24h")

    assert _entry(body, "host-limpio")["breachCount"] == 0


def test_the_most_conflictive_metric_is_the_one_with_most_breaches(
    client, three_assets_with_breaches, regular_user, auth_headers,
):
    """La métrica más conflictiva es la de mayor recuento acumulado del parque."""
    _, body = _get(client, auth_headers(regular_user), period="24h")

    assert body["mostConflictiveMetric"] == {"metric": "cpu.usagePct", "breachCount": 5}


def test_breaches_older_than_the_period_do_not_count(app, client, regular_user, auth_headers):
    """Un incumplimiento fuera de la ventana no entra en el recuento."""
    asset_id = _create_asset(app, regular_user.id, "host-viejo")
    _open_breaches(app, asset_id, 4, age=timedelta(days=3))

    _, body = _get(client, auth_headers(regular_user), period="24h")

    assert _entry(body, "host-viejo")["breachCount"] == 0
    assert body["totalBreaches"] == 0
    assert body["mostConflictiveMetric"] is None


def test_a_wider_period_reaches_the_older_breaches(app, client, regular_user, auth_headers):
    """La misma anomalía sí cuenta cuando el periodo la abarca."""
    asset_id = _create_asset(app, regular_user.id, "host-viejo")
    _open_breaches(app, asset_id, 4, age=timedelta(days=3))

    _, body = _get(client, auth_headers(regular_user), period="7d")

    assert _entry(body, "host-viejo")["breachCount"] == 4


def test_host_down_counts_for_the_asset_but_never_as_a_metric(
    app, client, regular_user, auth_headers,
):
    """Una caída de host es un incidente del activo, pero no es una métrica.

    ``host_down`` no nace de un umbral sino del silencio del agente, y su
    ``metric`` es nula: cuenta en el recuento del activo, y no compite por ser
    la métrica más conflictiva.
    """
    asset_id = _create_asset(app, regular_user.id, "host-caido")
    _open_breaches(app, asset_id, 3, metric=None, kind="host_down")

    _, body = _get(client, auth_headers(regular_user), period="24h")

    assert _entry(body, "host-caido")["breachCount"] == 3
    assert body["mostConflictiveMetric"] is None


def test_another_users_breaches_are_invisible(
    app, client, three_assets_with_breaches, regular_user, admin_user, auth_headers,
):
    """El ranking solo mira los activos del usuario que pregunta."""
    other_asset = _create_asset(app, admin_user.id, "host-ajeno")
    _open_breaches(app, other_asset, 9)

    _, body = _get(client, auth_headers(regular_user), period="24h")

    assert "host-ajeno" not in [entry["hostname"] for entry in body["assets"]]
    assert body["assetCount"] == 3
    assert body["totalBreaches"] == 7


def test_the_limit_trims_the_ranking_but_not_the_totals(
    client, three_assets_with_breaches, regular_user, auth_headers,
):
    """``limit`` recorta la lista devuelta; los totales siguen siendo los del parque."""
    _, body = _get(client, auth_headers(regular_user), period="24h", limit=1)

    assert [entry["hostname"] for entry in body["assets"]] == ["host-ruidoso"]
    assert body["assetCount"] == 3
    assert body["totalBreaches"] == 7
    assert body["mostConflictiveMetric"]["breachCount"] == 5


def test_a_period_beyond_the_limit_is_clipped(client, regular_user, auth_headers):
    """Pedir más de lo que se puede cubrir recorta la ventana y lo dice."""
    _, body = _get(client, auth_headers(regular_user), period="365d")

    assert body["isPeriodClipped"] is True


def test_the_ranking_requires_authentication(client):
    """Sin token, 401."""
    response = client.get("/hygeia/stats/breach-ranking")

    assert response.status_code == 401
