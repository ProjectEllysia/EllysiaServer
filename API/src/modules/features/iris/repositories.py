"""
Repository classes for Iris data access.

Extends BaseRepository for type-safe CRUD on IrisAnalysis and
IrisRuleResult models.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, List, Optional, Tuple

from sqlalchemy import String, and_, asc, cast, delete, desc, func, nullslast, or_, select, update
from sqlalchemy.orm import joinedload, selectinload

from src.modules.infrastructure import BaseRepository, DocumentRepository
from src.modules.shared import utcnow_naive

from .model import (
    IrisAnalystFeedback,
    IrisAnalysis, IrisMailboxConnection, IrisMailboxInbox, IrisNotificationPreference,
    IrisRawMessage, IrisRuleResult, IrisDocument, IrisTrustedSender,
    IrisAnalysisTag, IrisIndicator, IrisSavedView,
    IrisCase, IrisCaseAnalysis, IrisCaseEvent, IrisBatch, IrisBatchItem,
    IrisCampaign, IrisCampaignMember, IrisCommunicationEdge, IrisDomainCache, IrisUrlExpansion,
    IrisThreatIntelResult, IrisTenantProfile, IrisTenantConsent,
    IrisWebhookDelivery, IrisWebhookSubscription, WebhookDeliveryStatus,
)


class IrisAnalysisRepository(BaseRepository[IrisAnalysis]):
    """
    Data-access layer for IrisAnalysis records.

    Inherits generic CRUD (get_by_id, save, delete) from BaseRepository
    and adds analysis-specific query methods.
    """

    _MODEL = IrisAnalysis

    def get_by_user(self, user_id: int) -> List[IrisAnalysis]:
        """Return all analyses belonging to a user, newest first."""
        return (
            self._session.query(IrisAnalysis)
            .filter(IrisAnalysis.user_id == user_id)
            .order_by(IrisAnalysis.created_at.desc())
            .all()
        )

    def get_active_analyses(self) -> List[IrisAnalysis]:
        """Analyses still pending/running — used to detect orphans after a restart."""
        return (
            self._session.query(IrisAnalysis)
            .filter(IrisAnalysis.status.in_(["pending", "running"]))
            .order_by(IrisAnalysis.started_at.asc())
            .all()
        )

    #: Columnas ordenables expuestas por ``sort_by`` — nunca se acepta el
    #: nombre de columna directamente desde la query string.
    _SORTABLE_COLUMNS = {
        "date": IrisAnalysis.created_at,
        "score": IrisAnalysis.total_score,
        "verdict": IrisAnalysis.verdict,
        "title": IrisAnalysis.title,
        "status": IrisAnalysis.status,
    }

    def get_by_user_paginated(
        self, user_id: int, page: int, per_page: int, *,
        search: str | None = None, verdict: str | None = None,
        status: str | None = None, source: str | None = None,
        tag: str | None = None, ioc: str | None = None, review: str | None = None,
        sort_by: str = "date", sort_dir: str = "desc",
    ) -> Tuple[List[IrisAnalysis], int]:
        """
        Return a page of analyses for a user plus the total count.

        Args:
            user_id: Owner of the analyses.
            page: 1‑based page number.
            per_page: Maximum items per page.
            search: Optional case-insensitive substring match on ``title``.
            verdict: Optional exact match on ``verdict``.
            status: Optional exact match on ``status``.
            source: "manual" (``connection_id IS NULL``) or "mailbox"
                (``connection_id IS NOT NULL``); ``None`` = no filter.
            tag: Solo los análisis con esta etiqueta exacta; ``None`` = sin filtro.
            ioc: Solo los análisis cuyo índice de IOCs contiene este texto
                (ya normalizado por el llamante); ``None`` = sin filtro.
            review: ``pending`` (terminados y sin ninguna corrección del
                analista) o ``reviewed`` (con al menos una); ``None`` = sin filtro.
            sort_by: One of ``_SORTABLE_COLUMNS`` — validated upstream by
                ``ResultsQuerySchema``.
            sort_dir: "asc" or "desc".

        Returns:
            Tuple of (items, total_count).
        """
        query = (
            self._session.query(IrisAnalysis)
            .options(joinedload(IrisAnalysis.connection), selectinload(IrisAnalysis.tags))
            .filter(IrisAnalysis.user_id == user_id)
        )
        if tag:
            query = query.filter(IrisAnalysis.id.in_(
                select(IrisAnalysisTag.analysis_id).where(IrisAnalysisTag.name == tag)
            ))
        if ioc:
            query = query.filter(IrisAnalysis.id.in_(
                select(IrisIndicator.analysis_id).where(IrisIndicator.value.contains(ioc, autoescape=True))
            ))
        reviewed_ids = select(IrisAnalystFeedback.analysis_id)
        if review == "pending":
            query = query.filter(IrisAnalysis.status == "finished", IrisAnalysis.id.notin_(reviewed_ids))
        elif review == "reviewed":
            query = query.filter(IrisAnalysis.id.in_(reviewed_ids))
        if search:
            query = query.filter(IrisAnalysis.title.ilike(f"%{search}%"))
        if verdict:
            query = query.filter(IrisAnalysis.verdict == verdict)
        if status:
            query = query.filter(IrisAnalysis.status == status)
        if source == "manual":
            query = query.filter(IrisAnalysis.connection_id.is_(None))
        elif source == "mailbox":
            query = query.filter(IrisAnalysis.connection_id.isnot(None))

        total = query.count()

        column = self._SORTABLE_COLUMNS.get(sort_by, IrisAnalysis.created_at)
        direction = asc if sort_dir == "asc" else desc
        # nullslast en todos los campos ordenables salvo la fecha (nunca nula):
        # un análisis pendiente sin score/verdict aún no debe contaminar la
        # rampa de riesgo del extremo "peor" ni "mejor" del orden por score.
        order_clause = nullslast(direction(column)) if column is not IrisAnalysis.created_at else direction(column)
        items = (
            query.order_by(order_clause, IrisAnalysis.created_at.desc())
            .limit(per_page)
            .offset((page - 1) * per_page)
            .all()
        )
        return items, total

    def get_by_source(self, connection_id: int, source_message_uid: str) -> Optional[IrisAnalysis]:
        """El análisis ya aceptado para este (connection_id, source_message_uid),
        si existe.

        Usado tanto por la cola de checkpoint del sync de buzón (que
        solo necesita saber si existe) como por ``IrisManager.analyze()``
        (que necesita el id para devolverlo sin cobrar cuota de nuevo)
        -- reconocer un mensaje ya aceptado en un intento anterior, p.ej.
        tras un fallo entre el commit de ``IrisAnalysis`` y el borrado de su
        entrada en ``IrisMailboxInbox``, de forma que un reintento nunca
        confunda la ``UniqueConstraint`` de idempotencia con un fallo real.

        Args:
            connection_id: ``IrisMailboxConnection.id`` del buzón que
                aceptó el mensaje.
            source_message_uid: ``IrisMailboxInbox.provider_message_id``
                del mensaje.
        
        Returns:
            Optional[IrisAnalysis]: El análisis, o ``None`` si ese mensaje
                no se ha aceptado nunca.
        """
        return (
            self._session.query(IrisAnalysis)
            .filter(
                IrisAnalysis.connection_id == connection_id,
                IrisAnalysis.source_message_uid == source_message_uid,
            )
            .first()
        )

    def get_by_user_and_fingerprint(self, user_id: int, fingerprint: str) -> Optional[IrisAnalysis]:
        """El análisis más reciente de un usuario con esta huella de contenido.

        Args:
            user_id: Dueño de los análisis.
            fingerprint: ``IrisAnalysis.content_sha256`` buscada.

        Returns:
            Optional[IrisAnalysis]: El análisis, o ``None`` si ese mensaje no se
                ha analizado nunca (o solo antes de que existiera la huella).
        """
        return (
            self._session.query(IrisAnalysis)
            .filter(IrisAnalysis.user_id == user_id, IrisAnalysis.content_sha256 == fingerprint)
            .order_by(IrisAnalysis.id.desc())
            .first()
        )

    def has_earlier_with_fingerprint(self, user_id: int, fingerprint: str, analysis_id: int) -> bool:
        """Indica si el usuario ya había analizado antes el mismo correo.

        Args:
            user_id: Dueño de los análisis.
            fingerprint: ``IrisAnalysis.content_sha256`` del análisis actual.
            analysis_id: El análisis actual; solo cuentan los anteriores a él.

        Returns:
            bool: ``True`` si hay otro análisis del usuario, con id menor, con
                la misma huella.
        """
        return self._session.query(
            self._session.query(IrisAnalysis.id)
            .filter(IrisAnalysis.user_id == user_id, IrisAnalysis.content_sha256 == fingerprint,
                    IrisAnalysis.id < analysis_id)
            .exists()
        ).scalar()

    def count_active_by_user(self, user_id: int) -> int:
        """Cuántos análisis de un usuario están pendientes o en curso.

        Args:
            user_id: Dueño de los análisis.

        Returns:
            int: Análisis en ``pending`` o ``running``.
        """
        return (
            self._session.query(IrisAnalysis.id)
            .filter(IrisAnalysis.user_id == user_id, IrisAnalysis.status.in_(["pending", "running"]))
            .count()
        )

    def exists_by_source(self, connection_id: int, source_message_uid: str) -> bool:
        """
        Si ya existe un análisis para este (connection_id, source_message_uid).
        
        Args:
            connection_id: ``IrisMailboxConnection.id`` del buzón que
                aceptó el mensaje.
            source_message_uid: ``IrisMailboxInbox.provider_message_id``
                del mensaje.

        Returns:
            bool: ``True``, si ya hay un análisis aceptado para ese mensaje;
                ``False``, en caso contrario.
        """
        return self.get_by_source(connection_id, source_message_uid) is not None

    def count_by_connection(self, connection_id: int) -> int:
        """Cuántos análisis ha aceptado en total esta conexión.

        Es la cuenta real de "mensajes aceptados" -- no hace falta un
        contador aparte, porque cada mensaje aceptado por el checkpoint de
        buzón deja exactamente una fila ``IrisAnalysis`` con este
        ``connection_id`` y nunca se borra al resolverse (a diferencia de su
        entrada en ``IrisMailboxInbox``, que sí desaparece).
        """
        return (
            self._session.query(IrisAnalysis.id)
            .filter(IrisAnalysis.connection_id == connection_id)
            .count()
        )

    def get_non_critical_phishing_since(
        self, user_id: int, since: datetime, critical_threshold: float,
    ) -> List[IrisAnalysis]:
        """Veredictos Phishing de buzón que el digest diario todavía no ha
        resumido.

        Solo entran los que ``_enqueue_phishing_notification`` ya habría
        notificado si no fuera por el digest -- ``connection_id`` no nulo
        (un análisis manual ya lo está viendo el usuario en el panel) y
        ``total_score`` por encima de ``critical_threshold`` (los de alta
        confianza se envían siempre al momento, nunca esperan al digest;
        ver ``IrisPhishingNotifyManager._run_notify``).

        Args:
            user_id: Dueño de los análisis.
            since: Solo análisis terminados después de este instante --
                normalmente ``IrisNotificationPreference.digest_last_sent_at``
                (o su fecha de creación, si nunca se envió un digest).
            critical_threshold: ``iris.criticalPhishingScoreThreshold``; se
                pasa como argumento en vez de leerlo aquí para que el
                repositorio no dependa de ``config_reading``.

        Returns:
            List[IrisAnalysis]: En orden cronológico ascendente.
        """
        return (
            self._session.query(IrisAnalysis)
            .filter(
                IrisAnalysis.user_id == user_id,
                IrisAnalysis.connection_id.isnot(None),
                IrisAnalysis.verdict == "Phishing",
                IrisAnalysis.total_score > critical_threshold,
                IrisAnalysis.finished_at.isnot(None),
                IrisAnalysis.finished_at > since,
            )
            .order_by(IrisAnalysis.finished_at.asc())
            .all()
        )

    def count_by_user(self, user_id: int) -> int:
        """
        Cuántos análisis tiene este usuario en total -- para el informe
        de retención, que necesita el denominador.

        Args:
            user_id: Dueño de los análisis.

        Returns:
            int: Número de análisis de este usuario.
        """
        return self._session.query(IrisAnalysis.id).filter(IrisAnalysis.user_id == user_id).count()

    def count_finished_by_user(self, user_id: int) -> int:
        """
        Cuántos análisis terminados tiene un usuario.

        Es el denominador de la cobertura de feedback: solo un análisis
        terminado tiene un veredicto que el analista pueda corregir.

        Args:
            user_id: Dueño de los análisis.

        Returns:
            int: Número de análisis en estado ``finished``.
        """
        return (
            self._session.query(IrisAnalysis.id)
            .filter(IrisAnalysis.user_id == user_id, IrisAnalysis.status == "finished")
            .count()
        )

    def count_with_raw_retained_by_user(self, user_id: int) -> int:
        """
        De los análisis de este usuario, cuántos conservan todavía su
        raw -- el complemento de cuántos ya se purgaron.
        
        Args:
            user_id: Dueño de los análisis.

        Returns:
            int: Número de análisis con al menos un ``IrisRawMessage``
                asociado.
        """
        return (
            self._session.query(IrisAnalysis.id)
            .join(IrisRawMessage, IrisRawMessage.analysis_id == IrisAnalysis.id)
            .filter(IrisAnalysis.user_id == user_id)
            .count()
        )

    def purge_raw_messages_older_than(self, cutoff: datetime) -> int:
        """
        Purga (borra) el ``IrisRawMessage`` de cada análisis creado antes
        de ``cutoff``, conservando el análisis y sus resultados.

        DELETE masivo en vez de cargar cada fila por el ORM: ``IrisRawMessage``
        no tiene ninguna tabla que dependa de ella (a diferencia de borrar un
        ``IrisAnalysis`` entero, que si se hiciera igual dejaría huérfanas
        las filas de ``IrisRuleResult``, que solo cascadan a nivel de ORM,
        no de base de datos -- ver ``delete_analyses_older_than``), así que
        aquí no hay riesgo de huérfanos que evitar yendo fila a fila.

        Args:
            cutoff: Instante tras el cual se considera que un análisis 
            es "viejo" y su "raw" puede purgarse.
        """
        result = self._session.execute(
            delete(IrisRawMessage).where(
                IrisRawMessage.analysis_id.in_(
                    select(IrisAnalysis.id).where(IrisAnalysis.created_at < cutoff)
                )
            )
        )
        return result.rowcount

    def get_analyses_older_than(self, cutoff: datetime) -> List[IrisAnalysis]:
        """Análisis creados antes de ``cutoff`` -- candidatos a borrado
        completo cuando ``iris.analysisRetentionDays`` está activo.

        Devuelve instancias ORM (no un ``DELETE`` masivo): borrarlas una a
        una vía ``BaseRepository.delete`` es lo que dispara el cascade real
        hacia ``IrisRuleResult`` (``cascade="all, delete-orphan"`` es un
        mecanismo del ORM, no de la base de datos -- un ``DELETE`` en SQL
        directo sobre ``IrisAnalysis`` dejaría esas filas huérfanas), y la
        retención no puede dejar huérfanos.

        Args:
            cutoff: Instante tras el cual se considera que un análisis
                es "viejo" y puede borrarse entero.

        Returns:
            List[IrisAnalysis]: Análisis candidatos a borrado.
        """
        return (
            self._session.query(IrisAnalysis)
            .filter(IrisAnalysis.created_at < cutoff)
            .all()
        )

    def get_campaign_candidates(self, *, user_id: int, since: datetime, exclude_id: int,
                                subject_fingerprint: Optional[str], template_fingerprint: Optional[str],
                                indicator_pairs: List[Tuple[str, str]], limit: int) -> List[IrisAnalysis]:
        """Análisis recientes de un usuario que comparten alguna señal con uno nuevo.

        Es el primer filtro de la agrupación en campañas: solo trae los que
        pueden parecerse (mismo asunto normalizado, misma plantilla o algún
        IOC en común); cuánto se parecen lo decide ``services/campaigns.py``.

        Args:
            user_id: Dueño; nunca se mezclan análisis de otro usuario.
            since: Solo los recibidos desde este instante (la ventana).
            exclude_id: El propio análisis nuevo.
            subject_fingerprint: Huella del asunto; ``None`` si no tiene.
            template_fingerprint: Huella de la plantilla; ``None`` si no tiene.
            indicator_pairs: Pares ``(kind, value)`` del índice de IOCs.
            limit: Máximo de candidatos.

        Returns:
            List[IrisAnalysis]: Análisis terminados y no legítimos, del más
                reciente al más antiguo. Vacía si ninguno comparte nada.
        """
        conditions = []
        if subject_fingerprint:
            conditions.append(IrisAnalysis.subject_fingerprint == subject_fingerprint)
        if template_fingerprint:
            conditions.append(IrisAnalysis.template_fingerprint == template_fingerprint)
        values_by_kind: dict[str, list[str]] = {}
        for kind, value in indicator_pairs:
            values_by_kind.setdefault(kind, []).append(value)
        if values_by_kind:
            conditions.append(IrisAnalysis.id.in_(
                select(IrisIndicator.analysis_id).where(or_(*(
                    and_(IrisIndicator.kind == kind, IrisIndicator.value.in_(values))
                    for kind, values in values_by_kind.items()
                )))
            ))
        if not conditions:
            return []
        return (
            self._session.query(IrisAnalysis)
            .filter(
                IrisAnalysis.user_id == user_id,
                IrisAnalysis.id != exclude_id,
                IrisAnalysis.status == "finished",
                IrisAnalysis.verdict.isnot(None),
                IrisAnalysis.verdict != "Legitimate",
                IrisAnalysis.created_at >= since,
                or_(*conditions),
            )
            .order_by(IrisAnalysis.created_at.desc(), IrisAnalysis.id.desc())
            .limit(limit)
            .all()
        )

    def transition_if_state(self, analysis_id: int, from_states: list[str], **fields: Any) -> bool:
        """
        Aplica ``fields`` sobre un análisis solo si su ``status`` actual
        está en ``from_states`` -- transición SQL condicionada, no un
        leer-decidir-escribir.

        El caso real: el usuario cancela un análisis a la vez que el worker
        termina de procesarlo. Sin esta condición dentro del propio UPDATE,
        cancel_analysis() y _persist_analysis_results() compiten por
        escribir la misma fila -- running->cancelled uno, running->finished
        el otro -- y gana quien confirme último en vez de ganar quien tenga
        razón. Con la condición en el ``WHERE``, la base de datos serializa
        los dos UPDATE: solo el primero en llegar afecta a la fila (y su
        ``rowcount`` es 1); el segundo no cambia nada (``rowcount`` 0), y
        quien lo invoque sabe por el valor de retorno que perdió la carrera
        y no debe fiarse de que su transición se aplicó. Mismo patrón que
        ``_claim_ai_summary()``, generalizado a cualquier conjunto de
        campos en vez de una sola columna.

        Args:
            analysis_id: Primary key del ``IrisAnalysis`` a transicionar.
            from_states: Estados de ``status`` en los que debe estar la fila
                para que la transición se aplique (p.ej. ``["running"]``, o
                los dos estados no terminales `_CANCELLABLE_STATES`). Una
                lista vacía nunca coincide con nada.
            **fields: Columnas a escribir si la condición se cumple --
                normalmente incluye ``status`` con el nuevo valor, más
                cualquier otro campo que deba cambiar en el mismo commit
                (``finished_at``, ``total_score``, ``verdict``...).

        Returns:
            bool: ``True`` si la fila estaba en uno de ``from_states`` y la
                transición se aplicó (``fields`` ya están escritos). ``False``
                si el análisis no existe, o si su ``status`` ya había
                cambiado a otra cosa -- en ese caso ningún campo de
                ``fields`` se ha tocado.
        """
        result = self._session.execute(
            update(IrisAnalysis)
            .where(and_(IrisAnalysis.id == analysis_id, IrisAnalysis.status.in_(from_states)))
            .values(**fields)
        )
        return bool(result.rowcount)


class IrisMailboxConnectionRepository(BaseRepository[IrisMailboxConnection]):
    """Data-access layer for IrisMailboxConnection records."""

    _MODEL = IrisMailboxConnection

    def get_by_user(self, user_id: int) -> List[IrisMailboxConnection]:
        """Return all connections belonging to a user, newest first."""
        return (
            self._session.query(IrisMailboxConnection)
            .filter(IrisMailboxConnection.user_id == user_id)
            .order_by(IrisMailboxConnection.created_at.desc())
            .all()
        )

    def count_for_user(self, user_id: int) -> int:
        """Number of connections a user already has (for the quota check)."""
        return (
            self._session.query(IrisMailboxConnection)
            .filter(IrisMailboxConnection.user_id == user_id)
            .count()
        )

    def get_by_user_provider_email(
        self, user_id: int, provider: str, account_email: str
    ) -> Optional[IrisMailboxConnection]:
        """Look up an existing connection for the same (user, provider, account)."""
        return (
            self._session.query(IrisMailboxConnection)
            .filter(
                IrisMailboxConnection.user_id == user_id,
                IrisMailboxConnection.provider == provider,
                IrisMailboxConnection.account_email == account_email,
            )
            .first()
        )

    def get_due_for_sync(self, older_than_minutes: int) -> List[IrisMailboxConnection]:
        """Active connections whose last sync is stale enough to poll again.

        Includes connections that have never synced (``last_sync_at`` is
        NULL) — the scheduler must give every new connection its bootstrap
        sync.
        """
        cutoff = utcnow_naive() - timedelta(minutes=older_than_minutes)
        return (
            self._session.query(IrisMailboxConnection)
            .filter(
                IrisMailboxConnection.status == "active",
                (IrisMailboxConnection.last_sync_at.is_(None))
                | (IrisMailboxConnection.last_sync_at < cutoff),
            )
            .all()
        )

    def get_newly_stuck_connections(self, stuck_after_minutes: int) -> List[IrisMailboxConnection]:
        """Conexiones activas que siguen intentando sincronizar pero llevan
        atascadas sin un sync limpio, y todavía no se ha avisado de ello.

        "Sigue intentando" (``last_sync_at`` no nulo) las distingue de una
        conexión recién creada que aún no ha tenido su primer sondeo -- esa
        no está atascada, solo no ha empezado. Una conexión que **nunca**
        ha tenido un sync limpio (``last_success_at`` nulo) se mide contra
        su propia fecha de creación en vez de contra un ``last_success_at``
        inexistente -- si no, toda conexión recién creada se marcaría
        atascada en la primera pasada del scheduler, antes incluso de que
        el sondeo periódico (``iris.pollIntervalMinutes``) tenga ocasión de
        intentarlo. ``stuck_alert_sent_at IS NULL`` evita reencolar un aviso
        en cada pasada mientras el problema sigue sin resolverse -- se
        limpia en cuanto un sync vuelve a dejar la cola vacía (ver
        ``_finish_sync``), así que una recaída posterior sí vuelve a avisar.
        """
        cutoff = utcnow_naive() - timedelta(minutes=stuck_after_minutes)
        never_succeeded_and_stale = and_(
            IrisMailboxConnection.last_success_at.is_(None),
            IrisMailboxConnection.created_at < cutoff,
        )
        succeeded_but_stale = IrisMailboxConnection.last_success_at < cutoff
        return (
            self._session.query(IrisMailboxConnection)
            .filter(
                IrisMailboxConnection.status == "active",
                IrisMailboxConnection.last_sync_at.isnot(None),
                IrisMailboxConnection.stuck_alert_sent_at.is_(None),
                never_succeeded_and_stale | succeeded_but_stale,
            )
            .all()
        )


class IrisMailboxInboxRepository(BaseRepository[IrisMailboxInbox]):
    """Data-access layer for IrisMailboxInbox -- la cola de checkpoint por
    mensaje que va delante del cursor del proveedor."""

    _MODEL = IrisMailboxInbox

    def get_pending(self, connection_id: int) -> List[IrisMailboxInbox]:
        """Referencias sin resolver de una conexión, en orden de llegada
        (FIFO) -- el orden importa porque es el mismo en que el proveedor
        las devolvió."""
        return (
            self._session.query(IrisMailboxInbox)
            .filter(
                IrisMailboxInbox.connection_id == connection_id,
                IrisMailboxInbox.status == "pending",
            )
            .order_by(IrisMailboxInbox.id.asc())
            .all()
        )

    def has_pending(self, connection_id: int) -> bool:
        """Si quedan referencias sin resolver.

        Mientras esto sea True, ``_finish_sync`` no puede confirmar el
        cursor del proveedor -- avanzarlo perdería esas referencias
        para siempre, porque el proveedor no las vuelve a listar.
        """
        return (
            self._session.query(IrisMailboxInbox.id)
            .filter(
                IrisMailboxInbox.connection_id == connection_id,
                IrisMailboxInbox.status == "pending",
            )
            .first()
        ) is not None

    def get_existing_provider_ids(self, connection_id: int, provider_message_ids: List[str]) -> set:
        """De una lista de ids candidatos, cuáles ya están en la cola
        (pendientes o ya marcados ``dead``) -- evita volver a encolar una
        fila que un sync anterior ya conoce."""
        if not provider_message_ids:
            return set()
        rows = (
            self._session.query(IrisMailboxInbox.provider_message_id)
            .filter(
                IrisMailboxInbox.connection_id == connection_id,
                IrisMailboxInbox.provider_message_id.in_(provider_message_ids),
            )
            .all()
        )
        return {row[0] for row in rows}

    def count_pending(self, connection_id: int) -> int:
        """Cuántas referencias siguen sin resolver ahora mismo --
        contadas en vivo sobre la tabla real, no un contador aparte que
        pudiera desincronizarse de ella."""
        return (
            self._session.query(IrisMailboxInbox.id)
            .filter(
                IrisMailboxInbox.connection_id == connection_id,
                IrisMailboxInbox.status == "pending",
            )
            .count()
        )

    def count_retrying(self, connection_id: int) -> int:
        """Cuántas referencias pendientes ya han fallado al menos una vez
        -- distingue "recién descubierto, primer intento" de "se le
        está costando, va por el segundo o más"."""
        return (
            self._session.query(IrisMailboxInbox.id)
            .filter(
                IrisMailboxInbox.connection_id == connection_id,
                IrisMailboxInbox.status == "pending",
                IrisMailboxInbox.attempts >= 1,
            )
            .count()
        )

    def count_dead(self, connection_id: int) -> int:
        """Cuántas referencias agotaron ``iris.maxInboxAttempts`` y quedaron
        ``dead`` -- mensajes que Iris ha dejado de intentar
        procesar, visibles pero ya sin bloquear el cursor."""
        return (
            self._session.query(IrisMailboxInbox.id)
            .filter(
                IrisMailboxInbox.connection_id == connection_id,
                IrisMailboxInbox.status == "dead",
            )
            .count()
        )

    def oldest_pending_created_at(self, connection_id: int) -> Optional[datetime]:
        """Cuándo se encoló la referencia pendiente más antigua de esta
        conexión, o ``None`` si no queda ninguna.

        La edad de esa fecha es la señal de "cuánto lleva atascado el
        mensaje más viejo" -- más útil para un administrador que un simple
        recuento de pendientes, que no dice si llevan segundos o días ahí.
        """
        row = (
            self._session.query(IrisMailboxInbox.created_at)
            .filter(
                IrisMailboxInbox.connection_id == connection_id,
                IrisMailboxInbox.status == "pending",
            )
            .order_by(IrisMailboxInbox.id.asc())
            .first()
        )
        return row[0] if row is not None else None


