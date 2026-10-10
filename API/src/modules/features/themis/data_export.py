"""
Qué datos de un usuario entrega Themis en la exportación de sus datos.

Cada tabla con datos del usuario aparece aquí con la condición que deja solo sus
filas, y con las columnas que **no** salen: credenciales, secretos y rutas de
ficheros del servidor. ``users.services.data_export`` recoge esta lista y escribe
el archivo; un test recorre las claves ajenas hacia ``User`` para que una tabla
nueva no se quede sin decidir (o se declare expresamente como no exportada).
"""

from src.modules.shared import ExportTable, owned_by, owned_through

from .model import (
    AssetGroup,
    AuthorizedTarget,
    Finding,
    OsintScan,
    ProgramedScan,
    Scan,
    ScanFolder,
    ThemisDocument,
    Traceroute,
)

#: Tablas de Themis que entran en la exportación. El orden es el del archivo.
EXPORT_TABLES: tuple[ExportTable, ...] = (
    ExportTable("scans", Scan, owned_by(Scan.user_id)),
    ExportTable("findings", Finding, owned_through(Finding.scan_id, Scan.id, Scan.user_id)),
    ExportTable("domain_scans", OsintScan, owned_by(OsintScan.user_id)),
    ExportTable("scheduled_scans", ProgramedScan, owned_by(ProgramedScan.user_id)),
    ExportTable("folders", ScanFolder, owned_by(ScanFolder.user_id)),
    ExportTable("authorized_targets", AuthorizedTarget, owned_by(AuthorizedTarget.user_id)),
    ExportTable("traceroutes", Traceroute, owned_by(Traceroute.user_id)),
    ExportTable("asset_groups", AssetGroup, owned_by(AssetGroup.user_id)),
    # Los informes: sus metadatos, no el PDF, y sin la ruta interna del fichero.
    ExportTable("documents", ThemisDocument, owned_by(ThemisDocument.user_id), frozenset({"filename"})),
)
