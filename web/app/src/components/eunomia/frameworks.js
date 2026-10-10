/**
 * Lógica pura de la pantalla de marcos de Eunomia: cómo se reparten los marcos del catálogo
 * entre disponibles, adoptados y archivados, y qué cantidades enseña la confirmación de quitar
 * uno. Sin Vue ni red, para poder probarla con `node`.
 */

/**
 * Reparte el catálogo según lo que el dueño efectivo tiene adoptado.
 *
 * @param {Array<{key: string}>} catalog - Marcos del catálogo (`GET /eunomia/frameworks`).
 * @param {Array<{frameworkKey: string, status: string}>} adoptions - Adopciones (`GET /eunomia/adoptions`).
 * @returns {{available: Array, active: Array, archived: Array}} `available` son los marcos del
 *   catálogo sin adopción; `active` y `archived` son las adopciones tal cual, en el orden recibido.
 */
export function splitFrameworks(catalog, adoptions) {
  const taken = new Set(adoptions.map((adoption) => adoption.frameworkKey))
  return {
    available: catalog.filter((framework) => !taken.has(framework.key)),
    active: adoptions.filter((adoption) => adoption.status === 'active'),
    archived: adoptions.filter((adoption) => adoption.status === 'archived'),
  }
}

/**
 * Las cantidades de la vista previa de quitar un marco que valen la pena decir.
 *
 * Un aviso que enumera ceros solo añade ruido; si no hay nada que perder, la lista sale vacía y
 * la interfaz dice que no se pierde ninguna evaluación.
 *
 * @param {{assessments: number, evidenceDeleted: number, evidenceKept: number}} preview
 * @returns {Array<{key: string, count: number}>} En el orden: evaluaciones, evidencias que se
 *   borran, evidencias que se conservan. Solo las que tienen más de cero.
 */
export function removalFacts(preview) {
  return ['assessments', 'evidenceDeleted', 'evidenceKept']
    .map((key) => ({ key, count: Number(preview?.[key] ?? 0) }))
    .filter((fact) => fact.count > 0)
}

/**
 * Indica si lo que se pierde justifica enfatizar el aviso.
 *
 * @param {{assessments: number, evidenceDeleted: number}} preview
 * @returns {boolean} `true` si hay evaluaciones o evidencias que se borrarían.
 */
export function hasLoss(preview) {
  return Number(preview?.assessments ?? 0) > 0 || Number(preview?.evidenceDeleted ?? 0) > 0
}

/**
 * Las cantidades de la vista previa de pasar un marco a otra versión que valen la pena decir.
 *
 * @param {{moves: Array<{needsReview: boolean}>, lost: Array, newControls: Array}} plan
 * @returns {Array<{key: string, count: number}>} En el orden: trasladadas tal cual, a revisar,
 *   perdidas y nuevas. Solo las que tienen más de cero.
 */
export function upgradeFacts(plan) {
  const moves = plan?.moves ?? []
  const review = moves.filter((move) => move.needsReview).length
  return [
    { key: 'moved', count: moves.length - review },
    { key: 'review', count: review },
    { key: 'lost', count: (plan?.lost ?? []).length },
    { key: 'added', count: (plan?.newControls ?? []).length },
  ].filter((fact) => fact.count > 0)
}