class IrisRuleResultRepository(BaseRepository[IrisRuleResult]):
    """Data-access layer for IrisRuleResult records."""

    _MODEL = IrisRuleResult

    def get_by_analysis(self, analysis_id: int,
                        context_type: Optional[str] = None) -> List[IrisRuleResult]:
        """Filas de regla de un análisis, ordenadas por posición.

        Args:
            analysis_id: Primary key del ``IrisAnalysis``.
            context_type: Si se da (``"inner"`` o ``"wrapper"``), solo las
                filas de ese contexto del reenvío. Por defecto ``None``:
                todas las filas, de cualquier contexto.

        Returns:
            List[IrisRuleResult]: Las filas pedidas; lista vacía si no hay.
        """
        query = self._session.query(IrisRuleResult).filter(
            IrisRuleResult.analysis_id == analysis_id
        )
        if context_type is not None:
            query = query.filter(IrisRuleResult.context_type == context_type)
        return query.order_by(IrisRuleResult.position).all()

    def delete_by_analysis(self, analysis_id: int) -> None:
        """Delete all rule results belonging to an analysis."""
        self._session.query(IrisRuleResult).filter(
            IrisRuleResult.analysis_id == analysis_id
        ).delete()


class IrisAnalystFeedbackRepository(BaseRepository[IrisAnalystFeedback]):
    """Acceso a las correcciones del analista (``IrisAnalystFeedback``).

    Cada corrección es una fila nueva; la vigente de un análisis es la de
    ``id`` más alto, que crece junto con ``created_at``.
    """

    _MODEL = IrisAnalystFeedback

    def get_by_analysis(self, analysis_id: int) -> List[IrisAnalystFeedback]:
        """Historial de correcciones de un análisis, de la más reciente a la más antigua.

        Args:
            analysis_id: Primary key del ``IrisAnalysis``.

        Returns:
            List[IrisAnalystFeedback]: Las correcciones; lista vacía si no hay.
        """
        return (
            self._session.query(IrisAnalystFeedback)
            .filter(IrisAnalystFeedback.analysis_id == analysis_id)
            .order_by(IrisAnalystFeedback.id.desc())
            .all()
        )

    def latest_for_analysis(self, analysis_id: int) -> Optional[IrisAnalystFeedback]:
        """Corrección vigente de un análisis.

        Args:
            analysis_id: Primary key del ``IrisAnalysis``.

        Returns:
            Optional[IrisAnalystFeedback]: La más reciente, o ``None`` si
                nadie lo ha revisado.
        """
        return (
            self._session.query(IrisAnalystFeedback)
            .filter(IrisAnalystFeedback.analysis_id == analysis_id)
            .order_by(IrisAnalystFeedback.id.desc())
            .first()
        )

    def get_reviewed_ids(self, analysis_ids: List[int]) -> set[int]:
        """De una lista de análisis, cuáles tienen al menos una corrección.

        Args:
            analysis_ids: Primary keys de los análisis a mirar.

        Returns:
            set[int]: Los que un analista ha revisado; vacío si ninguno.
        """
        if not analysis_ids:
            return set()
        rows = (
            self._session.query(IrisAnalystFeedback.analysis_id)
            .filter(IrisAnalystFeedback.analysis_id.in_(analysis_ids))
            .distinct()
            .all()
        )
        return {row[0] for row in rows}

    def latest_per_analysis_for_user(self, user_id: int) -> List[IrisAnalystFeedback]:
        """La corrección vigente de cada análisis revisado de un usuario.

        Es la entrada de las métricas: una etiqueta por análisis (la última),
        no una por corrección, para que cambiar de opinión no cuente dos veces.

        Args:
            user_id: Dueño de los análisis.

        Returns:
            List[IrisAnalystFeedback]: Una fila por análisis revisado, con su
                ``analysis`` ya cargado.
        """
        latest_ids = (
            select(func.max(IrisAnalystFeedback.id))
            .join(IrisAnalysis, IrisAnalysis.id == IrisAnalystFeedback.analysis_id)
            .where(IrisAnalysis.user_id == user_id)
            .group_by(IrisAnalystFeedback.analysis_id)
        )
        return (
            self._session.query(IrisAnalystFeedback)
            .options(joinedload(IrisAnalystFeedback.analysis))
            .filter(IrisAnalystFeedback.id.in_(latest_ids))
            .all()
        )


