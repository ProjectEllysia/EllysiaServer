"""
IrisReportingManager — reportar un correo sospechoso desde el cliente de correo.

Sin esto, reportar un correo a Iris exige copiar sus cabeceras a mano o
guardarlo como ``.eml`` y arrastrarlo al panel. El canal de reporte permite que
un botón en Outlook o Gmail, una extensión del navegador o un script manden el
mensaje tal cual y se cree el análisis sin pedirle nada más al usuario.

Dos piezas:

- **Tokens de integración** (``IrisIntegrationToken``): la credencial que se
  pega en el complemento. Solo sirve para reportar y consultar lo reportado,
  caduca, y se revoca sin tocar la sesión ni la contraseña del usuario.
- **El reporte** (``submit_report``): recibe el mensaje original (``.eml`` o
  ``.msg``) o un mensaje que lo lleva adjunto como ``message/rfc822`` (lo que
  hace «reenviar como adjunto»). En el segundo caso el analizador ya
  desenvuelve el original y conserva quién lo reenvió y con qué asunto
  (``MessageContext.wrapper_*``), así que el informe dice las dos cosas.

El contrato completo para quien escribe el cliente está en ``REPORTING.md``,
junto a este módulo.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Dict, Optional

import src.modules.system.config_reading as CR
from src.modules.infrastructure import UnitOfWork, build_repository
from src.modules.shared import assert_owned, isoformat_utc, utcnow_naive

from ..exceptions import (
    IrisAnalysisNotFoundError,
    IrisIntegrationTokenLimitReachedError,
    IrisIntegrationTokenNotFoundError,
    IrisInvalidInputError,
    IrisInvalidIntegrationTokenError,
)
from ..model import IrisIntegrationToken
from ..repositories import IrisAnalysisRepository, IrisIntegrationTokenRepository
from ..services.batch import build_message_entry, decode_message, message_fingerprint
from ..services.integration_tokens import (
    generate_integration_token,
    is_secret_valid,
    parse_integration_token,
    parse_report_channel,
)
from ..services.parsers import build_subject_title
from .analysis import IrisManager

logger = logging.getLogger(__name__)

#: Nombre con que se trata un mensaje que llegó sin nombre de fichero (en el
#: cuerpo de la petición, como ``message/rfc822``).
_UNNAMED_MESSAGE = "reporte.eml"


def _invalid_input(text: str) -> IrisInvalidInputError:
    """Error de validación cuyo mensaje se enseña tal cual al usuario.

    Args:
        text: Qué falló, en castellano.

    Returns:
        IrisInvalidInputError: Con ``user_message`` igual a ``text``.
    """
    return IrisInvalidInputError(text, user_message=text)


def _token_status(token: IrisIntegrationToken, now) -> str:
    """Estado de un token para enseñarlo.

    Args:
        token: Token.
        now: Hora actual.

    Returns:
        str: ``revoked``, ``expired`` o ``active``.
    """
    if token.revoked_at is not None:
        return "revoked"
    if token.expires_at is not None and token.expires_at <= now:
        return "expired"
    return "active"


def _serialize_token(token: IrisIntegrationToken, secret_token: Optional[str] = None) -> Dict[str, Any]:
    """Serializa un token para la API; el token completo solo al crearlo.

    Args:
        token: Token.
        secret_token: El token completo en claro, solo en la respuesta del
            alta. Por defecto ``None``.

    Returns:
        dict: ``tokenId``, ``name``, ``keyId`` (para reconocerlo sin el
            secreto), ``status``, ``createdAt``, ``expiresAt``, ``lastUsedAt``,
            ``revokedAt`` y, solo al crearlo, ``token``.
    """
    payload = {
        "tokenId": token.id,
        "name": token.name,
        "keyId": token.key_id,
        "status": _token_status(token, utcnow_naive()),
        "createdAt": isoformat_utc(token.created_at),
        "expiresAt": isoformat_utc(token.expires_at),
        "lastUsedAt": isoformat_utc(token.last_used_at),
        "revokedAt": isoformat_utc(token.revoked_at),
    }
    if secret_token is not None:
        payload["token"] = secret_token
    return payload


class IrisReportingManager:
    """Tokens de integración y reportes de correo hechos con ellos."""

    # =========================================================================
    # Tokens
    # =========================================================================

    @staticmethod
    def list_tokens(user_id: int) -> Dict[str, Any]:
        """Tokens del usuario, sin su secreto.

        Args:
            user_id: Dueño.

        Returns:
            dict: ``tokens`` (ver ``_serialize_token``).
        """
        tokens = build_repository(IrisIntegrationTokenRepository).get_by_user(user_id)
        return {"tokens": [_serialize_token(token) for token in tokens]}

    @staticmethod
    def create_token(user_id: int, name: str, lifetime_days: Optional[int] = None) -> Dict[str, Any]:
        """Crea un token de integración y devuelve el token completo, por única vez.

        Args:
            user_id: Dueño; los reportes hechos con el token serán suyos.
            name: Para qué es, hasta 80 caracteres.
            lifetime_days: Días que vale, entre 1 y ``maxTokenLifetimeDays``.
                Por defecto ``None``: ``defaultTokenLifetimeDays``.

        Returns:
            dict: El token (``_serialize_token``) con ``token`` en claro.

        Raises:
            IrisInvalidInputError: Si el nombre está vacío o la duración no vale.
            IrisIntegrationTokenLimitReachedError: Si ya tiene el máximo de
                tokens vigentes.
        """
        config = CR.iris_reporting_config()
        cleaned_name = (name or "").strip()
        if not cleaned_name or len(cleaned_name) > 80:
            raise _invalid_input("El token necesita un nombre de hasta 80 caracteres.")
        days = config.default_token_lifetime_days if lifetime_days is None else lifetime_days
        if not 1 <= days <= config.max_token_lifetime_days:
            raise _invalid_input(f"Un token puede valer entre 1 y {config.max_token_lifetime_days} días.")
        now = utcnow_naive()
        if build_repository(IrisIntegrationTokenRepository).count_valid_by_user(user_id, now) >= config.max_tokens_per_user:
            raise IrisIntegrationTokenLimitReachedError(config.max_tokens_per_user)

        issued = generate_integration_token()
        with UnitOfWork() as uow:
            token = IrisIntegrationTokenRepository(uow).save(IrisIntegrationToken(
                user_id=user_id, name=cleaned_name, key_id=issued.key_id, secret_sha256=issued.secret_sha256,
                created_at=now, expires_at=now + timedelta(days=days),
            ))
            return _serialize_token(token, secret_token=issued.token)

    @staticmethod
    def revoke_token(token_id: int, user_id: int) -> Dict[str, Any]:
        """Revoca un token: deja de valer en el acto. Revocar uno ya revocado no hace nada.

        Args:
            token_id: Token.
            user_id: Dueño.

        Returns:
            dict: El token revocado.

        Raises:
            IrisIntegrationTokenNotFoundError: Si no existe o no es suyo.
        """
        with UnitOfWork() as uow:
            token = assert_owned(IrisIntegrationTokenRepository, token_id, user_id,
                                 IrisIntegrationTokenNotFoundError, uow=uow)
            if token.revoked_at is None:
                token.revoked_at = utcnow_naive()
            return _serialize_token(token)

    @staticmethod
    def authenticate(raw_token: Optional[str]) -> IrisIntegrationToken:
        """Comprueba un token de integración recibido y anota su uso.

        Args:
            raw_token: Lo que llegó en ``Authorization: Bearer …``.

        Returns:
            IrisIntegrationToken: El token vigente (con ``user_id``).

        Raises:
            IrisInvalidIntegrationTokenError: Si falta, está mal formado, no
                existe, el secreto no coincide, está revocado o caducó. El
                motivo solo va al log; la respuesta es la misma en todos los
                casos.
        """
        parts = parse_integration_token(raw_token)
        if parts is None:
            raise IrisInvalidIntegrationTokenError("formato")
        key_id, secret = parts
        token = build_repository(IrisIntegrationTokenRepository).get_by_key_id(key_id)
        if token is None or not is_secret_valid(secret, token.secret_sha256):
            raise IrisInvalidIntegrationTokenError("desconocido")
        now = utcnow_naive()
        if _token_status(token, now) != "active":
            raise IrisInvalidIntegrationTokenError(_token_status(token, now))
        with UnitOfWork() as uow:
            IrisIntegrationTokenRepository(uow).touch(token.id, now)
        return token

    # =========================================================================
    # Reportes
    # =========================================================================

    @staticmethod
    def submit_report(user_id: int, token_id: int, filename: Optional[str], data: bytes,
                      channel: Optional[str] = None) -> Dict[str, Any]:
        """Crea el análisis de un correo reportado desde un cliente de correo.

        Un correo que el usuario ya había analizado (mismo contenido) no se
        vuelve a analizar ni a cobrar: se devuelve el análisis que ya existe.

        Args:
            user_id: Dueño del token, que es también el dueño del análisis.
            token_id: Token con que se reporta; queda anotado en el análisis.
            filename: Nombre del fichero subido (``.eml`` o ``.msg``), o
                ``None`` si el mensaje llegó en el cuerpo de la petición (se
                trata como ``.eml``).
            data: Bytes del mensaje; se admite hasta ``maxMessageBytes`` (el
                llamante lee como mucho un byte más para detectar el exceso).
            channel: Canal declarado por el cliente (``X-Ellysia-Report-Channel``).
                Por defecto ``None``: ``api``.

        Returns:
            dict: ``analysisId``, ``status`` (``pending`` si se acaba de crear,
                o el estado del análisis que ya existía), ``isDuplicate`` y
                ``reportChannel``.

        Raises:
            IrisInvalidInputError: Si no llega mensaje, no es un ``.eml`` ni un
                ``.msg``, pasa del tamaño, el ``.msg`` está dañado o no tiene
                cabeceras suficientes para analizarlo.
            QuotaExceededError: Si el usuario agotó los análisis de su plan.
        """
        if not data:
            raise _invalid_input("No ha llegado ningún mensaje que reportar.")
        name = (filename or _UNNAMED_MESSAGE).strip() or _UNNAMED_MESSAGE
        if not name.lower().endswith((".eml", ".msg")):
            raise _invalid_input("El mensaje reportado tiene que ser un fichero .eml o .msg.")
        entry = build_message_entry(name, data, CR.iris_config().max_message_bytes)
        if entry.rejection:
            raise _invalid_input(entry.rejection)
        raw = decode_message(entry.content)
        report_channel = parse_report_channel(channel)

        existing = build_repository(IrisAnalysisRepository).get_by_user_and_fingerprint(
            user_id, message_fingerprint(raw))
        if existing is not None:
            return {"analysisId": existing.id, "status": existing.status, "isDuplicate": True,
                    "reportChannel": existing.report_channel}

        analysis_id = IrisManager().analyze(
            raw_headers=None, raw_message=raw, user_id=user_id, title=build_subject_title(raw),
            report_channel=report_channel, integration_token_id=token_id,
        )
        logger.info(f"Correo reportado por el usuario {user_id} desde {report_channel}: análisis {analysis_id}")
        return {"analysisId": analysis_id, "status": "pending", "isDuplicate": False,
                "reportChannel": report_channel}

    @staticmethod
    def get_report_status(analysis_id: int, user_id: int) -> Dict[str, Any]:
        """Cómo va el análisis de un correo reportado, para que el cliente se lo diga al usuario.

        Solo lo imprescindible para un aviso breve («Iris lo considera
        phishing»): el informe completo se consulta en el panel, con sesión.

        Args:
            analysis_id: Análisis.
            user_id: Dueño del token con que se consulta.

        Returns:
            dict: ``analysisId``, ``status``, ``verdict``, ``totalScore`` y
                ``finishedAt``; los tres últimos ``None`` mientras no termina.

        Raises:
            IrisAnalysisNotFoundError: Si no existe o no es del usuario.
        """
        analysis = assert_owned(IrisAnalysisRepository, analysis_id, user_id, IrisAnalysisNotFoundError)
        return {
            "analysisId": analysis.id,
            "status": analysis.status,
            "verdict": analysis.verdict,
            "totalScore": analysis.total_score,
            "finishedAt": isoformat_utc(analysis.finished_at),
        }
