"""El idioma preferido: lo que elige cada usuario y lo que fija su organización.

El perfil devuelve dos datos: ``language`` (lo que eligió el usuario, o
``null``) y ``effectiveLanguage`` (el que le corresponde tras aplicar la regla:
el suyo, si no el de su organización, si no el de la plataforma). Aquí se
prueba esa regla de punta a punta, a través de la API, y que solo el dueño de
una organización puede fijar su idioma.
"""

from datetime import timedelta

import pytest

from src.modules.shared import utcnow_naive

pytestmark = pytest.mark.integration

FUTURE = utcnow_naive() + timedelta(days=30)


@pytest.fixture()
def owner(make_user, make_subscription):
    """Un usuario cuyo plan incluye tener organización."""
    user = make_user()
    make_subscription(user, plan_code="gold", organization_enabled=True, current_period_end=FUTURE)
    return user


def _create_organization(client, headers):
    """Crea una organización a nombre de quien firma ``headers`` y la devuelve."""
    response = client.post("/organizations", headers=headers, json={"name": "Acme"})
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def _join(app, organization_id, user_id):
    """Mete a alguien en la organización sin pasar por la invitación."""
    from src.modules.accounts.model import OrganizationMember
    from src.modules.infrastructure import unit_of_work

    with app.app_context():
        with unit_of_work.UnitOfWork() as uow:
            uow.session.add(OrganizationMember(
                organization_id=organization_id, user_id=user_id, member_role="member",
            ))
            uow.session.flush()


def _profile(client, headers):
    """Lee el perfil de quien firma ``headers``."""
    response = client.get("/users/me", headers=headers)
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def test_without_choices_the_profile_follows_the_platform(client, regular_user, auth_headers):
    """Una cuenta que no ha elegido nada no tiene idioma propio y sigue el de la plataforma."""
    profile = _profile(client, auth_headers(regular_user))
    assert profile["language"] is None
    assert profile["effectiveLanguage"] == "es"


def test_choosing_a_language_is_saved_and_applied(client, regular_user, auth_headers):
    """Elegir un idioma lo guarda en el perfil y pasa a ser el efectivo."""
    headers = auth_headers(regular_user)
    response = client.put("/users/me/language", headers=headers, json={"language": "en"})

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["language"] == "en"
    assert _profile(client, headers)["effectiveLanguage"] == "en"


def test_null_goes_back_to_following_the_upper_level(client, regular_user, auth_headers):
    """Elegir ``null`` borra la elección: se vuelve a seguir a la organización o la plataforma."""
    headers = auth_headers(regular_user)
    client.put("/users/me/language", headers=headers, json={"language": "en"})
    response = client.put("/users/me/language", headers=headers, json={"language": None})

    assert response.status_code == 200
    assert response.get_json()["language"] is None
    assert response.get_json()["effectiveLanguage"] == "es"


def test_an_unsupported_language_is_rejected(client, regular_user, auth_headers):
    """Un idioma que la interfaz no tiene no se guarda."""
    response = client.put("/users/me/language", headers=auth_headers(regular_user), json={"language": "xx"})
    assert response.status_code == 422
    assert _profile(client, auth_headers(regular_user))["language"] is None


def test_members_without_a_choice_follow_the_organization(client, app, owner, regular_user, auth_headers):
    """Quien no ha elegido sigue el idioma que fijó el dueño; quien eligió, el suyo."""
    organization = _create_organization(client, auth_headers(owner))
    _join(app, organization["id"], regular_user.id)

    response = client.put(
        f"/organizations/{organization['id']}/language",
        headers=auth_headers(owner), json={"defaultLanguage": "en"},
    )
    assert response.status_code == 200, response.get_json()
    assert response.get_json()["defaultLanguage"] == "en"

    assert _profile(client, auth_headers(regular_user))["effectiveLanguage"] == "en"

    client.put("/users/me/language", headers=auth_headers(regular_user), json={"language": "es"})
    assert _profile(client, auth_headers(regular_user))["effectiveLanguage"] == "es"


def test_clearing_the_organization_language_goes_back_to_the_platform(
    client, app, owner, regular_user, auth_headers,
):
    """Sin idioma de organización, los miembros sin elección vuelven al de la plataforma."""
    organization = _create_organization(client, auth_headers(owner))
    _join(app, organization["id"], regular_user.id)
    url = f"/organizations/{organization['id']}/language"
    client.put(url, headers=auth_headers(owner), json={"defaultLanguage": "en"})
    client.put(url, headers=auth_headers(owner), json={"defaultLanguage": None})

    assert _profile(client, auth_headers(regular_user))["effectiveLanguage"] == "es"


def test_only_the_owner_sets_the_organization_language(client, app, owner, regular_user, auth_headers):
    """Un miembro no puede fijar el idioma de la organización; recibe el mismo error que si no existiera."""
    organization = _create_organization(client, auth_headers(owner))
    _join(app, organization["id"], regular_user.id)

    response = client.put(
        f"/organizations/{organization['id']}/language",
        headers=auth_headers(regular_user), json={"defaultLanguage": "en"},
    )
    assert response.status_code == 404
    assert client.get("/organizations/mine", headers=auth_headers(owner)).get_json()["organization"]["defaultLanguage"] is None