class IrisNotificationPreferenceRepository(BaseRepository[IrisNotificationPreference]):
    """Data-access layer for IrisNotificationPreference -- una fila
    por usuario, ver ``IrisNotificationPreference`` en ``model.py``."""

    _MODEL = IrisNotificationPreference

    def get_by_user_id(self, user_id: int) -> Optional[IrisNotificationPreference]:
        """Preferencias del usuario, o ``None`` si nunca las ha tocado --
        en ese caso rigen los valores por defecto del modelo sin que exista
        fila alguna (ver ``IrisNotificationPreferenceManager.get_or_default``)."""
        return (
            self._session.query(IrisNotificationPreference)
            .filter(IrisNotificationPreference.user_id == user_id)
            .first()
        )

    def get_due_for_digest(self, interval_hours: int) -> List[IrisNotificationPreference]:
        """Usuarios con el digest activo a los que toca enviarles uno:
        nunca se les ha enviado, o el último fue hace más de
        ``iris.digestIntervalHours``."""
        cutoff = utcnow_naive() - timedelta(hours=interval_hours)
        return (
            self._session.query(IrisNotificationPreference)
            .filter(
                IrisNotificationPreference.digest_enabled.is_(True),
                (IrisNotificationPreference.digest_last_sent_at.is_(None))
                | (IrisNotificationPreference.digest_last_sent_at < cutoff),
            )
            .all()
        )


