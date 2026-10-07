/**
 * Prerender de lo que los buscadores y las redes leen de cada página pública.
 *
 * El SPA pinta el `<head>` de cada ruta con JavaScript (`src/composables/useSeo.js`).
 * Google y Bing lo ejecutan; LinkedIn, Slack, WhatsApp y los rastreadores de IA
 * no, y de cualquier enlace leen solo el `index.html` de la portada. Este módulo
 * genera, al construir, una copia de `index.html` por ruta pública con su título,
 * su descripción, su URL canónica y su `og:url`, y un bloque `<noscript>` con el
 * título, la descripción y los enlaces a las demás páginas públicas.
 *
 * No renderiza el cuerpo de las páginas: eso exigiría ejecutar el SPA en el
 * servidor. Quien ejecuta JavaScript sigue recibiendo el SPA de siempre, y
 * `useSeo` reescribe el `<head>` al montarlo con los mismos valores.
 *
 * Node puro, sin dependencias, para poder probarlo con `test/seo.test.mjs`.
 */

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const DEFAULT_APP_ROOT = fileURLToPath(new URL('../', import.meta.url))

/** Idioma del servidor: el que ve un rastreador, que no envía preferencia. */
const DEFAULT_LOCALE = 'es'

/**
 * Lee un fichero de texto con saltos de línea `\n`, aunque el checkout sea CRLF.
 *
 * @param {string} path - Ruta absoluta del fichero.
 * @returns {string} Su contenido en UTF-8.
 */
function readText(path) {
  return readFileSync(path, 'utf-8').replace(/\r\n/g, '\n')
}

/**
 * Escapa un texto para ponerlo en el cuerpo o en un atributo HTML.
 *
 * @param {string} text - Texto en claro.
 * @returns {string} El texto sin `&`, `<`, `>` ni `"` sueltos.
 */
function escapeHtml(text) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/**
 * Lee el origen público con el que se escriben las URL canónicas.
 *
 * @param {string} [appRoot] - Raíz de `web/app`. Por defecto, la de este repositorio.
 * @returns {string} Origen sin barra final (`https://www.ellysia.es`), tal como lo
 *   declara `SITE_ORIGIN` en `src/composables/useSeo.js`.
 */
export function readSiteOrigin(appRoot = DEFAULT_APP_ROOT) {
  return readText(join(appRoot, 'src/composables/useSeo.js')).match(/SITE_ORIGIN = '([^']+)'/)[1]
}

/**
 * Lee del router las rutas que declaran `meta.seo`.
 *
 * El router no se puede importar desde Node (usa el alias `@` y vue-router), así
 * que se lee como texto: cada ruta es un bloque `{ ... }` de primer nivel.
 *
 * @param {string} [appRoot] - Raíz de `web/app`. Por defecto, la de este repositorio.
 * @returns {Map<string, string>} Ruta (`/themis`) → clave de `seo.pages` (`themis`),
 *   en el orden en que están declaradas.
 * @throws {Error} Si no encuentra ninguna: el formato del router habrá cambiado.
 */
export function readSeoRoutes(appRoot = DEFAULT_APP_ROOT) {
  const routes = new Map()
  for (const block of readText(join(appRoot, 'src/router/index.js')).split(/\n {2}\{\n/)) {
    const path = block.match(/^\s*path: '([^']+)'/m)?.[1]
    const seoKey = block.match(/seo: '([^']+)'/)?.[1]
    if (path && seoKey) routes.set(path, seoKey)
  }
  if (routes.size === 0) throw new Error('no se encuentra ninguna ruta con meta.seo: ¿ha cambiado el formato del router?')
  return routes
}

/**
 * Sustituye una etiqueta de la plantilla y falla si no está.
 *
 * @param {string} html - Plantilla.
 * @param {RegExp} pattern - Etiqueta a sustituir.
 * @param {string} replacement - Etiqueta nueva, ya escapada.
 * @param {string} label - Cómo llamar a la etiqueta en el error.
 * @returns {string} La plantilla con la etiqueta cambiada.
 * @throws {Error} Si la plantilla no contiene la etiqueta: `index.html` habrá
 *   cambiado de forma y el prerender dejaría la página sin su valor propio.
 */
function replaceTag(html, pattern, replacement, label) {
  if (!pattern.test(html)) throw new Error(`index.html no contiene ${label}: el prerender no sabe dónde escribirlo`)
  return html.replace(pattern, () => replacement)
}

/**
 * Construye el bloque `<noscript>` de una página.
 *
 * @param {object} page - Contenido de la página.
 * @param {string} page.title - Título (`<h1>`).
 * @param {string} page.description - Descripción (`<p>`).
 * @param {Array<{path: string, title: string}>} page.links - Páginas públicas a enlazar.
 * @returns {string} El HTML del bloque, con todo el texto escapado.
 */
function renderNoscript({ title, description, links }) {
  const items = links.map(({ path, title: linkTitle }) => `<li><a href="${escapeHtml(path)}">${escapeHtml(linkTitle)}</a></li>`)
  return [
    '<noscript>',
    `      <h1>${escapeHtml(title)}</h1>`,
    `      <p>${escapeHtml(description)}</p>`,
    '      <nav><ul>',
    ...items.map((item) => `        ${item}`),
    '      </ul></nav>',
    '    </noscript>',
  ].join('\n')
}

