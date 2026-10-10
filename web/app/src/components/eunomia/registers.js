/**
 * Lógica pura de los registros de Eunomia: qué valores se mandan al guardar una ficha y cómo se
 * agrupan sus plazos. Sin Vue ni red, para probarla con `node`.
 */

/**
 * Los valores de una ficha tal como hay que mandarlos: solo los campos que tienen texto.
 *
 * @param {Array<{key: string}>} fields - Campos de la definición.
 * @param {Record<string, string>} edited - Lo que hay en el formulario.
 * @returns {Record<string, string>}
 */
export function recordValues(fields, edited) {
  const values = {}
  for (const field of fields) {
    const value = edited[field.key] ?? ''
    if (value.trim()) values[field.key] = value
  }
  return values
}

/**
 * Las claves obligatorias sin valor.
 *
 * @param {Array<{key: string, isRequired: boolean}>} fields
 * @param {Record<string, string>} edited
 * @returns {string[]}
 */
export function missingFields(fields, edited) {
  return fields.filter((field) => field.isRequired && !(edited[field.key] ?? '').trim()).map((field) => field.key)
}

/**
 * Un valor de `datetime-local` (sin segundos ni zona) a lo que guarda la API, y al revés: la API
 * guarda ISO tal cual, así que solo hay que recortar para mostrarlo en el campo.
 *
 * @param {string} value
 * @returns {string} `AAAA-MM-DDTHH:MM`, o `''`.
 */
export function toDatetimeLocal(value) {
  return value ? value.slice(0, 16) : ''
}

/**
 * Cuántos plazos de un conjunto de fichas siguen abiertos y vencidos.
 *
 * @param {Array<{deadlines: Array<{status: string}>}>} records
 * @returns {{overdue: number, upcoming: number}}
 */
export function deadlineCounts(records) {
  const counts = { overdue: 0, upcoming: 0 }
  for (const record of records) {
    for (const deadline of record.deadlines ?? []) {
      if (deadline.status === 'overdue') counts.overdue += 1
      else if (deadline.status === 'upcoming') counts.upcoming += 1
    }
  }
  return counts
}