class IrisTrustedSenderRepository(BaseRepository[IrisTrustedSender]):
    """Acceso a las excepciones de confianza (``IrisTrustedSender``).

    Las filas no se borran al revocarse: la auditoría necesita las caducadas y
    las revocadas tanto como las activas.
    """

    _MODEL = IrisTrustedSender

    def get_by_user(self, user_id: int) -> List[IrisTrustedSender]:
        """Todas las excepciones de un usuario, de la más reciente a la más antigua.

        Args:
            user_id: Dueño de las excepciones.

        Returns:
            List[IrisTrustedSender]: Activas, caducadas y revocadas; lista
                vacía si no tiene ninguna.
        """
        return (
            self._session.query(IrisTrustedSender)
            .filter(IrisTrustedSender.user_id == user_id)
            .order_by(IrisTrustedSender.id.desc())
            .all()
        )

    def get_active_for_user(self, user_id: int, now: datetime) -> List[IrisTrustedSender]:
        """Excepciones de un usuario que siguen en vigor en un instante.

        Args:
            user_id: Dueño de las excepciones.
            now: Instante de referencia (UTC naive).

        Returns:
            List[IrisTrustedSender]: Las no revocadas cuya caducidad es
                posterior a ``now``.
        """
        return (
            self._session.query(IrisTrustedSender)
            .filter(
                IrisTrustedSender.user_id == user_id,
                IrisTrustedSender.revoked_at.is_(None),
                IrisTrustedSender.expires_at > now,
            )
            .order_by(IrisTrustedSender.id.asc())
            .all()
        )

    def has_active(self, user_id: int, kind: str, value: str, now: datetime) -> bool:
        """Si el usuario ya tiene en vigor una excepción idéntica.

        Args:
            user_id: Dueño de las excepciones.
            kind: ``sender`` o ``domain``.
            value: Valor ya normalizado.
            now: Instante de referencia (UTC naive).

        Returns:
            bool: ``True`` si hay una no revocada y no caducada con ese tipo y
                valor.
        """
        return (
            self._session.query(IrisTrustedSender.id)
            .filter(
                IrisTrustedSender.user_id == user_id,
                IrisTrustedSender.kind == kind,
                IrisTrustedSender.value == value,
                IrisTrustedSender.revoked_at.is_(None),
                IrisTrustedSender.expires_at > now,
            )
            .first()
        ) is not None


class IrisSavedViewRepository(BaseRepository[IrisSavedView]):
    """Acceso a las vistas guardadas del historial (``IrisSavedView``)."""

    _MODEL = IrisSavedView

    def get_by_user(self, user_id: int) -> List[IrisSavedView]:
        """Vistas de un usuario, por nombre.

        Args:
            user_id: Dueño de las vistas.

        Returns:
            List[IrisSavedView]: Las vistas; lista vacía si no tiene.
        """
        return (
            self._session.query(IrisSavedView)
            .filter(IrisSavedView.user_id == user_id)
            .order_by(IrisSavedView.name.asc())
            .all()
        )

    def count_by_user(self, user_id: int) -> int:
        """Cuántas vistas tiene guardadas un usuario.

        Args:
            user_id: Dueño de las vistas.

        Returns:
            int: Número de vistas.
        """
        return self._session.query(IrisSavedView.id).filter(IrisSavedView.user_id == user_id).count()

    def get_by_user_and_name(self, user_id: int, name: str) -> Optional[IrisSavedView]:
        """Vista de un usuario con un nombre exacto.

        Args:
            user_id: Dueño de las vistas.
            name: Nombre ya recortado.

        Returns:
            Optional[IrisSavedView]: La vista, o ``None`` si no hay ninguna con ese nombre.
        """
        return (
            self._session.query(IrisSavedView)
            .filter(IrisSavedView.user_id == user_id, IrisSavedView.name == name)
            .first()
        )


class IrisAnalysisTagRepository(BaseRepository[IrisAnalysisTag]):
    """Acceso a las etiquetas de los análisis (``IrisAnalysisTag``)."""

    _MODEL = IrisAnalysisTag

    def delete_by_analysis(self, analysis_id: int) -> None:
        """Quita todas las etiquetas de un análisis.

        Args:
            analysis_id: Primary key del ``IrisAnalysis``.
        """
        self._session.query(IrisAnalysisTag).filter(IrisAnalysisTag.analysis_id == analysis_id).delete()

    def count_by_name_for_user(self, user_id: int) -> List[Tuple[str, int]]:
        """Etiquetas que usa un usuario y en cuántos análisis aparece cada una.

        Args:
            user_id: Dueño de los análisis.

        Returns:
            List[Tuple[str, int]]: ``(nombre, análisis)``, de la más usada a la
                menos y, a igual uso, por nombre.
        """
        count = func.count(IrisAnalysisTag.id)
        return [
            (name, total) for name, total in (
                self._session.query(IrisAnalysisTag.name, count)
                .join(IrisAnalysis, IrisAnalysis.id == IrisAnalysisTag.analysis_id)
                .filter(IrisAnalysis.user_id == user_id)
                .group_by(IrisAnalysisTag.name)
                .order_by(count.desc(), IrisAnalysisTag.name.asc())
                .all()
            )
        ]


