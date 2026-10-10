"""
Qué datos de un usuario entrega el módulo de cuentas (plan y organización) en la exportación de sus datos.

Cada tabla con datos del usuario aparece aquí con la condición que deja solo sus
filas, y con las columnas que **no** salen: credenciales, secretos y rutas de
ficheros del servidor. ``users.services.data_export`` recoge esta lista y escribe
el archivo; un test recorre las claves ajenas hacia ``User`` para que una tabla
nueva no se quede sin decidir (o se declare expresamente como no exportada).
"""

from src.modules.shared import ExportTable, owned_by

from .model import CompanyProfile, Organization, OrganizationMember, Subscription

#: Tablas de el módulo de cuentas (plan y organización) que entran en la exportación. El orden es el del archivo.
EXPORT_TABLES: tuple[ExportTable, ...] = (
    ExportTable("subscription", Subscription, owned_by(Subscription.user_id)),
    ExportTable("company_profile", CompanyProfile, owned_by(CompanyProfile.user_id)),
    ExportTable("owned_organization", Organization, owned_by(Organization.owner_user_id)),
    ExportTable("organization_membership", OrganizationMember, owned_by(OrganizationMember.user_id)),
)
