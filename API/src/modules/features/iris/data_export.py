"""
Qué datos de un usuario entrega Iris en la exportación de sus datos.

Cada tabla con datos del usuario aparece aquí con la condición que deja solo sus
filas, y con las columnas que **no** salen: credenciales, secretos y rutas de
ficheros del servidor. ``users.services.data_export`` recoge esta lista y escribe
el archivo; un test recorre las claves ajenas hacia ``User`` para que una tabla
nueva no se quede sin decidir (o se declare expresamente como no exportada).
"""

from src.modules.shared import ExportTable, owned_by

from .model import (
    IrisActionAudit,
    IrisAnalysis,
    IrisAnalystFeedback,
    IrisBatch,
    IrisCampaign,
    IrisCase,
    IrisCaseEvent,
    IrisCommunicationEdge,
    IrisDocument,
    IrisIntegrationToken,
    IrisMailboxConnection,
    IrisMailboxMember,
    IrisNotificationPreference,
    IrisSavedView,
    IrisTenantConsent,
    IrisTrustedSender,
    IrisUrlExpansion,
    IrisWebhookSubscription,
)

#: Tablas de Iris que entran en la exportación. El orden es el del archivo.
EXPORT_TABLES: tuple[ExportTable, ...] = (
    # El resultado de cada análisis. El contenido completo del correo (IrisRawMessage)
    # no sale: es una copia temporal del buzón y se borra solo a los pocos días.
    ExportTable("analyses", IrisAnalysis, owned_by(IrisAnalysis.user_id)),
    ExportTable("analyst_feedback", IrisAnalystFeedback, owned_by(IrisAnalystFeedback.author_id)),
    ExportTable("batches", IrisBatch, owned_by(IrisBatch.user_id)),
    ExportTable("campaigns", IrisCampaign, owned_by(IrisCampaign.user_id)),
    ExportTable("cases", IrisCase, owned_by(IrisCase.user_id)),
    ExportTable("case_events", IrisCaseEvent, owned_by(IrisCaseEvent.actor_id)),
    ExportTable("communication_edges", IrisCommunicationEdge, owned_by(IrisCommunicationEdge.user_id)),
    ExportTable("trusted_senders", IrisTrustedSender, owned_by(IrisTrustedSender.user_id)),
    ExportTable("saved_views", IrisSavedView, owned_by(IrisSavedView.user_id)),
    ExportTable("url_expansions", IrisUrlExpansion, owned_by(IrisUrlExpansion.user_id)),
    ExportTable("action_audit", IrisActionAudit, owned_by(IrisActionAudit.actor_id)),
    ExportTable(
        "notification_preferences", IrisNotificationPreference,
        owned_by(IrisNotificationPreference.user_id),
    ),
    ExportTable("tenant_consents", IrisTenantConsent, owned_by(IrisTenantConsent.user_id)),
    # Las conexiones salen sin credenciales: ni los tokens del proveedor ni la clave IMAP.
    ExportTable(
        "mailbox_connections", IrisMailboxConnection, owned_by(IrisMailboxConnection.user_id),
        frozenset({"refresh_token", "access_token", "imap_password"}),
    ),
    ExportTable("mailbox_memberships", IrisMailboxMember, owned_by(IrisMailboxMember.user_id)),
    ExportTable(
        "integration_tokens", IrisIntegrationToken, owned_by(IrisIntegrationToken.user_id),
        frozenset({"secret_sha256"}),
    ),
    ExportTable(
        "webhook_subscriptions", IrisWebhookSubscription, owned_by(IrisWebhookSubscription.user_id),
        frozenset({"secret"}),
    ),
    ExportTable("documents", IrisDocument, owned_by(IrisDocument.user_id), frozenset({"filename"})),
)
