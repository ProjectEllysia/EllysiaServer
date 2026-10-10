/**
 * Catálogo de las herramientas gratuitas de Ellysia: pequeñas utilidades que
 * cuelgan del hub de cada módulo y se pueden usar sin pagar un plan.
 *
 * Es la ÚNICA lista que hay que tocar para añadir una. De ella salen, sin más
 * registros a mano:
 *
 * - la sección «Herramientas gratuitas» del hub del módulo (`FreeTools.vue`),
 *   que no se pinta si el módulo no tiene ninguna;
 * - la ruta de cada herramienta (`routes.js`);
 * - el título, la canónica y el sitemap de su página (`scripts/seoPrerender.mjs`).
 *
 * Es JavaScript puro, sin Vue ni el alias `@`, para que lo importen tanto el
 * router como el prerender de `npm run build` (Node) y los tests. La vista de
 * cada herramienta se localiza por convención (`viewFile`), no por una tabla
 * paralela que pueda desincronizarse.
 *
 * Para añadir una herramienta:
 *
 * 1. Una entrada en `FREE_TOOLS`.
 * 2. La vista `src/views/tools/<módulo>/<Id>View.vue` (con la primera letra del
 *    `id` en mayúscula), montada sobre `ToolShell`.
 * 3. Sus textos en `freeTools.items.<id>` y `seo.pages.tool<Id>`, en `es.json`
 *    y en `en.json`; y su ruta en `public/sitemap.xml`.
 *
 * `test/freeTools.test.mjs` falla si falta cualquiera de las tres.
 */

/** Prefijo de las rutas de las herramientas. No es el de ningún módulo de la API,
 *  así que ni Caddy ni el proxy de Vite las mandan a Flask. */
export const FREE_TOOLS_PATH = '/herramientas'

/** Quién puede usar una herramienta: `public` no pide cuenta; `account` pide una
 *  cuenta gratuita (la página se ve igual y la acción pide entrar). */
export const FREE_TOOL_ACCESS = Object.freeze(['public', 'account'])

/**
 * Herramientas gratuitas, en el orden en que se enseñan.
 *
 * Cada entrada:
 *
 * - `id` — `camelCase`, único. Nombra la vista, los textos y la clave SEO.
 * - `module` — hub del que cuelga: `themis`, `aegis`, `iris`, `acheron` o `hygeia`.
 * - `slug` — último tramo de la URL, en castellano y con guiones.
 * - `access` — uno de `FREE_TOOL_ACCESS`.
 * - `surface` — opcional. Interruptor de `general.launch.surfaces` que, si el
 *   servidor lo cierra, esconde la herramienta de los hubs y de la ruta sin
 *   desplegar nada. Sin él, la herramienta está siempre abierta.
 */
export const FREE_TOOLS = Object.freeze([
  Object.freeze({ id: 'passwordGenerator', module: 'acheron', slug: 'generador-de-contrasenas', access: 'public' }),
  Object.freeze({ id: 'cveLookup', module: 'aegis', slug: 'consulta-de-cve', access: 'public' }),
  Object.freeze({ id: 'passwordStrength', module: 'acheron', slug: 'medidor-de-contrasenas', access: 'public' }),
  Object.freeze({ id: 'cidrCalculator', module: 'themis', slug: 'calculadora-cidr', access: 'public' }),
  Object.freeze({ id: 'mailAuthChecker', module: 'iris', slug: 'comprobador-spf-dmarc', access: 'public' }),
  Object.freeze({ id: 'lookalikeDomain', module: 'iris', slug: 'detector-de-dominios-enganosos', access: 'public' }),
  Object.freeze({ id: 'headerAnalyzer', module: 'iris', slug: 'analizador-de-cabeceras', access: 'public' }),
  Object.freeze({ id: 'cvssCalculator', module: 'aegis', slug: 'calculadora-cvss', access: 'public' }),
  Object.freeze({ id: 'phishingQuiz', module: 'aegis', slug: 'quiz-de-phishing', access: 'public' }),
  Object.freeze({ id: 'powerCost', module: 'hygeia', slug: 'calculadora-de-consumo', access: 'public' }),
  Object.freeze({ id: 'uptimeCalculator', module: 'hygeia', slug: 'calculadora-de-disponibilidad', access: 'public' }),
])

/**
 * Pone en mayúscula la primera letra.
 *
 * @param {string} text - Texto no vacío.
 * @returns {string} El mismo texto con la primera letra en mayúscula.
 */
function upperFirst(text) {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

/**
 * Ruta pública de una herramienta.
 *
 * @param {{module: string, slug: string}} tool - Entrada del catálogo.
 * @returns {string} Por ejemplo `/herramientas/acheron/generador-de-contrasenas`.
 */
export function freeToolPath(tool) {
  return `${FREE_TOOLS_PATH}/${tool.module}/${tool.slug}`
}

/**
 * Clave de `seo.pages` con el título y la descripción de la página.
 *
 * @param {{id: string}} tool - Entrada del catálogo.
 * @returns {string} Por ejemplo `toolPasswordGenerator`.
 */
export function freeToolSeoKey(tool) {
  return `tool${upperFirst(tool.id)}`
}

/**
 * Ruta de la vista, relativa a `src/views/tools/`, sin la extensión.
 *
 * @param {{id: string, module: string}} tool - Entrada del catálogo.
 * @returns {string} Por ejemplo `acheron/PasswordGeneratorView`.
 */
export function freeToolViewFile(tool) {
  return `${tool.module}/${upperFirst(tool.id)}View`
}

/**
 * Elige las herramientas que se pueden enseñar ahora.
 *
 * Una herramienta con `surface` solo cuenta mientras el servidor tenga esa
 * superficie abierta; hasta que llega su estado todas las superficies cuentan
 * como cerradas (ver `launchState.js`), así que no aparece de golpe y
 * desaparece después.
 *
 * @param {object} options - Opciones.
 * @param {ReadonlyArray<object>} [options.tools] - Catálogo. Por defecto, `FREE_TOOLS`.
 * @param {string|null} [options.moduleId] - Solo las de este módulo; `null` o
 *   ausente devuelve las de todos.
 * @param {(surface: string) => boolean} [options.isSurfaceEnabled] - Si una
 *   superficie del lanzamiento está abierta. Por defecto, ninguna lo está.
 * @returns {Array<object>} Copias de las entradas con su `path`, en el orden del
 *   catálogo. Vacío si el módulo no tiene herramientas: quien lo pinta no debe
 *   enseñar la sección.
 */
export function selectFreeTools({ tools = FREE_TOOLS, moduleId = null, isSurfaceEnabled = () => false } = {}) {
  return tools
    .filter((tool) => !moduleId || tool.module === moduleId)
    .filter((tool) => !tool.surface || isSurfaceEnabled(tool.surface))
    .map((tool) => ({ ...tool, path: freeToolPath(tool) }))
}
