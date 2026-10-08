/**
 * Tests de lo que se publica para los buscadores: `public/sitemap.xml`,
 * `public/robots.txt`, las rutas con `meta.seo`, sus textos en `seo.pages`, la
 * imagen para compartir, el prerender del `<head>` (`scripts/seoPrerender.mjs`)
 * y las reglas de Caddy que lo sirven y que marcan la API como no indexable.
 *
 * Node puro, sin framework, misma convención que el resto de `test/`. Lee los
 * ficheros como texto; no arranca el router.
 *
 * Son cuatro listas que nadie está obligado a mirar a la vez: una página
 * pública que falta en el sitemap no se descubre, una entrada del sitemap sin
 * `meta.seo` lleva `noindex` (Search Console la marca como error) y una clave
 * de `meta.seo` sin texto pinta la clave cruda como título del resultado.
 */

import assert from 'node:assert/strict'
import { copyFileSync, existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { prerenderSeoPages, prerenderedFilePath, readSeoRoutes, readSiteOrigin, renderSeoPage } from '../scripts/seoPrerender.mjs'

const appRoot = fileURLToPath(new URL('../', import.meta.url))
const read = (path) => readFileSync(appRoot + path, 'utf-8').replace(/\r\n/g, '\n')

let failures = 0
function test(name, fn) {
  try {
    fn()
    console.log(`  ✓ ${name}`)
  } catch (error) {
    failures += 1
    console.error(`  ✗ ${name}\n    ${error.message}`)
  }
}

const SITE_ORIGIN = 'https://www.ellysia.es'
const composableOrigin = readSiteOrigin(appRoot)

const sitemapPaths = [...read('public/sitemap.xml').matchAll(/<loc>([^<]+)<\/loc>/g)].map(([, url]) => {
  assert.ok(url.startsWith(SITE_ORIGIN), `URL del sitemap fuera del dominio: ${url}`)
  return url.slice(SITE_ORIGIN.length)
})
const seoRoutes = readSeoRoutes(appRoot)

console.log('seo')

test('el sitemap y el composable usan el mismo dominio', () => {
  assert.equal(composableOrigin, SITE_ORIGIN)
  assert.match(read('public/robots.txt'), new RegExp(`^Sitemap: ${SITE_ORIGIN}/sitemap\\.xml$`, 'm'))
})

test('cada ruta con meta.seo está en el sitemap, y al revés', () => {
  assert.deepEqual([...seoRoutes.keys()].sort(), [...sitemapPaths].sort())
})

test('robots.txt no bloquea ninguna página del sitemap', () => {
  const disallowed = [...read('public/robots.txt').matchAll(/^Disallow: (\S+)$/gm)].map(([, path]) => path)
  const blocked = sitemapPaths.filter((path) => disallowed.some((rule) => path.startsWith(rule)))
  assert.deepEqual(blocked, [])
})

test('una vista provisional, sin contenido propio, no está en el sitemap ni declara meta.seo', () => {
  assert.ok(!sitemapPaths.includes('/docs/uso'), '/docs/uso es una vista provisional: no debe indexarse todavía')
  assert.ok(!seoRoutes.has('/docs/uso'))
})

for (const localeCode of ['es', 'en']) {
  const pages = JSON.parse(read(`src/i18n/locales/${localeCode}.json`)).seo.pages
  test(`${localeCode}: cada clave de meta.seo tiene título y descripción`, () => {
    const missing = [...seoRoutes.values()].filter((key) => !pages[key]?.title || !pages[key]?.description)
    assert.deepEqual(missing, [])
  })
  test(`${localeCode}: las descripciones caben en el resultado de búsqueda (≤ 170 caracteres)`, () => {
    const tooLong = Object.entries(pages).filter(([, page]) => page.description.length > 170).map(([key]) => key)
    assert.deepEqual(tooLong, [])
  })
}

console.log('imagen para compartir')

/**
 * Lee el ancho y el alto de un PNG de su cabecera.
 *
 * @param {string} path - Ruta del PNG relativa a `web/app`.
 * @returns {{width: number, height: number}} Dimensiones en píxeles.
 */
function pngSize(path) {
  const bytes = readFileSync(appRoot + path)
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) }
}

test('existe, mide 1200×630 y se anuncia con URL absoluta del dominio', () => {
  const html = read('index.html')
  const imageUrl = html.match(/<meta property="og:image" content="([^"]+)"/)?.[1]
  assert.ok(imageUrl, 'index.html no declara og:image')
  assert.ok(imageUrl.startsWith(`${SITE_ORIGIN}/`), `og:image tiene que ser absoluta y del dominio: ${imageUrl}`)
  const file = 'public' + imageUrl.slice(SITE_ORIGIN.length)
  assert.ok(existsSync(appRoot + file), `og:image apunta a un fichero que no existe: ${file}`)
  assert.deepEqual(pngSize(file), { width: 1200, height: 630 })
  assert.ok(html.includes('<meta property="og:image:width" content="1200" />'))
  assert.ok(html.includes('<meta property="og:image:height" content="630" />'))
  assert.match(html, /<meta property="og:image:alt" content="[^"]+" \/>/)
  assert.ok(html.includes(`<meta name="twitter:image" content="${imageUrl}" />`))
  assert.ok(html.includes('<meta name="twitter:card" content="summary_large_image" />'))
})

test('index.html trae el título y la descripción de la portada en español', () => {
  const landing = JSON.parse(read('src/i18n/locales/es.json')).seo.pages[seoRoutes.get('/')]
  const html = read('index.html')
  assert.ok(html.includes(`<title>${landing.title}</title>`))
  assert.ok(html.includes(`<meta name="description" content="${landing.description}" />`))
})

