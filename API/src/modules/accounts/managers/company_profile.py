"""
CompanyProfileManager — el perfil de empresa de una cuenta.

Los datos de identidad y de descripción de la empresa se guardan una vez, en
la fila de su **dueño efectivo** (``OrganizationManager.resolve_data_owner``), y
los usan todos los módulos que los necesitan. Un miembro de una organización
lee los del dueño y no puede editarlos.
"""

import logging
from typing import Any

from src.modules.infrastructure import UnitOfWork
from src.modules.infrastructure.session import build_repository

from ..exceptions import DataOwnedByOrganizationError, InvalidTaxIdError
from ..model import CompanyProfile
from ..repositories import CompanyProfileRepository
from ..services.tax_id import is_valid_spanish_tax_id, normalize_tax_id
from .organizations import OrganizationManager

logger = logging.getLogger(__name__)

#: Perfil de quien aún no ha guardado ninguno: mismas claves y vacíos que ``CompanyProfile.to_dict``.
_DEFAULT_PROFILE: dict[str, Any] = {
    "legalName": "", "taxId": "", "addressLine": "", "postalCode": "", "city": "",
    "province": "", "country": "", "sector": "", "companySize": "", "employeeCount": None,
    "jurisdiction": "", "workModel": "", "securityContact": "", "brandLogo": "",
}

#: Clave JSON → columna del modelo.
_COLUMN_OF_KEY = {
    "legalName": "legal_name", "taxId": "tax_id", "addressLine": "address_line",
    "postalCode": "postal_code", "city": "city", "province": "province", "country": "country",
    "sector": "sector", "companySize": "company_size", "employeeCount": "employee_count",
    "jurisdiction": "jurisdiction", "workModel": "work_model",
    "securityContact": "security_contact", "brandLogo": "brand_logo",
}


class CompanyProfileManager:
    """Lectura y edición del perfil de empresa de la cuenta que pregunta."""

    def get_for(self, user_id: int) -> dict:
        """Devuelve el perfil de empresa que ve un usuario y quién lo gestiona.

        Si el usuario es miembro de una organización, ve el perfil de su dueño.

        Args:
            user_id: Usuario que pregunta, sea dueño, miembro o sin organización.

        Returns:
            dict: Los campos de ``CompanyProfileSchema`` (con los valores por
                defecto si el dueño efectivo aún no guardó nada) más
                ``ownership``, el resultado de
                ``OrganizationManager.describe_data_ownership``, que la interfaz
                usa para saber si puede editar y a quién se lo explica.
        """
        manager = OrganizationManager()
        profile = build_repository(CompanyProfileRepository).get_by_user_id(
            manager.resolve_data_owner(user_id)
        )
        payload = dict(_DEFAULT_PROFILE) if profile is None else profile.to_dict()
        payload["ownership"] = manager.describe_data_ownership(user_id)
        return payload

    def update(self, user_id: int, data: dict) -> dict:
        """Crea o actualiza el perfil de empresa de su dueño efectivo.

        Args:
            user_id: Usuario que edita. Tiene que ser el propio dueño efectivo.
            data: Campos de ``CompanyProfileSchema``, ya validados en su forma.
                Un campo ausente se deja como estaba.

        Returns:
            dict: El perfil guardado, con el mismo contenido que ``get_for``.

        Raises:
            DataOwnedByOrganizationError: Si el usuario es miembro de una
                organización de otro (403).
            InvalidTaxIdError: Si el país es España y el NIF/CIF/NIE no supera
                su dígito de control (400).
        """
        manager = OrganizationManager()
        if manager.resolve_data_owner(user_id) != user_id:
            ownership = manager.describe_data_ownership(user_id)
            raise DataOwnedByOrganizationError(ownership["organizationName"] or "")

        fields = {_COLUMN_OF_KEY[key]: value for key, value in data.items() if key in _COLUMN_OF_KEY}
        if "tax_id" in fields:
            fields["tax_id"] = normalize_tax_id(fields["tax_id"]) or None
        if "country" in fields and fields["country"]:
            fields["country"] = fields["country"].upper()

        with UnitOfWork() as uow:
            repo = CompanyProfileRepository(uow)
            profile = repo.get_by_user_id(user_id) or CompanyProfile(user_id=user_id)
            for column, value in fields.items():
                setattr(profile, column, value if value != "" else None)

            if profile.country == "ES" and profile.tax_id and not is_valid_spanish_tax_id(profile.tax_id):
                raise InvalidTaxIdError()

            repo.save(profile)

        return self.get_for(user_id)