class IrisIndicatorRepository(BaseRepository[IrisIndicator]):
    """Acceso al índice de IOCs (``IrisIndicator``).

    Las búsquedas por IOC las hace ``IrisAnalysisRepository.get_by_user_paginated``,
    que es donde se combinan con el resto de filtros del historial.
    """

    _MODEL = IrisIndicator

    def get_pairs_by_analysis_ids(self, analysis_ids: List[int]) -> dict[int, List[Tuple[str, str]]]:
        """Indicadores de varios análisis de una vez.

        Args:
            analysis_ids: Análisis cuyos indicadores se quieren.

        Returns:
            dict: ``{analysis_id: [(kind, value), ...]}``; un análisis sin
                indicadores no aparece.
        """
        if not analysis_ids:
            return {}
        pairs_by_analysis: dict[int, List[Tuple[str, str]]] = {}
        rows = (
            self._session.query(IrisIndicator.analysis_id, IrisIndicator.kind, IrisIndicator.value)
            .filter(IrisIndicator.analysis_id.in_(analysis_ids))
            .all()
        )
        for analysis_id, kind, value in rows:
            pairs_by_analysis.setdefault(analysis_id, []).append((kind, value))
        return pairs_by_analysis

    def exists_for_user(self, user_id: int, kind: str, value: str) -> bool:
        """Indica si un indicador aparece en algún análisis del usuario.

        Es la condición para enriquecerlo: Iris solo consulta fuera lo que el
        usuario ya ha visto en su correo, para no ser un proxy de consultas
        arbitrarias.

        Args:
            user_id: Usuario.
            kind: ``IrisIndicator.kind``.
            value: Valor exacto, en minúsculas.

        Returns:
            bool: ``True`` si está en su índice.
        """
        return self._session.query(
            self._session.query(IrisIndicator.id)
            .join(IrisAnalysis, IrisAnalysis.id == IrisIndicator.analysis_id)
            .filter(IrisAnalysis.user_id == user_id, IrisIndicator.kind == kind, IrisIndicator.value == value)
            .exists()
        ).scalar()

    def get_values_of_analysis(self, analysis_id: int, kind: str) -> List[str]:
        """Valores de un tipo de indicador de un análisis.

        Args:
            analysis_id: Análisis.
            kind: ``IrisIndicator.kind``.

        Returns:
            List[str]: Los valores (en minúsculas), ordenados.
        """
        return [
            value for (value,) in
            self._session.query(IrisIndicator.value)
            .filter(IrisIndicator.analysis_id == analysis_id, IrisIndicator.kind == kind)
            .order_by(IrisIndicator.value.asc())
            .all()
        ]

    def aggregate_across_users(self, user_ids: List[int], since: datetime, kinds: List[str],
                               min_users: int, limit: int) -> List[Tuple[str, str, int, int, datetime, datetime]]:
        """Indicadores de análisis no legítimos que comparten varios usuarios.

        Es el agregado anonimizado de la inteligencia de una organización:
        devuelve recuentos, nunca qué usuario ni qué análisis.

        Args:
            user_ids: Usuarios que aportan (los que han consentido).
            since: Solo análisis recibidos desde este instante.
            kinds: Tipos de indicador que entran.
            min_users: Usuarios distintos mínimos para que un indicador salga.
            limit: Máximo de indicadores.

        Returns:
            List[Tuple]: ``(kind, value, usuarios, análisis, primer
                avistamiento, último avistamiento)``, de más a menos usuarios.
        """
        if not user_ids:
            return []
        user_count = func.count(func.distinct(IrisAnalysis.user_id))
        rows = (
            self._session.query(
                IrisIndicator.kind, IrisIndicator.value, user_count,
                func.count(func.distinct(IrisAnalysis.id)),
                func.min(IrisAnalysis.created_at), func.max(IrisAnalysis.created_at),
            )
            .join(IrisAnalysis, IrisAnalysis.id == IrisIndicator.analysis_id)
            .filter(
                IrisAnalysis.user_id.in_(user_ids), IrisAnalysis.created_at >= since,
                IrisAnalysis.verdict.in_(["Suspicious", "Phishing"]), IrisIndicator.kind.in_(kinds),
            )
            .group_by(IrisIndicator.kind, IrisIndicator.value)
            .having(user_count >= min_users)
            .order_by(user_count.desc(), IrisIndicator.kind.asc(), IrisIndicator.value.asc())
            .limit(limit)
            .all()
        )
        return [tuple(row) for row in rows]

    def count_users_per_indicator(self, user_ids: List[int], since: datetime,
                                  pairs: List[Tuple[str, str]]) -> dict[Tuple[str, str], int]:
        """Cuántos usuarios distintos han visto cada uno de unos indicadores.

        Args:
            user_ids: Usuarios que cuentan.
            since: Solo análisis recibidos desde este instante.
            pairs: Pares ``(kind, value)`` por los que se pregunta.

        Returns:
            dict: ``{(kind, value): usuarios}``; los que nadie vio no aparecen.
        """
        if not user_ids or not pairs:
            return {}
        values_by_kind: dict[str, list[str]] = {}
        for kind, value in pairs:
            values_by_kind.setdefault(kind, []).append(value)
        rows = (
            self._session.query(IrisIndicator.kind, IrisIndicator.value,
                                func.count(func.distinct(IrisAnalysis.user_id)))
            .join(IrisAnalysis, IrisAnalysis.id == IrisIndicator.analysis_id)
            .filter(
                IrisAnalysis.user_id.in_(user_ids), IrisAnalysis.created_at >= since,
                or_(*(and_(IrisIndicator.kind == kind, IrisIndicator.value.in_(values))
                      for kind, values in values_by_kind.items())),
            )
            .group_by(IrisIndicator.kind, IrisIndicator.value)
            .all()
        )
        return {(kind, value): total for kind, value, total in rows}

    def get_shared_in_campaign(self, campaign_id: int, min_analyses: int = 2) -> List[Tuple[str, str, int]]:
        """Indicadores que comparten varios análisis de una campaña.

        Son los *pivots* de la campaña: lo que un analista busca en el SIEM o
        bloquea una sola vez para todos sus mensajes.

        Args:
            campaign_id: Campaña.
            min_analyses: En cuántos análisis tiene que aparecer como mínimo.
                Por defecto ``2``.

        Returns:
            List[Tuple[str, str, int]]: ``(kind, value, análisis)``, del más
                repetido al menos, y por tipo y valor a igualdad.
        """
        analysis_count = func.count(func.distinct(IrisIndicator.analysis_id))
        return [
            (kind, value, total) for kind, value, total in (
                self._session.query(IrisIndicator.kind, IrisIndicator.value, analysis_count)
                .join(IrisCampaignMember, IrisCampaignMember.analysis_id == IrisIndicator.analysis_id)
                .filter(IrisCampaignMember.campaign_id == campaign_id)
                .group_by(IrisIndicator.kind, IrisIndicator.value)
                .having(analysis_count >= min_analyses)
                .order_by(analysis_count.desc(), IrisIndicator.kind.asc(), IrisIndicator.value.asc())
                .all()
            )
        ]


class IrisCampaignRepository(BaseRepository[IrisCampaign]):
    """Acceso a las campañas (``IrisCampaign``)."""

    _MODEL = IrisCampaign

    def get_page_for_user(self, user_id: int, page: int, per_page: int,
                          min_members: int = 2) -> Tuple[List[Tuple[IrisCampaign, int, int, datetime, datetime]], int]:
        """Campañas de un usuario con sus cifras, de la más activa a la menos.

        Las cifras se calculan aquí a partir de los miembros, no se guardan:
        así borrar un análisis nunca deja una campaña con cifras viejas.

        Args:
            user_id: Dueño.
            page: Página, empezando en 1.
            per_page: Campañas por página.
            min_members: Miembros mínimos para contar como campaña. Por
                defecto ``2``: una campaña que se quedó con un solo análisis
                (porque se borraron los demás) no se enseña.

        Returns:
            Tuple: La página, como tuplas ``(campaña, análisis, mensajes
                distintos, primer avistamiento, último avistamiento)``, y el
                total de campañas. «Mensajes distintos» no cuenta dos veces el
                mismo correo analizado de nuevo (misma ``content_sha256``).
        """
        analysis_count = func.count(IrisAnalysis.id)
        message_count = func.count(func.distinct(
            func.coalesce(IrisAnalysis.content_sha256, cast(IrisAnalysis.id, String))
        ))
        first_seen = func.min(IrisAnalysis.created_at)
        last_seen = func.max(IrisAnalysis.created_at)
        query = (
            self._session.query(IrisCampaign, analysis_count, message_count, first_seen, last_seen)
            .join(IrisCampaignMember, IrisCampaignMember.campaign_id == IrisCampaign.id)
            .join(IrisAnalysis, IrisAnalysis.id == IrisCampaignMember.analysis_id)
            .filter(IrisCampaign.user_id == user_id)
            .group_by(IrisCampaign.id)
            .having(analysis_count >= min_members)
        )
        total = query.count()
        rows = (
            query.order_by(last_seen.desc(), IrisCampaign.id.desc())
            .limit(per_page)
            .offset((page - 1) * per_page)
            .all()
        )
        return [tuple(row) for row in rows], total

    def count_verdicts(self, campaign_ids: List[int]) -> dict[int, dict[str, int]]:
        """Cuántos análisis de cada campaña hay por veredicto.

        Args:
            campaign_ids: Campañas.

        Returns:
            dict: ``{campaign_id: {veredicto: análisis}}``.
        """
        if not campaign_ids:
            return {}
        rows = (
            self._session.query(IrisCampaignMember.campaign_id, IrisAnalysis.verdict, func.count(IrisAnalysis.id))
            .join(IrisAnalysis, IrisAnalysis.id == IrisCampaignMember.analysis_id)
            .filter(IrisCampaignMember.campaign_id.in_(campaign_ids))
            .group_by(IrisCampaignMember.campaign_id, IrisAnalysis.verdict)
            .all()
        )
        verdicts_by_campaign: dict[int, dict[str, int]] = {}
        for campaign_id, verdict, total in rows:
            verdicts_by_campaign.setdefault(campaign_id, {})[verdict or "unknown"] = total
        return verdicts_by_campaign


