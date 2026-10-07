"""
Qué datos de un usuario entrega Aegis en la exportación de sus datos.

Cada tabla con datos del usuario aparece aquí con la condición que deja solo sus
filas, y con las columnas que **no** salen: credenciales, secretos y rutas de
ficheros del servidor. ``users.services.data_export`` recoge esta lista y escribe
el archivo; un test recorre las claves ajenas hacia ``User`` para que una tabla
nueva no se quede sin decidir (o se declare expresamente como no exportada).
"""

from src.modules.shared import ExportTable, owned_by, owned_through

from .model import (
    AegisDocument,
    AegisOrgProfile,
    AegisQuizQuestion,
    AegisTip,
    Campaign,
    CampaignRecipient,
    DistributionList,
    Recipient,
)

#: Tablas de Aegis que entran en la exportación. El orden es el del archivo.
EXPORT_TABLES: tuple[ExportTable, ...] = (
    ExportTable("org_profile", AegisOrgProfile, owned_by(AegisOrgProfile.user_id)),
    ExportTable("distribution_lists", DistributionList, owned_by(DistributionList.user_id)),
    ExportTable(
        "recipients", Recipient,
        owned_through(Recipient.list_id, DistributionList.id, DistributionList.user_id),
    ),
    ExportTable("documents", AegisDocument, owned_by(AegisDocument.user_id), frozenset({"filename"})),
    ExportTable("tips", AegisTip, owned_through(AegisTip.document_id, AegisDocument.id, AegisDocument.user_id)),
    ExportTable(
        "quiz_questions", AegisQuizQuestion,
        owned_through(AegisQuizQuestion.document_id, AegisDocument.id, AegisDocument.user_id),
    ),
    ExportTable("campaigns", Campaign, owned_by(Campaign.user_id)),
    # El token es la identidad de quien responde el test: no sale.
    ExportTable(
        "campaign_recipients", CampaignRecipient,
        owned_through(CampaignRecipient.campaign_id, Campaign.id, Campaign.user_id),
        frozenset({"token"}),
    ),
)