console.log('prerender')

const distDirectory = mkdtempSync(join(tmpdir(), 'ellysia-seo-'))
copyFileSync(appRoot + 'index.html', join(distDirectory, 'index.html'))
const prerendered = prerenderSeoPages({ distDirectory, appRoot })
const spanishPages = JSON.parse(read('src/i18n/locales/es.json')).seo.pages
const readPrerendered = (path) => readFileSync(prerenderedFilePath(distDirectory, path), 'utf-8')

test('hay una copia por cada ruta con meta.seo, salvo la portada', () => {
  assert.deepEqual(prerendered, [...seoRoutes.keys()].filter((path) => path !== '/'))
  for (const path of prerendered) assert.ok(existsSync(prerenderedFilePath(distDirectory, path)), `falta la copia de ${path}`)
})

test('cada copia lleva su título, su descripción, su canónica y su og:url', () => {
  for (const path of prerendered) {
    const page = spanishPages[seoRoutes.get(path)]
    const html = readPrerendered(path)
    assert.ok(html.includes(`<title>${page.title}</title>`), `título de ${path}`)
    assert.ok(html.includes(`<meta name="description" content="${page.description}" />`), `descripción de ${path}`)
    assert.ok(html.includes(`<meta property="og:title" content="${page.title}" />`), `og:title de ${path}`)
    assert.ok(html.includes(`<meta property="og:description" content="${page.description}" />`), `og:description de ${path}`)
    assert.ok(html.includes(`<link rel="canonical" href="${SITE_ORIGIN}${path}" />`), `canónica de ${path}`)
    assert.ok(html.includes(`<meta property="og:url" content="${SITE_ORIGIN}${path}" />`), `og:url de ${path}`)
    assert.equal(html.match(/<link rel="canonical"/g).length, 1, `${path} no puede tener dos canónicas`)
  }
})

test('cada copia sigue montando el SPA y no pone noindex (eso lo decide useSeo según el modo de lanzamiento)', () => {
  for (const path of prerendered) {
    const html = readPrerendered(path)
    assert.ok(html.includes('<div id="app"></div>'), `punto de montaje de ${path}`)
    assert.ok(html.includes('<script type="module"'), `script del SPA en ${path}`)
    assert.ok(!html.includes('name="robots"'), `${path} no debe llevar robots`)
  }
})

test('el <noscript> de cada copia y del index.html enlaza todas las páginas públicas', () => {
  const files = [readFileSync(join(distDirectory, 'index.html'), 'utf-8'), ...prerendered.map(readPrerendered)]
  for (const html of files) {
    const noscript = html.match(/<noscript>([\s\S]*?)<\/noscript>/)?.[1]
    assert.ok(noscript, 'falta el <noscript>')
    assert.match(noscript, /<h1>[^<]+<\/h1>/)
    for (const path of seoRoutes.keys()) assert.ok(noscript.includes(`<a href="${path}">`), `el <noscript> no enlaza ${path}`)
  }
})

test('el index.html prerenderizado no gana canónica: Caddy lo sirve para cualquier URL desconocida', () => {
  const html = readFileSync(join(distDirectory, 'index.html'), 'utf-8')
  assert.ok(!html.includes('rel="canonical"'))
  assert.ok(!html.includes('og:url'))
})

test('prerenderizar dos veces el mismo index.html falla en vez de duplicar el <noscript>', () => {
  assert.throws(() => prerenderSeoPages({ distDirectory, appRoot }), /noscript/)
})

test('el texto se escapa: comillas, ángulos y & no rompen el HTML', () => {
  const template = read('index.html')
  const html = renderSeoPage(template, {
    title: 'A "B" <script>&',
    description: 'Dice "hola" & <adiós>',
    canonicalUrl: `${SITE_ORIGIN}/x"y`,
    links: [{ path: '/a"b', title: '<c>' }],
  })
  assert.ok(html.includes('<title>A &quot;B&quot; &lt;script&gt;&amp;</title>'))
  assert.ok(html.includes('content="Dice &quot;hola&quot; &amp; &lt;adiós&gt;"'))
  assert.ok(html.includes('href="https://www.ellysia.es/x&quot;y"'))
  assert.ok(html.includes('<a href="/a&quot;b">&lt;c&gt;</a>'))
  assert.ok(!html.includes('<script>&'))
})

test('si index.html pierde una de las etiquetas que se sustituyen, falla en voz alta', () => {
  const withoutDescription = read('index.html').replace(/<meta name="description"[^>]*>/, '')
  assert.throws(
    () => renderSeoPage(withoutDescription, { title: 't', description: 'd', canonicalUrl: `${SITE_ORIGIN}/x`, links: [] }),
    /descripción/,
  )
})

rmSync(distDirectory, { recursive: true, force: true })

console.log('caddy')

const caddyfile = read('../Caddyfile')

test('las páginas prerenderizadas se sirven como <ruta>.html antes de caer al index.html', () => {
  assert.match(caddyfile, /\(spa\) \{[^}]*try_files \{path\} \{path\}\.html \/index\.html/)
})

test('todo lo que sale por el proxy hacia la API se marca como no indexable', () => {
  const snippet = caddyfile.match(/\(api_backend\) \{([\s\S]*?)\n\}/)?.[1]
  assert.ok(snippet, 'no se encuentra el fragmento api_backend')
  assert.match(snippet, /header X-Robots-Tag "noindex, nofollow"/)
  assert.ok(snippet.indexOf('X-Robots-Tag') < snippet.indexOf('reverse_proxy'))
})

test('los dos sitios que sirven la API usan ese fragmento', () => {
  assert.equal(caddyfile.match(/import api_backend/g).length, 2)
})

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