class IrisCampaignMemberRepository(BaseRepository[IrisCampaignMember]):
    """Acceso a la pertenencia de los análisis a campañas (``IrisCampaignMember``)."""

    _MODEL = IrisCampaignMember

    def get_by_analysis(self, analysis_id: int) -> Optional[IrisCampaignMember]:
        """La pertenencia de un análisis, si está en alguna campaña.

        Args:
            analysis_id: Análisis.

        Returns:
            Optional[IrisCampaignMember]: La fila, o ``None``.
        """
        return (
            self._session.query(IrisCampaignMember)
            .filter(IrisCampaignMember.analysis_id == analysis_id)
            .one_or_none()
        )

    def count_by_campaign(self, campaign_id: int) -> int:
        """Cuántos análisis tiene una campaña.

        Args:
            campaign_id: Campaña.

        Returns:
            int: Miembros; ``0`` si no tiene ninguno.
        """
        return (
            self._session.query(func.count(IrisCampaignMember.id))
            .filter(IrisCampaignMember.campaign_id == campaign_id)
            .scalar() or 0
        )

    def get_by_campaign(self, campaign_id: int) -> List[IrisCampaignMember]:
        """Miembros de una campaña con su análisis, del más reciente al más antiguo.

        Args:
            campaign_id: Campaña.

        Returns:
            List[IrisCampaignMember]: Los miembros, con ``analysis`` cargado.
        """
        return (
            self._session.query(IrisCampaignMember)
            .join(IrisAnalysis, IrisAnalysis.id == IrisCampaignMember.analysis_id)
            .options(joinedload(IrisCampaignMember.analysis))
            .filter(IrisCampaignMember.campaign_id == campaign_id)
            .order_by(IrisAnalysis.created_at.desc(), IrisAnalysis.id.desc())
            .all()
        )


class IrisCommunicationEdgeRepository(BaseRepository[IrisCommunicationEdge]):
    """Acceso al grafo de comunicación (``IrisCommunicationEdge``)."""

    _MODEL = IrisCommunicationEdge

    def get_edge(self, user_id: int, sender_address: str, recipient_address: str,
                 kind: str) -> Optional[IrisCommunicationEdge]:
        """La arista entre dos direcciones de un usuario, si existe.

        Args:
            user_id: Dueño del grafo.
            sender_address: Dirección del remitente, en minúsculas.
            recipient_address: Dirección del otro extremo, en minúsculas.
            kind: ``CommunicationKind``.

        Returns:
            Optional[IrisCommunicationEdge]: La arista, o ``None``.
        """
        return (
            self._session.query(IrisCommunicationEdge)
            .filter(
                IrisCommunicationEdge.user_id == user_id,
                IrisCommunicationEdge.sender_address == sender_address,
                IrisCommunicationEdge.recipient_address == recipient_address,
                IrisCommunicationEdge.kind == kind,
            )
            .one_or_none()
        )

    def get_senders(self, user_id: int, min_legitimate: int = 0,
                    limit: Optional[int] = None) -> List[Tuple[str, Optional[str], int, int, datetime, datetime]]:
        """Remitentes del grafo de un usuario con sus recuentos.

        Un mensaje con varios destinatarios deja una arista por cada uno, así
        que los mensajes de un remitente son el máximo de sus aristas, no la
        suma.

        Args:
            user_id: Dueño del grafo.
            min_legitimate: Solo los que tienen al menos estos mensajes
                legítimos. Por defecto ``0``: todos.
            limit: Máximo de remitentes. Por defecto ``None``: sin límite.

        Returns:
            List[Tuple]: ``(dirección, uno de sus nombres visibles —el último
                en orden alfabético—, mensajes, legítimos, primer avistamiento,
                último avistamiento)``, de más a menos mensajes legítimos.
        """
        legitimate = func.max(IrisCommunicationEdge.legitimate_count)
        query = (
            self._session.query(
                IrisCommunicationEdge.sender_address,
                func.max(IrisCommunicationEdge.sender_display_name),
                func.max(IrisCommunicationEdge.message_count),
                legitimate,
                func.min(IrisCommunicationEdge.first_seen_at),
                func.max(IrisCommunicationEdge.last_seen_at),
            )
            .filter(IrisCommunicationEdge.user_id == user_id)
            .group_by(IrisCommunicationEdge.sender_address)
            .having(legitimate >= min_legitimate)
            .order_by(legitimate.desc(), IrisCommunicationEdge.sender_address.asc())
        )
        if limit is not None:
            query = query.limit(limit)
        return [tuple(row) for row in query.all()]

    def get_display_names(self, user_id: int, sender_addresses: List[str]) -> dict[str, set[str]]:
        """Nombres visibles con los que ha escrito cada remitente.

        Args:
            user_id: Dueño del grafo.
            sender_addresses: Remitentes que interesan.

        Returns:
            dict: ``{dirección: {nombre, ...}}``; un remitente que nunca trajo
                nombre no aparece.
        """
        if not sender_addresses:
            return {}
        rows = (
            self._session.query(IrisCommunicationEdge.sender_address, IrisCommunicationEdge.sender_display_name)
            .filter(
                IrisCommunicationEdge.user_id == user_id,
                IrisCommunicationEdge.sender_address.in_(sender_addresses),
                IrisCommunicationEdge.sender_display_name.isnot(None),
            )
            .distinct()
            .all()
        )
        names_by_sender: dict[str, set[str]] = {}
        for address, name in rows:
            names_by_sender.setdefault(address, set()).add(name)
        return names_by_sender

    def get_by_user(self, user_id: int, address: Optional[str] = None,
                    limit: int = 500) -> List[IrisCommunicationEdge]:
        """Aristas de un usuario, de la usada más recientemente a la que menos.

        Args:
            user_id: Dueño del grafo.
            address: Solo las que tocan esta dirección, como remitente o como
                otro extremo. Por defecto ``None``: todas.
            limit: Máximo de aristas. Por defecto ``500``.

        Returns:
            List[IrisCommunicationEdge]: Las aristas.
        """
        query = self._session.query(IrisCommunicationEdge).filter(IrisCommunicationEdge.user_id == user_id)
        if address:
            query = query.filter(or_(
                IrisCommunicationEdge.sender_address == address,
                IrisCommunicationEdge.recipient_address == address,
            ))
        return query.order_by(IrisCommunicationEdge.last_seen_at.desc(), IrisCommunicationEdge.id.desc()) \
            .limit(limit).all()

    def aggregate_sender_domains(self, user_ids: List[int], min_users: int,
                                 limit: int) -> List[Tuple[str, int, int]]:
        """Dominios de los que varios usuarios reciben correo legítimo.

        Args:
            user_ids: Usuarios que aportan.
            min_users: Usuarios distintos mínimos para que un dominio salga.
            limit: Máximo de dominios.

        Returns:
            List[Tuple[str, int, int]]: ``(dominio, usuarios, mensajes
                legítimos)``, de más a menos usuarios.
        """
        if not user_ids:
            return []
        user_count = func.count(func.distinct(IrisCommunicationEdge.user_id))
        rows = (
            self._session.query(IrisCommunicationEdge.sender_domain, user_count,
                                func.sum(IrisCommunicationEdge.legitimate_count))
            .filter(IrisCommunicationEdge.user_id.in_(user_ids), IrisCommunicationEdge.legitimate_count > 0)
            .group_by(IrisCommunicationEdge.sender_domain)
            .having(user_count >= min_users)
            .order_by(user_count.desc(), IrisCommunicationEdge.sender_domain.asc())
            .limit(limit)
            .all()
        )
        return [(domain, users, int(messages or 0)) for domain, users, messages in rows]

    def delete_by_user(self, user_id: int) -> int:
        """Borra el grafo entero de un usuario.

        Args:
            user_id: Dueño del grafo.

        Returns:
            int: Aristas borradas.
        """
        result = self._session.execute(
            delete(IrisCommunicationEdge).where(IrisCommunicationEdge.user_id == user_id)
        )
        return result.rowcount or 0

    def purge_older_than(self, cutoff: datetime) -> int:
        """Borra las aristas que no se han visto desde ``cutoff``.

        Args:
            cutoff: Instante límite; se borra lo visto por última vez antes.

        Returns:
            int: Aristas borradas.
        """
        result = self._session.execute(
            delete(IrisCommunicationEdge).where(IrisCommunicationEdge.last_seen_at < cutoff)
        )
        return result.rowcount or 0


