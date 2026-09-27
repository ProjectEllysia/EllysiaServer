"""
Campañas: agrupar los análisis de un usuario que comparten origen.

Un análisis se compara, al terminar, con los análisis recientes del mismo
usuario que comparten con él alguna señal fuerte. El parecido es
**determinista** —una suma de pesos por señal coincidente— y no un modelo: se
puede explicar a un analista qué coincidió, y dos ejecuciones sobre los mismos
datos agrupan igual. Solo si esta versión demostrara no bastar tendría sentido
pasar a embeddings.

Las señales salen de dos sitios:

- el índice de IOCs (``IrisIndicator``): URLs, hashes de adjuntos, direcciones y
  dominios;
- tres rasgos que no son IOCs pero delatan una campaña, guardados en el propio
  análisis: la huella del asunto normalizado, la del esqueleto del cuerpo (la
  plantilla visual) y las marcas suplantadas.

Solo entran en campañas los análisis que Iris no consideró legítimos: agrupar
boletines de un mismo remitente llenaría la vista de ruido sin ayudar a
investigar nada.

Las funciones de huella y de parecido son puras; ``assign_to_campaign`` es la
única que toca la base de datos.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import src.modules.system.config_reading as CR
from src.modules.infrastructure import UnitOfWork
from src.modules.shared import utcnow_naive

from ..model import CampaignSignal, IrisCampaign, IrisCampaignMember
from ..repositories import (
    IrisAnalysisRepository,
    IrisCampaignMemberRepository,
    IrisCampaignRepository,
    IrisIndicatorRepository,
)
from .text import is_free_provider

#: Peso de cada señal coincidente. Una URL o un adjunto compartidos bastan por
#: sí solos para superar el umbral por defecto (5): nadie más manda ese enlace
#: ni ese fichero. El asunto solo no basta —«Factura pendiente» lo escriben
#: muchas campañas distintas—, pero con un dominio o una plantilla sí. Cada
#: tipo suma una sola vez por muchos valores que coincidan: un phishing enlaza a
#: menudo a la web real de la marca que suplanta, y dos campañas distintas
#: contra la misma marca no deben sumar un dominio por cada enlace legítimo.
SIGNAL_WEIGHTS: Dict[CampaignSignal, float] = {
    CampaignSignal.URL: 5.0,
    CampaignSignal.HASH: 5.0,
    CampaignSignal.TEMPLATE: 4.0,
    CampaignSignal.SUBJECT: 3.0,
    CampaignSignal.SENDER: 3.0,
    CampaignSignal.DOMAIN: 2.0,
    CampaignSignal.BRAND: 1.0,
}

#: Prefijos de respuesta y reenvío que se quitan del asunto, en varios idiomas.
_SUBJECT_PREFIX_RE = re.compile(r"^\s*((re|fw|fwd|rv|tr|aw|wg|sv|vs|enc|reenv)\s*(\[\d+\])?\s*:\s*)+", re.IGNORECASE)
_DIGITS_RE = re.compile(r"\d+")
_NON_WORD_RE = re.compile(r"[^\w#]+", re.UNICODE)
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_TAG_NAME_RE = re.compile(r"<\s*([a-zA-Z][a-zA-Z0-9]*)")

#: Un asunto normalizado más corto no distingue una campaña de otra («Hola»).
_MIN_SUBJECT_LENGTH = 8

#: Etiquetas HTML mínimas para que el esqueleto sea una plantilla y no un
#: ``<p>`` suelto que comparten miles de mensajes.
_MIN_TEMPLATE_TAGS = 12

#: Palabras mínimas del texto plano para tomarlo como plantilla.
_MIN_TEMPLATE_WORDS = 20

#: Longitud de las huellas (hex de SHA-256 recortado): sobra para no colisionar
#: dentro de las campañas de un usuario y cabe en un índice.
_FINGERPRINT_LENGTH = 32

#: ``IrisIndicator.kind`` → señal de campaña. Las IPs no cuentan: la del salto
#: de entrada suele ser la del proveedor de correo, compartida por todo.
_SIGNAL_BY_INDICATOR_KIND = {
    "url": CampaignSignal.URL,
    "hash": CampaignSignal.HASH,
    "email": CampaignSignal.SENDER,
    "domain": CampaignSignal.DOMAIN,
}


@dataclass(frozen=True)
class CampaignFeatures:
    """Rasgos de un análisis con los que se compara con otros.

    Attributes:
        subject_fingerprint: Huella del asunto normalizado, o ``None``.
        template_fingerprint: Huella del esqueleto del cuerpo, o ``None``.
        brands: Marcas suplantadas, en minúsculas.
        urls: URLs del cuerpo, en minúsculas.
        hashes: SHA-256 de los adjuntos.
        senders: Direcciones de ``From``, ``Reply-To`` y ``Return-Path``.
        domains: Dominios que no son de correo gratuito.
    """

    subject_fingerprint: Optional[str] = None
    template_fingerprint: Optional[str] = None
    brands: frozenset = field(default_factory=frozenset)
    urls: frozenset = field(default_factory=frozenset)
    hashes: frozenset = field(default_factory=frozenset)
    senders: frozenset = field(default_factory=frozenset)
    domains: frozenset = field(default_factory=frozenset)


@dataclass(frozen=True)
class CampaignTraits:
    """Rasgos de campaña que se guardan en el análisis al terminar.

    Attributes:
        subject_fingerprint: ``fingerprint_subject`` del asunto, o ``None``.
        template_fingerprint: ``fingerprint_template`` del cuerpo, o ``None``.
        brands: ``extract_brands`` de las reglas del contexto ganador.
        label: Asunto del mensaje tal cual, para rotular una campaña nueva;
            cadena vacía si no tenía.
    """

    subject_fingerprint: Optional[str]
    template_fingerprint: Optional[str]
    brands: Tuple[str, ...]
    label: str


@dataclass(frozen=True)
class SimilarityMatch:
    """Cuánto se parecen dos análisis y por qué.

    Attributes:
        score: Suma de los pesos de las señales coincidentes (``0.0`` si
            ninguna coincide).
        signals: Señales que coincidieron, ordenadas por su valor.
    """

    score: float
    signals: Tuple[CampaignSignal, ...]


def normalize_subject(subject: Optional[str]) -> str:
    """Reduce un asunto a la forma que comparten los mensajes de una campaña.

    Las campañas cambian el número de factura, el nombre del destinatario o
    añaden ``RE:`` para aparentar una conversación; lo que se mantiene es el
    resto del texto.

    Args:
        subject: Asunto tal como viene en la cabecera; ``None`` o vacío si no
            tenía.

    Returns:
        str: El asunto sin prefijos de respuesta o reenvío, en minúsculas, con
            cada número sustituido por ``#`` y los signos de puntuación
            colapsados en un espacio. Cadena vacía si no queda nada.
    """
    text = _SUBJECT_PREFIX_RE.sub("", subject or "")
    text = _DIGITS_RE.sub("#", text.lower())
    return _NON_WORD_RE.sub(" ", text).strip()


def fingerprint_subject(subject: Optional[str]) -> Optional[str]:
    """Huella del asunto normalizado (ver ``normalize_subject``).

    Args:
        subject: Asunto tal como viene en la cabecera.

    Returns:
        Optional[str]: Hex de ``_FINGERPRINT_LENGTH`` caracteres, o ``None`` si
            el asunto normalizado es demasiado corto para distinguir nada.
    """
    normalized = normalize_subject(subject)
    if len(normalized) < _MIN_SUBJECT_LENGTH:
        return None
    return _digest(f"subject:{normalized}")


def fingerprint_template(body_html: str, body_text: str) -> Optional[str]:
    """Huella de la plantilla del cuerpo.

    Con HTML, la plantilla es la secuencia de etiquetas sin atributos ni
    texto: dos correos de la misma campaña cambian nombres, importes y
    enlaces, pero se maquetan igual. Sin HTML, es el texto sin números ni
    URLs.

    Args:
        body_html: Parte HTML del cuerpo; vacía si no la hay.
        body_text: Parte de texto plano; vacía si no la hay.

    Returns:
        Optional[str]: Hex de ``_FINGERPRINT_LENGTH`` caracteres, o ``None`` si
            el cuerpo no tiene entidad suficiente (``_MIN_TEMPLATE_TAGS``
            etiquetas o ``_MIN_TEMPLATE_WORDS`` palabras) o no hay cuerpo.
    """
    tags = [name.lower() for name in _TAG_NAME_RE.findall(body_html or "")]
    if len(tags) >= _MIN_TEMPLATE_TAGS:
        return _digest("html:" + " ".join(tags))
    words = _NON_WORD_RE.sub(" ", _DIGITS_RE.sub("#", _URL_RE.sub(" ", (body_text or "").lower()))).split()
    if len(words) >= _MIN_TEMPLATE_WORDS:
        return _digest("text:" + " ".join(words))
    return None


def extract_brands(rule_details: Iterable[Tuple[float, Any]]) -> List[str]:
    """Marcas que las reglas vieron suplantadas.

    Solo cuentan las reglas que penalizaron: una regla que pasa también puede
    nombrar una marca («el remitente es de verdad paypal.com»).

    Args:
        rule_details: Pares ``(score, details)`` de las reglas del contexto
            ganador; ``details`` es el dict de ``RuleResult.details``.

    Returns:
        List[str]: Marcas en minúsculas, sin duplicados y ordenadas; vacía si
            ninguna regla nombró una.
    """
    brands: set[str] = set()
    for score, details in rule_details:
        if (score or 0) < 0:
            _collect_brands(details, brands)
    return sorted(brands)


def build_traits(context: Any, results: Iterable[Any]) -> CampaignTraits:
    """Calcula los rasgos de campaña de un mensaje ya evaluado.

    Args:
        context: ``MessageContext`` del contexto ganador.
        results: ``RuleResult`` de ese contexto (se leen ``score`` y
            ``details``).

    Returns:
        CampaignTraits: Huellas, marcas y rótulo.
    """
    subject = context.headers.get("subject", "") or ""
    return CampaignTraits(
        subject_fingerprint=fingerprint_subject(subject),
        template_fingerprint=fingerprint_template(context.body_html, context.body_text),
        brands=tuple(extract_brands((result.score, result.details) for result in results)),
        label=subject.strip(),
    )


def build_features(subject_fingerprint: Optional[str], template_fingerprint: Optional[str],
                   brands: Optional[Iterable[str]],
                   indicator_pairs: Iterable[Tuple[str, str]]) -> CampaignFeatures:
    """Junta los rasgos de un análisis a partir de lo que se guarda de él.

    Args:
        subject_fingerprint: ``IrisAnalysis.subject_fingerprint``.
        template_fingerprint: ``IrisAnalysis.template_fingerprint``.
        brands: ``IrisAnalysis.impersonated_brands``; ``None`` si no tiene.
        indicator_pairs: Pares ``(kind, value)`` de su ``IrisIndicator``.

    Returns:
        CampaignFeatures: Los rasgos, con los dominios de correo gratuito ya
            descartados.
    """
    values_by_signal: Dict[CampaignSignal, set] = {signal: set() for signal in _SIGNAL_BY_INDICATOR_KIND.values()}
    for kind, value in indicator_pairs:
        signal = _SIGNAL_BY_INDICATOR_KIND.get(kind)
        if signal is None or not value:
            continue
        if signal is CampaignSignal.DOMAIN and is_free_provider(value):
            continue
        values_by_signal[signal].add(value)
    return CampaignFeatures(
        subject_fingerprint=subject_fingerprint,
        template_fingerprint=template_fingerprint,
        brands=frozenset(brands or ()),
        urls=frozenset(values_by_signal[CampaignSignal.URL]),
        hashes=frozenset(values_by_signal[CampaignSignal.HASH]),
        senders=frozenset(values_by_signal[CampaignSignal.SENDER]),
        domains=frozenset(values_by_signal[CampaignSignal.DOMAIN]),
    )


def score_similarity(first: CampaignFeatures, second: CampaignFeatures) -> SimilarityMatch:
    """Mide cuánto se parecen dos análisis.

    Cada tipo de señal suma su peso de ``SIGNAL_WEIGHTS`` una sola vez si
    coincide al menos un valor. Es simétrica.

    Args:
        first: Rasgos de un análisis.
        second: Rasgos del otro.

    Returns:
        SimilarityMatch: La puntuación y las señales coincidentes.
    """
    matched: List[CampaignSignal] = []
    if first.subject_fingerprint and first.subject_fingerprint == second.subject_fingerprint:
        matched.append(CampaignSignal.SUBJECT)
    if first.template_fingerprint and first.template_fingerprint == second.template_fingerprint:
        matched.append(CampaignSignal.TEMPLATE)
    pairs = (
        (CampaignSignal.URL, first.urls, second.urls),
        (CampaignSignal.HASH, first.hashes, second.hashes),
        (CampaignSignal.SENDER, first.senders, second.senders),
        (CampaignSignal.DOMAIN, first.domains, second.domains),
        (CampaignSignal.BRAND, first.brands, second.brands),
    )
    for signal, first_values, second_values in pairs:
        if first_values & second_values:
            matched.append(signal)
    score = sum(SIGNAL_WEIGHTS[signal] for signal in matched)
    return SimilarityMatch(score=score, signals=tuple(sorted(matched, key=lambda signal: signal.value)))


def assign_to_campaign(uow: UnitOfWork, analysis_id: int, user_id: int, seen_at: datetime,
                       features: CampaignFeatures, label: Optional[str]) -> Optional[int]:
    """Mete un análisis recién terminado en la campaña del análisis más parecido.

    Busca, entre los análisis no legítimos del mismo usuario de los últimos
    ``window_days`` días, los que comparten alguna señal con este; se queda con
    el de mayor parecido que supere ``similarity_threshold``. Si ese análisis ya
    está en una campaña, este entra en ella; si no, se abre una campaña con los
    dos.

    Dos análisis de la misma campaña que terminan a la vez no se ven entre sí
    (cada transacción aún no ve la otra) y pueden quedar sueltos; el siguiente
    mensaje de la campaña los engancha.

    Args:
        uow: Transacción en curso.
        analysis_id: Análisis recién terminado.
        user_id: Su dueño; nunca se compara con análisis de otro usuario.
        seen_at: Cuándo se recibió el análisis; la ventana cuenta desde aquí.
        features: Sus rasgos (``build_features``).
        label: Asunto del mensaje, para rotular la campaña si se abre una.

    Returns:
        Optional[int]: Id de la campaña en la que entró, o ``None`` si no se
            parece lo bastante a ningún análisis reciente.
    """
    config = CR.iris_campaigns_config()
    indicator_pairs = _indicator_pairs(features)
    candidates = IrisAnalysisRepository(uow).get_campaign_candidates(
        user_id=user_id,
        since=seen_at - timedelta(days=config.window_days),
        exclude_id=analysis_id,
        subject_fingerprint=features.subject_fingerprint,
        template_fingerprint=features.template_fingerprint,
        indicator_pairs=indicator_pairs,
        limit=config.max_candidates,
    )
    if not candidates:
        return None

    pairs_by_analysis = IrisIndicatorRepository(uow).get_pairs_by_analysis_ids(
        [candidate.id for candidate in candidates]
    )
    best_candidate, best_match = None, None
    for candidate in candidates:
        candidate_features = build_features(
            candidate.subject_fingerprint, candidate.template_fingerprint,
            candidate.impersonated_brands, pairs_by_analysis.get(candidate.id, []),
        )
        match = score_similarity(features, candidate_features)
        if match.score < config.similarity_threshold:
            continue
        # Empate: el más reciente, que es el que mejor describe la campaña hoy.
        if best_match is None or match.score > best_match.score:
            best_candidate, best_match = candidate, match
    if best_candidate is None:
        return None

    member_repo = IrisCampaignMemberRepository(uow)
    now = utcnow_naive()
    candidate_link = member_repo.get_by_analysis(best_candidate.id)
    if candidate_link is not None:
        campaign = candidate_link.campaign
    else:
        campaign = IrisCampaignRepository(uow).save(IrisCampaign(
            user_id=user_id, label=(label or "").strip()[:120] or None, created_at=now, updated_at=now,
        ))
        member_repo.save(IrisCampaignMember(
            campaign_id=campaign.id, analysis_id=best_candidate.id, similarity=best_match.score,
            matched_signals=[signal.value for signal in best_match.signals], added_at=now,
        ))
    member_repo.save(IrisCampaignMember(
        campaign_id=campaign.id, analysis_id=analysis_id, similarity=best_match.score,
        matched_signals=[signal.value for signal in best_match.signals], added_at=now,
    ))
    campaign.updated_at = now
    return campaign.id


def _digest(text: str) -> str:
    """Hex SHA-256 de ``text`` recortado a ``_FINGERPRINT_LENGTH``."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:_FINGERPRINT_LENGTH]


