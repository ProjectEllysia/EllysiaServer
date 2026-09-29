"""
Qué recomienda Iris hacer con un correo y qué hace falta para hacerlo. Sin BD ni red.

Iris separa **recomendar** de **actuar**: el veredicto sugiere una acción, pero
nada se hace sobre el buzón hasta que el usuario lo pide, con un motivo, y —si
la acción saca el correo de su bandeja— confirmándolo. No hay acciones
automáticas: un falso positivo del detector nunca mueve un correo solo.
"""

from __future__ import annotations

from typing import Optional

from ..model import DESTRUCTIVE_MAILBOX_ACTIONS, MailboxAction

#: Longitud mínima del motivo. No es burocracia: la auditoría tiene que poder
#: explicar después por qué se tocó el correo de alguien, y «x» no lo explica.
MIN_REASON_LENGTH = 5

#: Longitud máxima del motivo que se guarda.
MAX_REASON_LENGTH = 1000

#: Acción que se sugiere según el veredicto: la más suave que resuelve el
#: riesgo. Un phishing sale de la bandeja (cuarentena, reversible); un
#: sospechoso se queda donde está, marcado; uno legítimo no necesita nada.
_RECOMMENDED_BY_VERDICT = {
    "Phishing": MailboxAction.QUARANTINE.value,
    "Suspicious": MailboxAction.LABEL.value,
}


def recommend_action(verdict: Optional[str]) -> Optional[str]:
    """Acción que Iris recomienda para un veredicto.

    Args:
        verdict: ``Legitimate``, ``Suspicious``, ``Phishing`` o ``None`` si el
            análisis no ha terminado.

    Returns:
        Optional[str]: ``quarantine`` para phishing, ``label`` para
            sospechoso y ``None`` para legítimo o sin veredicto.
    """
    return _RECOMMENDED_BY_VERDICT.get(verdict or "")


def is_destructive(action: str) -> bool:
    """Si una acción saca el correo de donde el usuario lo ve (y exige confirmación).

    Args:
        action: Valor de ``MailboxAction``.

    Returns:
        bool: ``True`` para cuarentena, spam y papelera.
    """
    return action in DESTRUCTIVE_MAILBOX_ACTIONS


def clean_reason(reason: Optional[str]) -> str:
    """Valida y normaliza el motivo que da el usuario para actuar.

    Args:
        reason: Motivo escrito por el usuario.

    Returns:
        str: El motivo sin espacios alrededor, recortado a ``MAX_REASON_LENGTH``.

    Raises:
        ValueError: En castellano, si tiene menos de ``MIN_REASON_LENGTH``
            caracteres.
    """
    cleaned = (reason or "").strip()
    if len(cleaned) < MIN_REASON_LENGTH:
        raise ValueError(f"Explica en al menos {MIN_REASON_LENGTH} caracteres por qué actúas sobre este correo.")
    return cleaned[:MAX_REASON_LENGTH]
