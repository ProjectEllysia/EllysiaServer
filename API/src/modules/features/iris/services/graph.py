"""
Grafo de comunicación: quién escribe a quién, y quién imita a un contacto habitual.

Cada análisis deja, al terminar, una arista por cada destinatario (``To`` y
``Cc``) y por la dirección de respuesta (``Reply-To``) de su remitente. Son
solo metadatos —direcciones, nombre visible, recuentos y fechas—, por usuario y
con retención corta.

Con ellos se detecta, sin ningún modelo entrenado, el engaño más común de un
fraude del CEO: un remitente **nuevo** que usa el **nombre** de alguien con
quien el usuario habla a menudo («Juan Pérez» <juan.perez@gmail.com> cuando
Juan siempre escribe desde la empresa), o la misma dirección con otro dominio.

Un contacto es habitual por sus mensajes **legítimos**, no por todos: si
contaran los sospechosos, un atacante que insiste se convertiría en contacto
habitual.

La desviación no cambia el veredicto: el veredicto de Iris sale solo del
mensaje, para que el simulador, un reanálisis o una comparación den lo mismo
hoy y dentro de un mes. La desviación depende de la historia del usuario y se
enseña aparte, en el informe.

``parse_participants``, ``normalize_display_name`` y ``detect_deviation`` son
puras; el resto usa la base de datos.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import getaddresses, parseaddr
from typing import Dict, List, Optional, Tuple

from src.modules.infrastructure import UnitOfWork

from ..model import CommunicationKind, IrisCommunicationEdge
from ..repositories import IrisCommunicationEdgeRepository

#: Un nombre visible normalizado más corto no identifica a nadie («Yo», «JP»).
_MIN_DISPLAY_NAME_LENGTH = 4

#: Una parte local más corta, o genérica, la comparten miles de dominios sin
#: que tenga nada que ver con una persona concreta.
_MIN_LOCAL_PART_LENGTH = 4
_GENERIC_LOCAL_PARTS = frozenset({
    "info", "admin", "contact", "contacto", "noreply", "no-reply", "support", "soporte",
    "hello", "hola", "sales", "ventas", "billing", "facturacion", "team", "office", "mail",
    "notifications", "notification", "newsletter", "news", "marketing", "help", "ayuda",
})

#: Tope de caracteres guardados de un nombre visible.
_MAX_DISPLAY_NAME_LENGTH = 200


@dataclass(frozen=True)
class Participants:
    """Quién interviene en un mensaje.

    Attributes:
        sender_address: Dirección del ``From`` en minúsculas; vacía si no se
            pudo leer.
        sender_display_name: Nombre visible del ``From`` tal cual; vacío si no
            traía.
        counterparts: Pares ``(CommunicationKind, dirección)`` con cada
            destinatario y la dirección de respuesta, sin duplicados.
    """

    sender_address: str
    sender_display_name: str
    counterparts: Tuple[Tuple[CommunicationKind, str], ...] = field(default_factory=tuple)

    @property
    def sender_domain(self) -> str:
        """Dominio del remitente; vacío si no hay dirección."""
        return self.sender_address.rpartition("@")[2]


@dataclass(frozen=True)
class HabitualContact:
    """Un remitente con el que el usuario habla habitualmente.

    Attributes:
        address: Su dirección, en minúsculas.
        display_names: Nombres visibles con los que ha escrito, tal cual.
        legitimate_count: Mensajes legítimos suyos.
    """

    address: str
    display_names: frozenset
    legitimate_count: int


def normalize_display_name(name: Optional[str]) -> str:
    """Reduce un nombre visible a la forma con la que se compara.

    Args:
        name: Nombre visible tal como viene en la cabecera.

    Returns:
        str: En minúsculas, sin tildes, sin comillas ni signos y con los
            espacios colapsados. Cadena vacía si no queda nada.
    """
    decomposed = unicodedata.normalize("NFKD", name or "")
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    cleaned = "".join(char if char.isalnum() else " " for char in without_accents.lower())
    return " ".join(cleaned.split())


def parse_participants(headers: Dict[str, str]) -> Participants:
    """Lee remitente, destinatarios y dirección de respuesta de un mensaje.

    Args:
        headers: Cabeceras del mensaje, con las claves en minúsculas
            (``MessageContext.headers``).

    Returns:
        Participants: Los participantes. Una dirección sin ``@`` se descarta,
            y la dirección de respuesta solo cuenta si es distinta del
            remitente.
    """
    display_name, sender = parseaddr(headers.get("from", "") or "")
    sender = sender.strip().lower() if "@" in sender else ""
    counterparts: list[Tuple[CommunicationKind, str]] = []
    for header_name, kind in (("to", CommunicationKind.TO), ("cc", CommunicationKind.CC),
                              ("reply-to", CommunicationKind.REPLY_TO)):
        for _, address in getaddresses([headers.get(header_name, "") or ""]):
            address = address.strip().lower()
            if "@" not in address or (kind is CommunicationKind.REPLY_TO and address == sender):
                continue
            if (kind, address) not in counterparts:
                counterparts.append((kind, address))
    return Participants(
        sender_address=sender,
        sender_display_name=(display_name or "").strip()[:_MAX_DISPLAY_NAME_LENGTH],
        counterparts=tuple(counterparts),
    )


def detect_deviation(participants: Participants, habitual_contacts: List[HabitualContact]) -> Optional[dict]:
    """Busca si un remitente nuevo imita a un contacto habitual.

    Dos formas, en este orden:

    - ``display_name_reuse``: usa el nombre visible de un contacto habitual
      desde una dirección que no es la suya.
    - ``address_domain_change``: usa la misma parte local que un contacto
      habitual (``juan.perez@``) con otro dominio.

    Un remitente que ya es habitual no se desvía de nada.

    Args:
        participants: Participantes del mensaje (``parse_participants``).
        habitual_contacts: Contactos habituales del usuario, de más a menos
            mensajes legítimos.

    Returns:
        Optional[dict]: ``kind``, ``senderAddress``, ``displayName`` (el del
            mensaje), ``habitualAddress`` y ``habitualMessages``; ``None`` si
            no imita a nadie.
    """
    sender = participants.sender_address
    if not sender or any(contact.address == sender for contact in habitual_contacts):
        return None

    display_name = normalize_display_name(participants.sender_display_name)
    if len(display_name) >= _MIN_DISPLAY_NAME_LENGTH:
        for contact in habitual_contacts:
            if display_name in {normalize_display_name(name) for name in contact.display_names}:
                return _deviation("display_name_reuse", participants, contact)

    local_part = sender.partition("@")[0]
    if len(local_part) >= _MIN_LOCAL_PART_LENGTH and local_part not in _GENERIC_LOCAL_PARTS:
        for contact in habitual_contacts:
            contact_local, _, contact_domain = contact.address.partition("@")
            if contact_local == local_part and contact_domain != participants.sender_domain:
                return _deviation("address_domain_change", participants, contact)
    return None


def load_habitual_contacts(uow: UnitOfWork, user_id: int, min_messages: int) -> List[HabitualContact]:
    """Contactos habituales de un usuario según su grafo.

    Args:
        uow: Transacción en curso.
        user_id: Dueño del grafo.
        min_messages: Mensajes legítimos mínimos para ser habitual.

    Returns:
        List[HabitualContact]: De más a menos mensajes legítimos; vacía si no
            tiene ninguno.
    """
    edge_repo = IrisCommunicationEdgeRepository(uow)
    senders = edge_repo.get_senders(user_id, min_legitimate=max(1, min_messages))
    names_by_sender = edge_repo.get_display_names(user_id, [row[0] for row in senders])
    return [
        HabitualContact(address=address, display_names=frozenset(names_by_sender.get(address, ())),
                        legitimate_count=legitimate)
        for address, _, _, legitimate, _, _ in senders
    ]


def record_communication(uow: UnitOfWork, user_id: int, participants: Participants,
                         is_legitimate: bool, seen_at: datetime) -> int:
    """Suma un mensaje a las aristas de su remitente.

    Args:
        uow: Transacción en curso.
        user_id: Dueño del grafo.
        participants: Participantes del mensaje.
        is_legitimate: Si Iris lo consideró legítimo; solo así cuenta para
            hacer habitual al remitente.
        seen_at: Cuándo se recibió.

    Returns:
        int: Aristas creadas o actualizadas; ``0`` si el mensaje no tenía
            remitente o no tenía a quién.
    """
    if not participants.sender_address:
        return 0
    edge_repo = IrisCommunicationEdgeRepository(uow)
    display_name = participants.sender_display_name or None
    for kind, address in participants.counterparts:
        edge = edge_repo.get_edge(user_id, participants.sender_address, address, kind.value)
        if edge is None:
            edge = edge_repo.save(IrisCommunicationEdge(
                user_id=user_id, sender_address=participants.sender_address,
                sender_domain=participants.sender_domain, recipient_address=address, kind=kind.value,
                message_count=0, legitimate_count=0, first_seen_at=seen_at, last_seen_at=seen_at,
            ))
        edge.message_count += 1
        edge.legitimate_count += 1 if is_legitimate else 0
        edge.last_seen_at = max(edge.last_seen_at, seen_at)
        edge.first_seen_at = min(edge.first_seen_at, seen_at)
        if display_name:
            edge.sender_display_name = display_name
    return len(participants.counterparts)


def _deviation(kind: str, participants: Participants, contact: HabitualContact) -> dict:
    """Serializa una desviación de contacto.

    Args:
        kind: ``display_name_reuse`` o ``address_domain_change``.
        participants: Participantes del mensaje.
        contact: Contacto habitual imitado.

    Returns:
        dict: Lo que guarda ``IrisAnalysis.contact_deviation``.
    """
    return {
        "kind": kind,
        "senderAddress": participants.sender_address,
        "displayName": participants.sender_display_name or None,
        "habitualAddress": contact.address,
        "habitualMessages": contact.legitimate_count,
    }
