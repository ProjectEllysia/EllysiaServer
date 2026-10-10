/**
 * Lógica pura de «¿Me aplica NIS2?»: de las respuestas de quien visita a si la Directiva (UE)
 * 2022/2555 le alcanza y con qué categoría. Sin Vue ni red, para probarla con `node`.
 *
 * Las reglas son las de los artículos 2 y 3 de la directiva y los anexos I y II, que están en
 * `nis2ApplicabilityData.js` (actividades con su anexo y, si la tienen, la regla especial) y en
 * las constantes de abajo (umbrales de tamaño de la Recomendación 2003/361/CE). Nada se guarda y
 * nada sale del navegador.
 */
import data from './nis2ApplicabilityData.js'

/** Resultado: la directiva no le alcanza con lo que ha respondido. */
export const OUTCOME_NOT_APPLICABLE = 'notApplicable'
/** Resultado: le aplica y es entidad importante (art. 3.2). */
export const OUTCOME_IMPORTANT = 'important'
/** Resultado: le aplica y es entidad esencial (art. 3.1). */
export const OUTCOME_ESSENTIAL = 'essential'
/** Resultado: le aplica, pero la directiva deja la categoría al Estado miembro. */
export const OUTCOME_UNCLASSIFIED = 'unclassified'

/** Reglas especiales de una actividad (`rule` en el JSON). */
export const RULE_DNS_OR_TLD = 'dns_or_tld'
export const RULE_TRUST = 'trust'
export const RULE_PUBLIC_COMMS = 'public_comms'
export const RULE_CENTRAL_ADMIN = 'central_admin'
export const RULE_REGIONAL_ADMIN = 'regional_admin'

/** Tamaños que distingue la directiva. `atLeastMedium`: se sabe que no es pequeña, pero no si supera el tope de mediana. */
export const SIZE_SMALL = 'small'
export const SIZE_MEDIUM = 'medium'
export const SIZE_LARGE = 'large'
export const SIZE_AT_LEAST_MEDIUM = 'atLeastMedium'

/** Umbrales de la Recomendación 2003/361/CE, artículo 2: personas y millones de euros. */
const LARGE_EMPLOYEES = 250
const LARGE_TURNOVER = 50
const LARGE_BALANCE = 43
const MEDIUM_EMPLOYEES = 50
const SMALL_AMOUNT = 10

/** Actividades de los anexos, en el orden de la directiva. */
export const ACTIVITIES = Object.freeze([...data.annexes.I, ...data.annexes.II])

/**
 * La actividad con ese identificador.
 *
 * @param {string} id - Identificador (`'I.1.a'`, `'I.8.dns'`…).
 * @returns {object|undefined} La actividad, o `undefined` si no existe.
 */
export function findActivity(id) {
  return ACTIVITIES.find((activity) => activity.id === id)
}

/**
 * Lee una cifra escrita por una persona: acepta coma o punto decimal y vacío.
 *
 * @param {string|number|null|undefined} value - Lo escrito.
 * @returns {number|null|undefined} El número; `null` si está vacío; `undefined` si no es un número válido o es negativo.
 */
export function parseAmount(value) {
  if (value === null || value === undefined) return null
  if (typeof value === 'number') return Number.isFinite(value) && value >= 0 ? value : undefined
  const text = String(value).trim().replace(',', '.')
  if (text === '') return null
  const number = Number(text)
  return Number.isFinite(number) && number >= 0 ? number : undefined
}

/**
 * El tamaño de empresa según la Recomendación 2003/361/CE.
 *
 * Es grande con 250 personas o más, o con más de 50 M€ de facturación **y** más de 43 M€ de balance;
 * pequeña (con las microempresas) con menos de 50 personas y una de las dos cifras en 10 M€ o menos;
 * mediana en el resto. Con datos que no bastan para decidir se devuelve lo que sí se sabe.
 *
 * @param {{employees: number|null, turnover: number|null, balance: number|null}} figures - Personas, facturación y balance (M€); `null` si no se han dado.
 * @returns {string|null} Uno de `SIZE_*`, o `null` si sin más datos no se puede decir.
 */
export function companySize({ employees, turnover, balance }) {
  if (employees === null) return null
  if (employees >= LARGE_EMPLOYEES) return SIZE_LARGE
  if (turnover !== null && balance !== null && turnover > LARGE_TURNOVER && balance > LARGE_BALANCE) return SIZE_LARGE
  if (employees < MEDIUM_EMPLOYEES) {
    const isSmall = (turnover !== null && turnover <= SMALL_AMOUNT) || (balance !== null && balance <= SMALL_AMOUNT)
    if (isSmall) return SIZE_SMALL
    return turnover !== null && balance !== null ? SIZE_MEDIUM : null
  }
  const isNotLarge = (turnover !== null && turnover <= LARGE_TURNOVER) || (balance !== null && balance <= LARGE_BALANCE)
  return isNotLarge ? SIZE_MEDIUM : SIZE_AT_LEAST_MEDIUM
}

/** Prioridad de los resultados, de menor a mayor: gana el más exigente. */
const RANK = [OUTCOME_NOT_APPLICABLE, OUTCOME_UNCLASSIFIED, OUTCOME_IMPORTANT, OUTCOME_ESSENTIAL]

