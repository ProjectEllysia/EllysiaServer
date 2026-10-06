/**
 * Contenido de la documentación técnica: una página por herramienta.
 *
 * Cada página es un fichero `<idioma>/<herramienta>.json` de esta carpeta.
 * No vive en `i18n/locales/` a propósito: esos ficheros se cargan enteros en
 * todas las páginas, y la documentación pesa más que el resto de la interfaz
 * junta. Aquí cada fichero se descarga solo al abrir su página.
 *
 * Forma de un fichero:
 *
 * ```json
 * {
 *   "title": "Themis",
 *   "lede": "Entradilla bajo el título.",
 *   "sections": [
 *     {
 *       "id": "recorrido",
 *       "heading": "El recorrido de un escaneo",
 *       "blocks": [
 *         { "type": "p", "text": "Párrafo con **negrita** y `código`." },
 *         { "type": "list", "items": ["…", "…"] },
 *         { "type": "steps", "items": [{ "title": "…", "text": "…" }] },
 *         { "type": "terms", "items": [{ "term": "…", "text": "…" }] },
 *         { "type": "callout", "text": "…" }
 *       ],
 *       "figures": [
 *         { "image": "themis/escaneo.png", "alt": "…", "caption": "…" }
 *       ]
 *     }
 *   ]
 * }
 * ```
 *
 * Las figuras son opcionales y nunca necesarias: el texto de una sección se
 * entiende sin ellas, y una sección sin `figures` no pinta ningún hueco. La
 * imagen se busca en `src/assets/images/documentation/` por la ruta de `image`.
 * `test/docs.content.test.mjs` exige que los dos idiomas tengan las mismas
 * secciones, los mismos tipos de bloque y las mismas figuras.
 */

/** Las herramientas, en el orden del panteón. */
export const DOC_TOOLS = ['themis', 'aegis', 'iris', 'acheron', 'hygeia']

/** Idioma de respaldo cuando una página no está traducida. */
const FALLBACK_LOCALE = 'es'

const pageLoaders = import.meta.glob('./*/*.json', { import: 'default' })

const figureUrls = Object.fromEntries(
  Object.entries(
    import.meta.glob('../../assets/images/documentation/**/*.{png,jpg,jpeg,webp,svg}', { eager: true, import: 'default' }),
  ).map(([path, url]) => [path.replace('../../assets/images/documentation/', ''), url]),
)

/**
 * Ruta del fichero de una página dentro de esta carpeta.
 *
 * @param {string} locale - Código del idioma (`'es'`, `'en'`).
 * @param {string} tool - Herramienta, uno de {@link DOC_TOOLS}.
 * @returns {string} La clave con la que la indexa `import.meta.glob`.
 */
function pagePath(locale, tool) {
  return `./${locale}/${tool}.json`
}

/**
 * Herramientas que ya tienen página, en el orden del panteón.
 *
 * Una herramienta sin fichero no aparece en ningún índice ni enlace: la
 * documentación crece página a página sin anunciar páginas vacías.
 *
 * @returns {string[]} Subconjunto ordenado de {@link DOC_TOOLS}.
 */
export function availableDocTools() {
  return DOC_TOOLS.filter((tool) => pagePath(FALLBACK_LOCALE, tool) in pageLoaders)
}

/**
 * Carga la página de una herramienta en el idioma pedido.
 *
 * @param {string} tool - Herramienta, uno de {@link DOC_TOOLS}.
 * @param {string} locale - Idioma activo de la interfaz.
 * @returns {Promise<object|null>} El contenido de la página (ver la forma en
 *   la cabecera de este módulo), en castellano si el idioma pedido no tiene
 *   traducción; `null` si la herramienta no tiene página.
 */
export async function loadToolDoc(tool, locale) {
  const loader = pageLoaders[pagePath(locale, tool)] ?? pageLoaders[pagePath(FALLBACK_LOCALE, tool)]
  return loader ? loader() : null
}

/**
 * URL publicada de la imagen de una figura.
 *
 * @param {string} image - Ruta relativa a `src/assets/images/documentation/`
 *   (`'themis/escaneo.png'`).
 * @returns {string|null} La URL que genera Vite, o `null` si el fichero no
 *   existe; en ese caso la figura no se pinta.
 */
export function resolveFigureUrl(image) {
  return figureUrls[image] ?? null
}
