"""
Qué datos de un usuario entrega Acheron en la exportación de sus datos.

Cada tabla con datos del usuario aparece aquí con la condición que deja solo sus
filas, y con las columnas que **no** salen: credenciales, secretos y rutas de
ficheros del servidor. ``users.services.data_export`` recoge esta lista y escribe
el archivo; un test recorre las claves ajenas hacia ``User`` para que una tabla
nueva no se quede sin decidir (o se declare expresamente como no exportada).
"""

from src.modules.shared import ExportTable, owned_by, owned_through

from .model import Storable, Vault

#: Tablas de Acheron que entran en la exportación. El orden es el del archivo.
EXPORT_TABLES: tuple[ExportTable, ...] = (
    # La bóveda sale tal cual está guardada, cifrada: el servidor no puede leerla y
    # el archivo tampoco la abre sin la contraseña maestra del usuario.
    ExportTable("vaults", Vault, owned_by(Vault.user_id)),
    ExportTable("items", Storable, owned_through(Storable.vault_id, Vault.id, Vault.user_id)),
)