class IrisDomainCacheRepository(BaseRepository[IrisDomainCache]):
    """Acceso a la caché RDAP de dominios (``IrisDomainCache``)."""

    _MODEL = IrisDomainCache

    def get_by_domain(self, domain: str) -> Optional[IrisDomainCache]:
        """La entrada de caché de un dominio, caducada o no.

        Args:
            domain: Dominio registrable, en minúsculas.

        Returns:
            Optional[IrisDomainCache]: La entrada, o ``None``.
        """
        return self._session.query(IrisDomainCache).filter(IrisDomainCache.domain == domain).one_or_none()


class IrisUrlExpansionRepository(BaseRepository[IrisUrlExpansion]):
    """Acceso a las expansiones de URLs (``IrisUrlExpansion``)."""

    _MODEL = IrisUrlExpansion

    def get_by_user_and_hash(self, user_id: int, url_sha256: str) -> Optional[IrisUrlExpansion]:
        """La expansión de una URL de un usuario, si existe.

        Args:
            user_id: Usuario.
            url_sha256: ``IrisUrlExpansion.url_sha256``.

        Returns:
            Optional[IrisUrlExpansion]: La expansión, o ``None``.
        """
        return (
            self._session.query(IrisUrlExpansion)
            .filter(IrisUrlExpansion.user_id == user_id, IrisUrlExpansion.url_sha256 == url_sha256)
            .one_or_none()
        )

    def get_by_user_and_hashes(self, user_id: int, url_hashes: List[str]) -> List[IrisUrlExpansion]:
        """Las expansiones de varias URLs de un usuario.

        Args:
            user_id: Usuario.
            url_hashes: Huellas de las URLs.

        Returns:
            List[IrisUrlExpansion]: Las que existen, por URL.
        """
        if not url_hashes:
            return []
        return (
            self._session.query(IrisUrlExpansion)
            .filter(IrisUrlExpansion.user_id == user_id, IrisUrlExpansion.url_sha256.in_(url_hashes))
            .order_by(IrisUrlExpansion.url.asc())
            .all()
        )

    def claim_for_run(self, expansion_id: int) -> bool:
        """Pasa una expansión de ``pending`` a ``running`` si nadie la ha cogido ya.

        La outbox garantiza al menos una entrega: si el job llega dos veces,
        solo el primero la sigue.

        Args:
            expansion_id: Expansión.

        Returns:
            bool: ``True`` si este worker la ha reclamado.
        """
        result = self._session.execute(
            update(IrisUrlExpansion)
            .where(and_(IrisUrlExpansion.id == expansion_id, IrisUrlExpansion.status == "pending"))
            .values(status="running")
        )
        return bool(result.rowcount)


class IrisThreatIntelResultRepository(BaseRepository[IrisThreatIntelResult]):
    """Acceso a la caché de reputación (``IrisThreatIntelResult``)."""

    _MODEL = IrisThreatIntelResult

    def get_entry(self, provider: str, kind: str, value_sha256: str) -> Optional[IrisThreatIntelResult]:
        """Lo que dijo un proveedor de un indicador, caducado o no.

        Args:
            provider: Proveedor.
            kind: Tipo de indicador.
            value_sha256: Huella del indicador en minúsculas.

        Returns:
            Optional[IrisThreatIntelResult]: La entrada, o ``None``.
        """
        return (
            self._session.query(IrisThreatIntelResult)
            .filter(IrisThreatIntelResult.provider == provider, IrisThreatIntelResult.kind == kind,
                    IrisThreatIntelResult.value_sha256 == value_sha256)
            .one_or_none()
        )


class IrisTenantProfileRepository(BaseRepository[IrisTenantProfile]):
    """Acceso a la política de inteligencia de cada organización (``IrisTenantProfile``)."""

    _MODEL = IrisTenantProfile

    def get_by_organization(self, organization_id: int) -> Optional[IrisTenantProfile]:
        """La política de una organización, si se ha configurado alguna vez.

        Args:
            organization_id: Organización.

        Returns:
            Optional[IrisTenantProfile]: La política, o ``None``.
        """
        return (
            self._session.query(IrisTenantProfile)
            .filter(IrisTenantProfile.organization_id == organization_id)
            .one_or_none()
        )


class IrisTenantConsentRepository(BaseRepository[IrisTenantConsent]):
    """Acceso a los consentimientos de los miembros (``IrisTenantConsent``)."""

    _MODEL = IrisTenantConsent

    def get_by_user(self, user_id: int) -> Optional[IrisTenantConsent]:
        """El consentimiento de un usuario, vigente o revocado.

        Args:
            user_id: Usuario.

        Returns:
            Optional[IrisTenantConsent]: La fila, o ``None`` si nunca lo dio.
        """
        return self._session.query(IrisTenantConsent).filter(IrisTenantConsent.user_id == user_id).one_or_none()

    def get_active_user_ids(self, organization_id: int) -> List[int]:
        """Usuarios con consentimiento vigente dado en una organización.

        Args:
            organization_id: Organización.

        Returns:
            List[int]: Sus ids, ordenados. Quien pueda haber salido de la
                organización después lo filtra el llamante.
        """
        return [
            user_id for (user_id,) in
            self._session.query(IrisTenantConsent.user_id)
            .filter(IrisTenantConsent.organization_id == organization_id, IrisTenantConsent.revoked_at.is_(None))
            .order_by(IrisTenantConsent.user_id.asc())
            .all()
        ]


class IrisCaseRepository(BaseRepository[IrisCase]):
    """Acceso a los casos de analista (``IrisCase``)."""

    _MODEL = IrisCase

    def get_by_user_filtered(self, user_id: int, *, status: Optional[str] = None,
                             priority: Optional[str] = None,
                             assignee_id: Optional[int] = None) -> List[IrisCase]:
        """Casos de un usuario, del modificado más recientemente al más antiguo.

        Args:
            user_id: Dueño de los casos.
            status: Solo los de este estado. Por defecto ``None``: todos.
            priority: Solo los de esta prioridad. Por defecto ``None``: todas.
            assignee_id: Solo los asignados a este usuario. Por defecto
                ``None``: sin filtro.

        Returns:
            List[IrisCase]: Los casos, con sus vínculos y su asignado cargados.
        """
        query = (
            self._session.query(IrisCase)
            .options(selectinload(IrisCase.links), joinedload(IrisCase.assignee))
            .filter(IrisCase.user_id == user_id)
        )
        if status:
            query = query.filter(IrisCase.status == status)
        if priority:
            query = query.filter(IrisCase.priority == priority)
        if assignee_id is not None:
            query = query.filter(IrisCase.assignee_id == assignee_id)
        return query.order_by(IrisCase.updated_at.desc(), IrisCase.id.desc()).all()

    def count_by_status_for_user(self, user_id: int) -> dict:
        """Cuántos casos tiene un usuario en cada estado.

        Args:
            user_id: Dueño de los casos.

        Returns:
            dict: ``{estado: casos}``, solo con los estados que tienen alguno.
        """
        rows = (
            self._session.query(IrisCase.status, func.count(IrisCase.id))
            .filter(IrisCase.user_id == user_id)
            .group_by(IrisCase.status)
            .all()
        )
        return {status: total for status, total in rows}


class IrisCaseAnalysisRepository(BaseRepository[IrisCaseAnalysis]):
    """Acceso a los vínculos entre casos y análisis (``IrisCaseAnalysis``)."""

    _MODEL = IrisCaseAnalysis

    def get_link(self, case_id: int, analysis_id: int) -> Optional[IrisCaseAnalysis]:
        """El vínculo entre un caso y un análisis, si existe.

        Args:
            case_id: Primary key del caso.
            analysis_id: Primary key del análisis.

        Returns:
            Optional[IrisCaseAnalysis]: El vínculo, o ``None``.
        """
        return (
            self._session.query(IrisCaseAnalysis)
            .filter(IrisCaseAnalysis.case_id == case_id, IrisCaseAnalysis.analysis_id == analysis_id)
            .first()
        )


class IrisCaseEventRepository(BaseRepository[IrisCaseEvent]):
    """Acceso a la timeline de los casos (``IrisCaseEvent``).

    Los eventos se leen a través de ``IrisCase.events``; aquí solo se guardan.
    """

    _MODEL = IrisCaseEvent


class IrisBatchRepository(BaseRepository[IrisBatch]):
    """Acceso a los lotes de mensajes (``IrisBatch``)."""

    _MODEL = IrisBatch

    def get_recent_by_user(self, user_id: int, limit: int) -> List[IrisBatch]:
        """Lotes más recientes de un usuario.

        Args:
            user_id: Dueño de los lotes.
            limit: Cuántos como máximo.

        Returns:
            List[IrisBatch]: Del más nuevo al más antiguo, con sus elementos cargados.
        """
        return (
            self._session.query(IrisBatch)
            .options(selectinload(IrisBatch.items))
            .filter(IrisBatch.user_id == user_id)
            .order_by(IrisBatch.id.desc())
            .limit(limit)
            .all()
        )


class IrisBatchItemRepository(BaseRepository[IrisBatchItem]):
    """Acceso a los elementos de los lotes (``IrisBatchItem``).

    Se leen a través de ``IrisBatch.items``; aquí solo se guardan.
    """

    _MODEL = IrisBatchItem