/**
 * Aplica los artículos 2 y 3 de la directiva a unas respuestas.
 *
 * @param {object} answers
 * @param {boolean} answers.hasEuActivity - Si presta servicios o desarrolla su actividad en la Unión.
 * @param {string|null} answers.activityId - Identificador de la actividad (`ACTIVITIES`); `null` si ninguna de las de los anexos.
 * @param {number|null} answers.employees - Personas empleadas.
 * @param {number|null} answers.turnover - Volumen de negocio anual, en millones de euros.
 * @param {number|null} answers.balance - Balance general anual, en millones de euros.
 * @param {boolean} [answers.isQualifiedTrust] - Si, siendo prestador de servicios de confianza, está cualificado.
 * @param {boolean} [answers.isCriticalEntity] - Si ha sido identificada como entidad crítica (Directiva 2022/2557).
 * @param {boolean} [answers.isIdentifiedByState] - Si un Estado miembro la ha identificado por ser proveedor único, por su impacto o por su criticidad (art. 2.2, letras b a e).
 * @param {boolean} [answers.isDomainRegistrar] - Si presta servicios de registro de nombres de dominio (art. 2.4).
 * @returns {{outcome: string, reasons: string[], caveats: string[]}|{missing: string[]}} El resultado con las claves de sus motivos y de sus avisos
 *   (se traducen en `freeTools.items.nis2Applicability.reasons.<clave>` y `.caveats.<clave>`), o `{missing}` con lo que falta para decidir (`'size'`).
 */
export function assess(answers) {
  const activity = answers.activityId ? findActivity(answers.activityId) : null
  const size = companySize({ employees: answers.employees, turnover: answers.turnover, balance: answers.balance })
  const reasons = []
  const caveats = []
  let outcome = OUTCOME_NOT_APPLICABLE
  const raise = (candidate, reason) => {
    reasons.push(reason)
    if (RANK.indexOf(candidate) > RANK.indexOf(outcome)) outcome = candidate
  }

  if (!answers.hasEuActivity) {
    return { outcome: OUTCOME_NOT_APPLICABLE, reasons: ['noEuActivity'], caveats: [] }
  }

  // Lo que no depende del tamaño.
  if (answers.isCriticalEntity) raise(OUTCOME_ESSENTIAL, 'criticalEntity')
  if (activity?.rule === RULE_DNS_OR_TLD) raise(OUTCOME_ESSENTIAL, 'dnsOrTld')
  if (activity?.rule === RULE_TRUST) {
    if (answers.isQualifiedTrust) raise(OUTCOME_ESSENTIAL, 'trustQualified')
    else raise(OUTCOME_IMPORTANT, 'trustNotQualified')
  }
  if (activity?.rule === RULE_CENTRAL_ADMIN) raise(OUTCOME_ESSENTIAL, 'centralAdministration')
  if (answers.isDomainRegistrar) raise(OUTCOME_UNCLASSIFIED, 'domainRegistrar')
  if (answers.isIdentifiedByState) raise(OUTCOME_UNCLASSIFIED, 'identifiedByState')

  // Lo que sí depende del tamaño: comunicaciones electrónicas y el resto de actividades de los anexos.
  const isSizeless = outcome !== OUTCOME_NOT_APPLICABLE && activity?.rule !== RULE_PUBLIC_COMMS
  if (activity?.rule === RULE_PUBLIC_COMMS) {
    if (size === SIZE_SMALL) raise(OUTCOME_IMPORTANT, 'publicCommsSmall')
    else if (size === null && !isSizeless) return { missing: ['size'] }
    else raise(OUTCOME_ESSENTIAL, 'publicCommsMediumOrLarge')
  } else if (activity && ![RULE_DNS_OR_TLD, RULE_TRUST, RULE_CENTRAL_ADMIN].includes(activity.rule)) {
    if (activity.rule === RULE_REGIONAL_ADMIN) {
      raise(OUTCOME_IMPORTANT, 'regionalAdministration')
      caveats.push('regionalAdministration')
    } else if (size === SIZE_SMALL) {
      if (outcome === OUTCOME_NOT_APPLICABLE) reasons.push('smallBelowThreshold')
    } else if (size === SIZE_LARGE) {
      raise(activity.annex === 'I' ? OUTCOME_ESSENTIAL : OUTCOME_IMPORTANT, activity.annex === 'I' ? 'annexILarge' : 'annexIILarge')
    } else if (size === SIZE_MEDIUM || size === SIZE_AT_LEAST_MEDIUM) {
      if (activity.annex === 'II' || size === SIZE_MEDIUM) {
        raise(OUTCOME_IMPORTANT, activity.annex === 'I' ? 'annexIMedium' : 'annexIIMediumOrLarge')
      } else if (outcome === OUTCOME_NOT_APPLICABLE) {
        return { missing: ['size'] }
      }
    } else if (outcome === OUTCOME_NOT_APPLICABLE) {
      return { missing: ['size'] }
    }
  } else if (!activity && outcome === OUTCOME_NOT_APPLICABLE) {
    reasons.push('noAnnexActivity')
  }

  if (outcome === OUTCOME_NOT_APPLICABLE) caveats.push('supplyChain')
  if (outcome !== OUTCOME_NOT_APPLICABLE) caveats.push('spainTransposition')
  return { outcome, reasons, caveats }
}
