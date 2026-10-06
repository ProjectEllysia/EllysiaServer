"""
IrisContactGraphManager — el grafo de comunicación de un usuario.

El grafo se construye solo al terminar cada análisis (``managers/analysis.py``
→ ``services/graph.py``). Este manager es lo que el usuario puede hacer con
él: consultarlo y olvidarlo entero. Lo purga además la retención
(``services/retention.py``).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import src.modules.system.config_reading as CR
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.shared import isoformat_utc

from ..repositories import IrisCommunicationEdgeRepository


class IrisContactGraphManager:
    """Consulta y olvido del grafo de comunicación de un usuario."""

    @staticmethod
    def get_graph(user_id: int, address: Optional[str] = None, limit: int = 200) -> Dict[str, Any]:
        """Remitentes y aristas del grafo de un usuario.

        Args:
            user_id: Dueño del grafo; nunca se ve el de otro usuario.
            address: Solo lo que toca esta dirección. Por defecto ``None``: todo.
            limit: Máximo de remitentes y de aristas. Por defecto ``200``.

        Returns:
            dict: ``senders`` (dirección, nombre visible, mensajes, legítimos,
                si es habitual y fechas), ``edges`` (remitente, otro extremo,
                ``kind``, recuentos y fechas), ``habitualMinMessages``,
                ``retentionDays`` y ``enabled``.
        """
        config = CR.iris_graph_config()
        edge_repo = build_repository(IrisCommunicationEdgeRepository)
        normalized_address = (address or "").strip().lower() or None
        edges = edge_repo.get_by_user(user_id, normalized_address, limit)
        senders = edge_repo.get_senders(user_id, limit=None if normalized_address else limit)
        if normalized_address:
            touched = {edge.sender_address for edge in edges}
            senders = [row for row in senders if row[0] in touched]
        return {
            "senders": [
                {
                    "address": sender_address,
                    "displayName": display_name,
                    "messageCount": message_count,
                    "legitimateCount": legitimate_count,
                    "isHabitual": legitimate_count >= config.habitual_min_messages,
                    "firstSeenAt": isoformat_utc(first_seen),
                    "lastSeenAt": isoformat_utc(last_seen),
                }
                for sender_address, display_name, message_count, legitimate_count, first_seen, last_seen in senders
            ],
            "edges": [
                {
                    "sender": edge.sender_address,
                    "recipient": edge.recipient_address,
                    "kind": edge.kind,
                    "messageCount": edge.message_count,
                    "legitimateCount": edge.legitimate_count,
                    "firstSeenAt": isoformat_utc(edge.first_seen_at),
                    "lastSeenAt": isoformat_utc(edge.last_seen_at),
                }
                for edge in edges
            ],
            "habitualMinMessages": config.habitual_min_messages,
            "retentionDays": config.retention_days,
            "enabled": config.enabled,
        }

    @staticmethod
    def forget_graph(user_id: int) -> Dict[str, int]:
        """Borra el grafo entero de un usuario.

        Los análisis no cambian; los siguientes empiezan a construir un grafo
        nuevo.

        Args:
            user_id: Dueño del grafo.

        Returns:
            dict: ``deletedEdges``.
        """
        with UnitOfWork() as uow:
            deleted = IrisCommunicationEdgeRepository(uow).delete_by_user(user_id)
        return {"deletedEdges": deleted}