class IrisWebhookSubscriptionRepository(BaseRepository[IrisWebhookSubscription]):
    """Acceso a las suscripciones de webhooks (``IrisWebhookSubscription``)."""

    _MODEL = IrisWebhookSubscription

    def get_by_user(self, user_id: int) -> List[IrisWebhookSubscription]:
        """Suscripciones de un usuario.

        Args:
            user_id: Dueño.

        Returns:
            List[IrisWebhookSubscription]: De la más antigua a la más nueva.
        """
        return (
            self._session.query(IrisWebhookSubscription)
            .filter(IrisWebhookSubscription.user_id == user_id)
            .order_by(IrisWebhookSubscription.id.asc())
            .all()
        )

    def count_by_user(self, user_id: int) -> int:
        """Cuántas suscripciones tiene un usuario, activas o no.

        Args:
            user_id: Dueño.

        Returns:
            int: Número de suscripciones; ``0`` si no tiene ninguna.
        """
        return (
            self._session.query(IrisWebhookSubscription)
            .filter(IrisWebhookSubscription.user_id == user_id)
            .count()
        )

    def get_active_for_event(self, user_id: int, event_type: str) -> List[IrisWebhookSubscription]:
        """Suscripciones activas de un usuario que reciben un tipo de evento.

        El filtro por tipo se hace en Python: ``event_types`` es una lista JSON
        de pocos elementos y un usuario tiene como mucho unas pocas
        suscripciones, así que no compensa una consulta distinta por dialecto.

        Args:
            user_id: Dueño.
            event_type: Valor de ``WebhookEventType``.

        Returns:
            List[IrisWebhookSubscription]: Las que están activas y suscritas a
                ``event_type``.
        """
        active = (
            self._session.query(IrisWebhookSubscription)
            .filter(IrisWebhookSubscription.user_id == user_id, IrisWebhookSubscription.is_active.is_(True))
            .order_by(IrisWebhookSubscription.id.asc())
            .all()
        )
        return [subscription for subscription in active if event_type in (subscription.event_types or [])]

    def reset_failures(self, subscription_id: int, delivered_at: datetime) -> None:
        """Anota una entrega que llegó: la cuenta de fallos seguidos vuelve a cero.

        Args:
            subscription_id: Suscripción.
            delivered_at: Cuándo llegó.
        """
        self._session.execute(
            update(IrisWebhookSubscription)
            .where(IrisWebhookSubscription.id == subscription_id)
            .values(consecutive_failures=0, last_success_at=delivered_at)
        )

    def increment_failures(self, subscription_id: int, failed_at: datetime, error: str) -> int:
        """Suma un intento fallido a la suscripción, dentro del propio ``UPDATE``.

        El incremento va en la base de datos y no en Python porque varios
        workers pueden estar entregando a la vez eventos de la misma
        suscripción.

        Args:
            subscription_id: Suscripción.
            failed_at: Cuándo falló.
            error: Motivo del fallo, ya recortado.

        Returns:
            int: Fallos seguidos después de sumar este; ``0`` si la suscripción
                ya no existe.
        """
        self._session.execute(
            update(IrisWebhookSubscription)
            .where(IrisWebhookSubscription.id == subscription_id)
            .values(
                consecutive_failures=IrisWebhookSubscription.consecutive_failures + 1,
                last_failure_at=failed_at,
                last_error=error,
            )
        )
        count = self._session.execute(
            select(IrisWebhookSubscription.consecutive_failures)
            .where(IrisWebhookSubscription.id == subscription_id)
        ).scalar()
        return int(count or 0)

    def deactivate_if_active(self, subscription_id: int, reason: str, disabled_at: datetime) -> bool:
        """Desactiva una suscripción que sigue activa, con su motivo.

        Args:
            subscription_id: Suscripción.
            reason: ``failures`` o ``gone``.
            disabled_at: Cuándo.

        Returns:
            bool: ``True`` si este llamante la desactivó; ``False`` si ya no
                estaba activa (otro worker se adelantó o la apagó el usuario).
        """
        result = self._session.execute(
            update(IrisWebhookSubscription)
            .where(and_(IrisWebhookSubscription.id == subscription_id,
                        IrisWebhookSubscription.is_active.is_(True)))
            .values(is_active=False, disabled_reason=reason, disabled_at=disabled_at)
        )
        return result.rowcount == 1


class IrisWebhookDeliveryRepository(BaseRepository[IrisWebhookDelivery]):
    """Acceso a las entregas de eventos (``IrisWebhookDelivery``)."""

    _MODEL = IrisWebhookDelivery

    def exists_for_event(self, subscription_id: int, event_id: str) -> bool:
        """Si un evento ya tiene entrega para una suscripción.

        Args:
            subscription_id: Suscripción.
            event_id: Id estable del evento.

        Returns:
            bool: ``True`` si ya se emitió ese evento a esa suscripción.
        """
        return self._session.query(
            self._session.query(IrisWebhookDelivery)
            .filter(IrisWebhookDelivery.subscription_id == subscription_id,
                    IrisWebhookDelivery.event_id == event_id)
            .exists()
        ).scalar()

    def get_page_of_subscription(self, subscription_id: int, page: int,
                                 per_page: int) -> Tuple[List[IrisWebhookDelivery], int]:
        """Historial de entregas de una suscripción, de la más nueva a la más antigua.

        Args:
            subscription_id: Suscripción.
            page: Página, empezando en 1.
            per_page: Entregas por página.

        Returns:
            tuple: ``(entregas, total)``.
        """
        return self.paginate(page=page, per_page=per_page, filters={"subscription_id": subscription_id},
                             order_by=IrisWebhookDelivery.id.desc())

    def claim_for_attempt(self, delivery_id: int, now: datetime) -> bool:
        """Pasa una entrega de ``pending`` a ``delivering`` si ya le toca y nadie la tiene.

        El envío lo pueden disparar a la vez el camino inmediato tras emitir y
        el barrido del scheduler; solo quien gana este ``UPDATE`` envía.

        Args:
            delivery_id: Entrega.
            now: Hora actual; la entrega tiene que tener ``next_attempt_at``
                anterior o igual.

        Returns:
            bool: ``True`` si este worker la ha reclamado.
        """
        result = self._session.execute(
            update(IrisWebhookDelivery)
            .where(and_(IrisWebhookDelivery.id == delivery_id,
                        IrisWebhookDelivery.status == WebhookDeliveryStatus.PENDING.value,
                        IrisWebhookDelivery.next_attempt_at <= now))
            .values(status=WebhookDeliveryStatus.DELIVERING.value, claimed_at=now)
        )
        return result.rowcount == 1

    def get_due_ids(self, now: datetime, limit: int) -> List[Tuple[int, int]]:
        """Entregas pendientes cuyo intento ya toca, de suscripciones activas.

        Args:
            now: Hora actual.
            limit: Cuántas como máximo.

        Returns:
            List[tuple]: Pares ``(id, intentos hechos)``, de la que más espera a
                la que menos.
        """
        rows = (
            self._session.query(IrisWebhookDelivery.id, IrisWebhookDelivery.attempts)
            .join(IrisWebhookSubscription, IrisWebhookSubscription.id == IrisWebhookDelivery.subscription_id)
            .filter(IrisWebhookDelivery.status == WebhookDeliveryStatus.PENDING.value,
                    IrisWebhookDelivery.next_attempt_at <= now,
                    IrisWebhookSubscription.is_active.is_(True))
            .order_by(IrisWebhookDelivery.next_attempt_at.asc())
            .limit(limit)
            .all()
        )
        return [(row[0], row[1]) for row in rows]

    def release_stale_claims(self, claimed_before: datetime) -> int:
        """Devuelve a ``pending`` las entregas cuyo worker murió a mitad de envío.

        Args:
            claimed_before: Una entrega ``delivering`` reclamada antes de esto
                se da por abandonada.

        Returns:
            int: Cuántas entregas se rescataron.
        """
        result = self._session.execute(
            update(IrisWebhookDelivery)
            .where(and_(IrisWebhookDelivery.status == WebhookDeliveryStatus.DELIVERING.value,
                        IrisWebhookDelivery.claimed_at < claimed_before))
            .values(status=WebhookDeliveryStatus.PENDING.value, claimed_at=None)
        )
        return result.rowcount or 0

    def fail_pending_of_subscription(self, subscription_id: int, error: str) -> int:
        """Da por fallidas las entregas pendientes de una suscripción que ya no recibe.

        Args:
            subscription_id: Suscripción desactivada.
            error: Motivo (``subscription_disabled``).

        Returns:
            int: Cuántas entregas se cerraron.
        """
        result = self._session.execute(
            update(IrisWebhookDelivery)
            .where(and_(IrisWebhookDelivery.subscription_id == subscription_id,
                        IrisWebhookDelivery.status == WebhookDeliveryStatus.PENDING.value))
            .values(status=WebhookDeliveryStatus.FAILED.value, last_error=error)
        )
        return result.rowcount or 0

    def purge_finished_older_than(self, cutoff: datetime) -> int:
        """Borra el historial de entregas terminadas (llegadas o fallidas) anterior a una fecha.

        Args:
            cutoff: Se borran las emitidas antes de esto.

        Returns:
            int: Cuántas se borraron.
        """
        result = self._session.execute(
            delete(IrisWebhookDelivery)
            .where(and_(IrisWebhookDelivery.created_at < cutoff,
                        IrisWebhookDelivery.status.in_([WebhookDeliveryStatus.DELIVERED.value,
                                                        WebhookDeliveryStatus.FAILED.value])))
        )
        return result.rowcount or 0


class IrisReportRepository(DocumentRepository[IrisDocument]):
    """Data-access layer for IrisDocument records (generated PDF reports).

    Las tres consultas de documentos las aporta ``DocumentRepository``.
    """

    _MODEL = IrisDocument
    _PARENT_FK = "analysis_id"
