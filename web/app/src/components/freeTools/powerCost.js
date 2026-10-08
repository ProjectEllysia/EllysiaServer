/**
 * Lógica sin Vue de la calculadora de consumo eléctrico gratuita
 * (`views/tools/hygeia/PowerCostView.vue`), para poder probarla con `node` a secas.
 */

/** Días de un año y de un mes medio, para pasar el consumo diario a mensual y anual. */
const DAYS_PER_YEAR = 365
const DAYS_PER_MONTH = DAYS_PER_YEAR / 12

/** Qué se pide y entre qué valores es válido cada campo. `integer` exige un número entero. */
export const FIELD_LIMITS = Object.freeze({
  watts: Object.freeze({ min: 0, max: 100000 }),
  hoursPerDay: Object.freeze({ min: 0, max: 24 }),
  devices: Object.freeze({ min: 1, max: 100000, integer: true }),
  pricePerKwh: Object.freeze({ min: 0, max: 10 }),
  emissionFactor: Object.freeze({ min: 0, max: 2 }),
  pue: Object.freeze({ min: 1, max: 3 }),
})

/** Valores con los que arranca la calculadora, como texto, tal como se escribirían en el campo. */
export const DEFAULT_INPUTS = Object.freeze({
  watts: '150',
  hoursPerDay: '24',
  devices: '1',
  pricePerKwh: '0.15',
  emissionFactor: '0.15',
  pue: '1',
})

/** Potencias medias orientativas de equipos habituales, en vatios. */
export const POWER_PRESETS = Object.freeze([
  Object.freeze({ id: 'raspberryPi', watts: 5 }),
  Object.freeze({ id: 'miniPc', watts: 15 }),
  Object.freeze({ id: 'laptop', watts: 45 }),
  Object.freeze({ id: 'server', watts: 200 }),
  Object.freeze({ id: 'gpuServer', watts: 600 }),
])

/**
 * Lee un número escrito por una persona.
 *
 * @param {unknown} text - Lo escrito, con coma o con punto decimal y con o sin espacios.
 * @returns {number|null} El número, o `null` si está vacío o no es un número finito.
 */
export function parseDecimal(text) {
  if (typeof text === 'number') return Number.isFinite(text) ? text : null
  if (typeof text !== 'string' || text.trim() === '') return null
  const value = Number(text.replace(/\s+/g, '').replace(',', '.'))
  return Number.isFinite(value) ? value : null
}

/**
 * Valida y convierte todos los campos.
 *
 * @param {Record<string, unknown>} raw - Lo escrito en cada campo de `FIELD_LIMITS`.
 * @returns {{values: Record<string, number>|null, invalid: string[]}} `values` trae los
 *   seis números si todos son válidos y `null` si no; `invalid` lista los campos que
 *   están vacíos, no son un número, están fuera de su rango o (los que lo exigen) no
 *   son enteros.
 */
export function parseInputs(raw) {
  const values = {}
  const invalid = []
  for (const [field, limits] of Object.entries(FIELD_LIMITS)) {
    const value = parseDecimal(raw?.[field])
    const isValid = value !== null && value >= limits.min && value <= limits.max && (!limits.integer || Number.isInteger(value))
    if (isValid) values[field] = value
    else invalid.push(field)
  }
  return { values: invalid.length ? null : values, invalid }
}

/**
 * Calcula consumo, coste y emisiones.
 *
 * @param {object} values - Valores ya validados (`parseInputs`).
 * @param {number} values.watts - Potencia media de cada equipo, en vatios.
 * @param {number} values.hoursPerDay - Horas de uso al día (0 a 24).
 * @param {number} values.devices - Cuántos equipos iguales.
 * @param {number} values.pricePerKwh - Precio de la electricidad, en euros por kWh.
 * @param {number} values.emissionFactor - Emisiones de la electricidad, en kg de CO₂ por kWh.
 * @param {number} values.pue - Eficiencia del centro de datos: 1 si el equipo no está en uno;
 *   en uno, multiplica el consumo del equipo por lo que gasta la refrigeración.
 * @returns {{
 *   kwh: {day: number, month: number, year: number},
 *   cost: {day: number, month: number, year: number},
 *   co2Year: number
 * }} Energía en kWh, coste en euros y emisiones anuales en kg de CO₂. Supone un consumo
 *   constante igual a la potencia media.
 */
export function calculatePowerCost({ watts, hoursPerDay, devices, pricePerKwh, emissionFactor, pue }) {
  const day = (watts * hoursPerDay * devices * pue) / 1000
  const kwh = { day, month: day * DAYS_PER_MONTH, year: day * DAYS_PER_YEAR }
  return {
    kwh,
    cost: { day: day * pricePerKwh, month: kwh.month * pricePerKwh, year: kwh.year * pricePerKwh },
    co2Year: kwh.year * emissionFactor,
  }
}

/** Campos que viajan en la URL y la clave corta de cada uno. */
const QUERY_KEYS = Object.freeze({ watts: 'w', hoursPerDay: 'h', devices: 'n', pricePerKwh: 'p', emissionFactor: 'e', pue: 'u' })

/**
 * Pasa los campos a los parámetros de la URL.
 *
 * @param {Record<string, string>} inputs - Lo escrito en cada campo.
 * @returns {Record<string, string>} Solo los campos que no valen lo de por defecto.
 */
export function inputsToQuery(inputs) {
  const query = {}
  for (const [field, key] of Object.entries(QUERY_KEYS)) {
    if (String(inputs[field]).trim() !== DEFAULT_INPUTS[field]) query[key] = String(inputs[field]).trim()
  }
  return query
}

/**
 * Lee los campos de los parámetros de la URL.
 *
 * @param {Record<string, unknown>} query - Parámetros de la URL.
 * @returns {Record<string, string>} Los seis campos: el de la URL si es un número válido
 *   dentro de su rango, y el de por defecto en otro caso.
 */
export function queryToInputs(query) {
  const inputs = { ...DEFAULT_INPUTS }
  for (const [field, key] of Object.entries(QUERY_KEYS)) {
    const candidate = query?.[key]
    if (typeof candidate === 'string' && parseInputs({ ...DEFAULT_INPUTS, [field]: candidate }).invalid.length === 0) inputs[field] = candidate
  }
  return inputs
}
