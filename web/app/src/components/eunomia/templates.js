/**
 * Lógica pura del formulario de una plantilla de documento de Eunomia: qué valores se guardan
 * y a dónde lleva el origen de un campo precargado. Sin Vue ni red, para probarla con `node`.
 */

/**
 * Los valores que hay que guardar de un formulario.
 *
 * Un campo precargado que el usuario no tocó **no** se guarda: si se guardara, dejaría de seguir
 * al perfil de empresa o a la evaluación de la que viene y quedaría congelado.
 *
 * @param {Array<{key: string, value: string, origin: string}>} fields - Campos tal como los dio la API.
 * @param {Record<string, string>} edited - Lo que hay ahora en el formulario, por clave.
 * @returns {Record<string, string>} Solo los campos con texto que el usuario escribió o cambió.
 */
export function valuesToSave(fields, edited) {
  const values = {}
  for (const field of fields) {
    const current = edited[field.key] ?? ''
    if (!current.trim()) continue
    if (field.origin !== 'saved' && current === field.value) continue
    values[field.key] = current
  }
  return values
}

/**
 * Las claves obligatorias que siguen sin valor en el formulario.
 *
 * @param {Array<{key: string, isRequired: boolean}>} fields
 * @param {Record<string, string>} edited
 * @returns {string[]} Claves, en el orden de la plantilla.
 */
export function missingRequired(fields, edited) {
  return fields.filter((field) => field.isRequired && !(edited[field.key] ?? '').trim()).map((field) => field.key)
}

/**
 * A dónde lleva el origen de un campo precargado, para corregirlo en su sitio.
 *
 * @param {{source: string|null, origin: string}} field
 * @param {string} framework - Marco de la plantilla.
 * @returns {string|null} Una ruta del SPA, o `null` si el campo no viene de ningún sitio editable.
 */
export function sourceRoute(field, framework) {
  if (field.origin === 'company') return '/profile'
  if (field.origin === 'assessment') return `/eunomia/marcos/${framework}`
  return null
}
