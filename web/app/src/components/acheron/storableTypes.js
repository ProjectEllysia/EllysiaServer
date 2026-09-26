/**
 * Vista compuesta de los tipos de storable para la interfaz: une el contrato
 * de datos (`STORABLE_SCHEMA` de `@projectellysia/acheron-core-js`, generado
 * desde el catálogo de `AcheronCore`) con su presentación (`storableLabels.js`).
 *
 * Las dos mitades van separadas porque el esquema se publica con el paquete de
 * criptografía y la presentación no: cambiar el texto de un botón no debe
 * obligar a publicar una versión nueva del motor. Los textos en sí están en los
 * ficheros de idioma; aquí solo viajan sus claves.
 *
 * La capa cripto NO pasa por aquí: vive en el
 * paquete y lee el esquema directamente, y por eso nunca ve una etiqueta.
 *
 * `acheron.schema.test.mjs` verifica que las dos mitades siguen hablando de
 * los mismos campos.
 */
import { STORABLE_SCHEMA } from '@projectellysia/acheron-core-js'
import { STORABLE_LABELS } from './storableLabels.js'

/**
 * Tipos con esquema y etiquetas fusionados. Cada campo lleva su `key` y
 * `secret` del esquema, más `labelKey` (la clave de su rótulo) y las pistas de
 * formulario de las etiquetas.
 */
export const STORABLE_TYPES = STORABLE_SCHEMA.map((type) => {
  const labels = STORABLE_LABELS[type.kind] ?? { fields: {} }
  return {
    ...type,
    ...labels,
    fields: type.fields.map((field) => ({
      ...field,
      ...(labels.fields[field.key] ?? {}),
    })),
  }
})

/** Spec por categoría (clave plural del vault JSON). */
export const TYPE_BY_CATEGORY = Object.fromEntries(STORABLE_TYPES.map((type) => [type.category, type]))

/** Spec por kind (singular de la API). */
export const TYPE_BY_KIND = Object.fromEntries(STORABLE_TYPES.map((type) => [type.kind, type]))
