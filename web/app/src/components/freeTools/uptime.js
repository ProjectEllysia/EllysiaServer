/**
 * Lógica sin Vue de la calculadora de disponibilidad gratuita
 * (`views/tools/hygeia/UptimeCalculatorView.vue`), para poder probarla con `node` a
 * secas.
 *
 * El año es el juliano, de 365,25 días, para que los años bisiestos cuenten en la media;
 * el mes es su doceava parte y el trimestre, su cuarta.
 */

import { parseDecimal } from './powerCost.js'

const DAY_SECONDS = 86400
const YEAR_SECONDS = 365.25 * DAY_SECONDS

/** Duración de cada periodo, en segundos, en el orden en que se enseñan. */
export const PERIOD_SECONDS = Object.freeze({
  day: DAY_SECONDS,
  week: 7 * DAY_SECONDS,
  month: YEAR_SECONDS / 12,
  quarter: YEAR_SECONDS / 4,
  year: YEAR_SECONDS,
})

/** Disponibilidades habituales en un acuerdo de nivel de servicio, en porcentaje. */
export const SLA_PRESETS = Object.freeze([99, 99.5, 99.9, 99.95, 99.99, 99.999])

/** Unidades en las que se escribe una duración, de la mayor a la menor, con sus segundos. */
const DURATION_UNITS = Object.freeze([['day', DAY_SECONDS], ['hour', 3600], ['minute', 60], ['second', 1]])

/**
 * Lee una disponibilidad escrita por una persona.
 *
 * @param {unknown} text - Lo escrito: `99,9`, `99.9` o `99.9 %`.
 * @returns {number|null} El porcentaje, entre 0 y 100 incluidos, o `null` si no es un
 *   número o se sale de ese rango.
 */
export function parseSla(text) {
  const value = parseDecimal(typeof text === 'string' ? text.replace('%', '') : text)
  return value !== null && value >= 0 && value <= 100 ? value : null
}

/**
 * Caída que permite una disponibilidad en cada periodo.
 *
 * @param {number} sla - Disponibilidad, en porcentaje (0 a 100).
 * @returns {Record<keyof PERIOD_SECONDS, number>} Segundos de caída permitidos por
 *   periodo; todos `0` con un 100 %.
 */
export function allowedDowntime(sla) {
  const downFraction = 1 - sla / 100
  return Object.fromEntries(Object.entries(PERIOD_SECONDS).map(([period, seconds]) => [period, seconds * downFraction]))
}

/**
 * Disponibilidad que deja un tiempo de caída en un periodo.
 *
 * @param {unknown} minutesText - Minutos de caída, tal como se escribieron.
 * @param {keyof PERIOD_SECONDS} period - Periodo en el que ocurrió la caída.
 * @returns {number|null} La disponibilidad, en porcentaje; `null` si los minutos no
 *   son un número, son negativos o superan la duración del periodo.
 */
export function availabilityFor(minutesText, period) {
  const minutes = parseDecimal(minutesText)
  const periodSeconds = PERIOD_SECONDS[period]
  if (minutes === null || !periodSeconds || minutes < 0 || minutes * 60 > periodSeconds) return null
  return 100 * (1 - (minutes * 60) / periodSeconds)
}

/**
 * Parte una duración en días, horas, minutos y segundos para escribirla.
 *
 * @param {number} seconds - Duración, en segundos.
 * @returns {Array<{unit: 'day'|'hour'|'minute'|'second', value: number}>} Las unidades
 *   que no son cero, de mayor a menor, con los segundos redondeados. Por debajo de diez
 *   segundos, una sola parte en segundos con hasta dos decimales, para que un 99,999 %
 *   al día no salga como «0 s». Vacío si la duración no es un número no negativo.
 */
export function durationParts(seconds) {
  if (!(seconds >= 0)) return []
  if (seconds < 10) return [{ unit: 'second', value: Math.round(seconds * 100) / 100 }]
  let rest = Math.round(seconds)
  const parts = []
  for (const [unit, size] of DURATION_UNITS) {
    const value = Math.floor(rest / size)
    rest -= value * size
    if (value) parts.push({ unit, value })
  }
  return parts
}
