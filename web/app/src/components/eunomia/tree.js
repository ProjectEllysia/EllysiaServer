/**
 * Lógica pura del árbol personal de un marco: filtrar, aplanar lo visible y moverse con el
 * teclado. Sin Vue ni red, para poder probarla con `node`. No asume ninguna profundidad: un
 * marco de dos niveles (ISO 27001) y uno de cuatro (ENS) pasan por las mismas funciones.
 */

/** Estados de una evaluación, en el orden en que se ofrecen. */
export const STATUSES = Object.freeze(['pending', 'in_progress', 'implemented', 'not_applicable'])

/**
 * Estado de un nodo: el de su evaluación, o `null` si es un grupo (no se evalúa).
 *
 * @param {object} node - Nodo del árbol personal.
 * @returns {string|null}
 */
export function statusOf(node) {
  return node.assessment ? node.assessment.status : null
}

/**
 * Indica si un nodo coincide con la búsqueda por texto y con el filtro por estado.
 *
 * @param {object} node - Nodo del árbol.
 * @param {string} query - Texto a buscar en el identificador, el título y la descripción.
 * @param {string} status - Estado a exigir, o '' para cualquiera. Un grupo no tiene estado y
 *   por sí mismo no cumple un filtro de estado: lo cumplen sus hijos.
 * @returns {boolean}
 */
function matches(node, query, status) {
  if (status && statusOf(node) !== status) return false
  if (!query) return true
  const needle = query.trim().toLowerCase()
  return [node.identifier, node.title, node.description].some((text) => (text || '').toLowerCase().includes(needle))
}

/**
 * Poda el árbol a lo que coincide, conservando el camino hasta cada coincidencia.
 *
 * @param {Array} nodes - Raíces del árbol.
 * @param {{query?: string, status?: string}} [filters]
 * @returns {Array} Un árbol nuevo; los nodos que se conservan solo por ser ascendientes de una
 *   coincidencia llevan `isPathOnly: true`. Sin filtros, devuelve el árbol tal cual.
 */
export function filterTree(nodes, { query = '', status = '' } = {}) {
  if (!query && !status) return nodes
  const prune = (list) => list.flatMap((node) => {
    const children = prune(node.children)
    const own = matches(node, query, status)
    if (!own && !children.length) return []
    return [{ ...node, children, isPathOnly: !own }]
  })
  return prune(nodes)
}

/**
 * Aplana el árbol en el orden en que se ve, saltando lo que cuelga de un grupo contraído.
 *
 * @param {Array} nodes - Raíces del árbol (ya filtrado).
 * @param {Set<string>} expanded - Códigos de los grupos desplegados.
 * @returns {Array<{node: object, level: number, hasChildren: boolean, isExpanded: boolean}>}
 *   `level` empieza en 1, como `aria-level`.
 */
export function visibleNodes(nodes, expanded) {
  const rows = []
  const walk = (list, level) => {
    for (const node of list) {
      const hasChildren = node.children.length > 0
      const isExpanded = hasChildren && expanded.has(node.code)
      rows.push({ node, level, hasChildren, isExpanded })
      if (isExpanded) walk(node.children, level + 1)
    }
  }
  walk(nodes, 1)
  return rows
}

/**
 * Todos los códigos de grupo del árbol, para «expandir todo».
 *
 * @param {Array} nodes
 * @returns {Set<string>}
 */
export function groupCodes(nodes) {
  const codes = new Set()
  const walk = (list) => list.forEach((node) => {
    if (node.children.length) { codes.add(node.code); walk(node.children) }
  })
  walk(nodes)
  return codes
}

/**
 * Qué hace una tecla sobre el árbol (patrón ARIA de árbol).
 *
 * @param {Array} rows - Resultado de `visibleNodes`.
 * @param {string} currentCode - Código del nodo con el foco.
 * @param {string} key - `ArrowDown`, `ArrowUp`, `ArrowRight`, `ArrowLeft`, `Home` o `End`.
 * @returns {{focus: string|null, toggle: 'open'|'close'|null}} A qué nodo mover el foco y si hay
 *   que abrir o cerrar el actual. `focus` es `null` si la tecla no mueve nada.
 */
export function keyAction(rows, currentCode, key) {
  const index = rows.findIndex((row) => row.node.code === currentCode)
  if (index === -1) return { focus: rows[0]?.node.code ?? null, toggle: null }
  const row = rows[index]
  const at = (i) => rows[Math.min(Math.max(i, 0), rows.length - 1)].node.code
  switch (key) {
    case 'ArrowDown': return { focus: at(index + 1), toggle: null }
    case 'ArrowUp': return { focus: at(index - 1), toggle: null }
    case 'Home': return { focus: at(0), toggle: null }
    case 'End': return { focus: at(rows.length - 1), toggle: null }
    case 'ArrowRight':
      if (row.hasChildren && !row.isExpanded) return { focus: null, toggle: 'open' }
      if (row.hasChildren) return { focus: at(index + 1), toggle: null }
      return { focus: null, toggle: null }
    case 'ArrowLeft': {
      if (row.hasChildren && row.isExpanded) return { focus: null, toggle: 'close' }
      for (let i = index - 1; i >= 0; i -= 1) {
        if (rows[i].level < row.level) return { focus: rows[i].node.code, toggle: null }
      }
      return { focus: null, toggle: null }
    }
    default: return { focus: null, toggle: null }
  }
}

/**
 * Busca un nodo por código.
 *
 * @param {Array} nodes - Raíces del árbol.
 * @param {string} code - Código global del nodo.
 * @returns {object|null}
 */
export function findNode(nodes, code) {
  for (const node of nodes) {
    if (node.code === code) return node
    const found = findNode(node.children, code)
    if (found) return found
  }
  return null
}