def _collect_brands(value: Any, brands: set) -> None:
    """Recorre los ``details`` de una regla y recoge las marcas que nombra.

    Args:
        value: Un nivel de ``details`` (dict, lista o escalar).
        brands: Conjunto que se va rellenando, en minúsculas.
    """
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "brand" and isinstance(item, str) and item.strip():
                brands.add(item.strip().lower())
            elif key == "brands" and isinstance(item, (list, tuple)):
                brands.update(brand.strip().lower() for brand in item if isinstance(brand, str) and brand.strip())
            else:
                _collect_brands(item, brands)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _collect_brands(item, brands)


def _indicator_pairs(features: CampaignFeatures) -> List[Tuple[str, str]]:
    """Pares ``(kind, value)`` del índice de IOCs con los que buscar candidatos.

    Args:
        features: Rasgos del análisis nuevo.

    Returns:
        List[Tuple[str, str]]: URLs, hashes, direcciones y dominios no
            gratuitos, con el ``kind`` de ``IrisIndicator``.
    """
    kind_by_signal = {signal: kind for kind, signal in _SIGNAL_BY_INDICATOR_KIND.items()}
    values_by_signal: Sequence[Tuple[CampaignSignal, frozenset]] = (
        (CampaignSignal.URL, features.urls),
        (CampaignSignal.HASH, features.hashes),
        (CampaignSignal.SENDER, features.senders),
        (CampaignSignal.DOMAIN, features.domains),
    )
    return [(kind_by_signal[signal], value) for signal, values in values_by_signal for value in sorted(values)]
