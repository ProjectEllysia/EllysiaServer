"""Acceso a datos de los grupos de activos y de los escaneos más recientes por host."""

from datetime import timedelta

import pytest

from src.modules.infrastructure import UnitOfWork
from src.modules.shared import utcnow_naive
from src.modules.features.themis.model import AssetGroup, Host, LybraScan, ScanStatus
from src.modules.features.themis.repositories import AssetGroupRepository, ScanRepository

pytestmark = pytest.mark.integration


def _host(uow, name: str, address: str) -> int:
    host = Host(hostname=name, ip_address=address, mac_address="00:00:00:00:00:00")
    uow.session.add(host)
    uow.session.flush()
    return host.id


def _scan(uow, user_id: int, host_id, status: ScanStatus, age_minutes: int, asset_id=None) -> int:
    scan = LybraScan(target="t", user_id=user_id, host_id=host_id, status=status.value,
                     started_at=utcnow_naive() - timedelta(minutes=age_minutes), asset_id=asset_id)
    uow.session.add(scan)
    uow.session.flush()
    return scan.id


def test_the_latest_finished_scan_of_each_host_is_returned(app, admin_user):
    with app.app_context():
        with UnitOfWork() as uow:
            first, second = _host(uow, "h1", "10.0.0.1"), _host(uow, "h2", "10.0.0.2")
            _scan(uow, admin_user.id, first, ScanStatus.FINISHED, age_minutes=60)
            newest = _scan(uow, admin_user.id, first, ScanStatus.FINISHED, age_minutes=10)
            _scan(uow, admin_user.id, first, ScanStatus.FAILED, age_minutes=1)    # más nuevo, pero fallido
            only = _scan(uow, admin_user.id, second, ScanStatus.FINISHED, age_minutes=30)
            _scan(uow, admin_user.id, None, ScanStatus.FINISHED, age_minutes=5)   # el padre de un lote: sin host
            _scan(uow, admin_user.id, second, ScanStatus.FINISHED, age_minutes=2, asset_id=7)  # inventario

            scans = ScanRepository(uow).get_latest_finished_scans_by_host(admin_user.id)

            assert sorted(scan.id for scan in scans) == sorted([newest, only])


def test_the_latest_scans_of_another_user_are_not_returned(app, admin_user, regular_user):
    with app.app_context():
        with UnitOfWork() as uow:
            host = _host(uow, "h1", "10.0.0.1")
            _scan(uow, regular_user.id, host, ScanStatus.FINISHED, age_minutes=5)

            assert ScanRepository(uow).get_latest_finished_scans_by_host(admin_user.id) == []


def test_groups_are_scoped_to_their_owner_and_ordered_by_name(app, admin_user, regular_user):
    with app.app_context():
        with UnitOfWork() as uow:
            repo = AssetGroupRepository(uow)
            repo.save(AssetGroup(user_id=admin_user.id, name="oficina", cidr="10.0.1.0/24"))
            mine = repo.save(AssetGroup(user_id=admin_user.id, name="dmz", cidr="10.0.0.0/24"))
            foreign = repo.save(AssetGroup(user_id=regular_user.id, name="otro", cidr="10.9.0.0/24"))

            assert [group.name for group in repo.get_by_user(admin_user.id)] == ["dmz", "oficina"]
            assert repo.get_by_id_and_user(mine.id, admin_user.id) is not None
            assert repo.get_by_id_and_user(foreign.id, admin_user.id) is None
            assert repo.get_by_name_and_user("dmz", admin_user.id).id == mine.id
            assert repo.get_by_name_and_user("dmz", regular_user.id) is None