/**
 * Añade el bloque `<noscript>` justo detrás del punto de montaje del SPA.
 *
 * @param {string} html - Plantilla.
 * @param {object} page - Lo mismo que recibe `renderNoscript`.
 * @returns {string} La plantilla con el bloque añadido.
 * @throws {Error} Si la plantilla no tiene `<div id="app"></div>` o ya lleva un `<noscript>`.
 */
export function insertNoscript(html, page) {
  if (html.includes('<noscript>')) throw new Error('index.html ya contiene un <noscript>: ¿se ha prerenderizado dos veces?')
  const mountPoint = '<div id="app"></div>'
  if (!html.includes(mountPoint)) throw new Error(`index.html no contiene ${mountPoint}`)
  return html.replace(mountPoint, () => `${mountPoint}\n    ${renderNoscript(page)}`)
}

/**
 * Genera el HTML de una página pública a partir de la plantilla del SPA.
 *
 * @param {string} template - `index.html` construido por Vite.
 * @param {object} page - Lo que se publica de la página.
 * @param {string} page.title - Título del documento y de `og:title`.
 * @param {string} page.description - Descripción del resultado de búsqueda y de `og:description`.
 * @param {string} page.canonicalUrl - URL absoluta canónica, también `og:url`.
 * @param {Array<{path: string, title: string}>} page.links - Páginas públicas del `<noscript>`.
 * @returns {string} La plantilla con los valores de la página.
 * @throws {Error} Si a la plantilla le falta alguna de las etiquetas que se sustituyen.
 */
export function renderSeoPage(template, { title, description, canonicalUrl, links }) {
  const safeTitle = escapeHtml(title)
  const safeDescription = escapeHtml(description)
  const safeCanonical = escapeHtml(canonicalUrl)
  let html = template
  html = replaceTag(html, /<title>[^<]*<\/title>/, `<title>${safeTitle}</title>`, '<title>')
  html = replaceTag(html, /<meta name="description" content="[^"]*" \/>/, `<meta name="description" content="${safeDescription}" />`, 'la descripción')
  html = replaceTag(html, /<meta property="og:title" content="[^"]*" \/>/, `<meta property="og:title" content="${safeTitle}" />`, 'og:title')
  html = replaceTag(
    html,
    /<meta property="og:description" content="[^"]*" \/>/,
    [
      `<meta property="og:description" content="${safeDescription}" />`,
      `    <meta property="og:url" content="${safeCanonical}" />`,
      `    <link rel="canonical" href="${safeCanonical}" />`,
    ].join('\n'),
    'og:description',
  )
  return insertNoscript(html, { title, description, links })
}

/**
 * Ruta del fichero que sirve una página pública dentro de `dist`.
 *
 * Es `<ruta>.html` y no `<ruta>/index.html`: Caddy redirige a una carpeta con
 * barra final, y las rutas del SPA se declaran sin ella.
 *
 * @param {string} distDirectory - Carpeta de salida de Vite.
 * @param {string} routePath - Ruta pública (`/docs/tecnica/themis`).
 * @returns {string} Ruta del fichero (`<dist>/docs/tecnica/themis.html`).
 */
export function prerenderedFilePath(distDirectory, routePath) {
  return join(distDirectory, `${routePath}.html`)
}

/**
 * Prerenderiza todas las páginas públicas sobre la carpeta de salida de Vite.
 *
 * Escribe un `<ruta>.html` por cada ruta con `meta.seo` salvo la portada, y añade
 * el `<noscript>` al `index.html`. A la portada no se le pone canónica: ese
 * fichero lo sirve Caddy para cualquier URL desconocida, y una canónica a `/`
 * en todas ellas sería falsa.
 *
 * @param {object} options - Opciones.
 * @param {string} options.distDirectory - Carpeta de salida de Vite, con su `index.html`.
 * @param {string} [options.appRoot] - Raíz de `web/app`. Por defecto, la de este repositorio.
 * @returns {string[]} Rutas públicas para las que se ha escrito un fichero propio.
 * @throws {Error} Si falta el texto `seo.pages.<clave>` de alguna ruta, o si
 *   `index.html` no tiene la forma esperada.
 */
export function prerenderSeoPages({ distDirectory, appRoot = DEFAULT_APP_ROOT }) {
  const origin = readSiteOrigin(appRoot)
  const texts = JSON.parse(readText(join(appRoot, `src/i18n/locales/${DEFAULT_LOCALE}.json`))).seo.pages
  const routes = readSeoRoutes(appRoot)
  const links = []
  for (const [path, key] of routes) {
    if (!texts[key]?.title || !texts[key]?.description) throw new Error(`falta seo.pages.${key} en ${DEFAULT_LOCALE}.json`)
    links.push({ path, title: texts[key].title })
  }

  const indexPath = join(distDirectory, 'index.html')
  const template = readText(indexPath)
  const written = []
  for (const [path, key] of routes) {
    if (path === '/') continue
    const html = renderSeoPage(template, {
      title: texts[key].title,
      description: texts[key].description,
      canonicalUrl: origin + path,
      links,
    })
    const filePath = prerenderedFilePath(distDirectory, path)
    mkdirSync(dirname(filePath), { recursive: true })
    writeFileSync(filePath, html)
    written.push(path)
  }
  const landing = texts[routes.get('/')]
  writeFileSync(indexPath, insertNoscript(template, { title: landing.title, description: landing.description, links }))
  return written
}
