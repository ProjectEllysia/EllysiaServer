"""
Qué datos de un usuario entrega Hygeia en la exportación de sus datos.

Cada tabla con datos del usuario aparece aquí con la condición que deja solo sus
filas, y con las columnas que **no** salen: credenciales, secretos y rutas de
ficheros del servidor. ``users.services.data_export`` recoge esta lista y escribe
el archivo; un test recorre las claves ajenas hacia ``User`` para que una tabla
nueva no se quede sin decidir (o se declare expresamente como no exportada).
"""

from src.modules.shared import ExportTable, owned_by, owned_through

from .model import Anomaly, HygeiaDocument, HygeiaTag, MonitoredAsset

#: Tablas de Hygeia que entran en la exportación. El orden es el del archivo.
EXPORT_TABLES: tuple[ExportTable, ...] = (
    # La clave con la que el agente se identifica no sale: solo su huella, que tampoco es útil fuera.
    ExportTable(
        "monitored_assets", MonitoredAsset, owned_by(MonitoredAsset.user_id),
        frozenset({"agent_key_hash"}),
    ),
    ExportTable("anomalies", Anomaly, owned_through(Anomaly.asset_id, MonitoredAsset.id, MonitoredAsset.user_id)),
    ExportTable("tags", HygeiaTag, owned_by(HygeiaTag.user_id)),
    ExportTable("documents", HygeiaDocument, owned_by(HygeiaDocument.user_id), frozenset({"filename"})),
)
