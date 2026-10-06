/**
 * Tests de lo que se publica para los buscadores: `public/sitemap.xml`,
 * `public/robots.txt`, las rutas con `meta.seo` y sus textos en `seo.pages`.
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
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const appRoot = fileURLToPath(new URL('../', import.meta.url))
const read = (path) => readFileSync(appRoot + path, 'utf-8')

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
const composableOrigin = read('src/composables/useSeo.js').match(/SITE_ORIGIN = '([^']+)'/)[1]

/**
 * Las rutas del router que declaran `meta.seo`, con su clave.
 *
 * @returns {Map<string, string>} Ruta (`/themis`) → clave (`themis`).
 */
function routesWithSeo() {
  const source = read('src/router/index.js')
  const routes = new Map()
  for (const block of source.split(/\n  \{\n/)) {
    const path = block.match(/^\s*path: '([^']+)'/m)?.[1]
    const seoKey = block.match(/seo: '([^']+)'/)?.[1]
    if (path && seoKey) routes.set(path, seoKey)
  }
  assert.ok(routes.size > 0, 'no se encuentra ninguna ruta con meta.seo: ¿ha cambiado el formato del router?')
  return routes
}

const sitemapPaths = [...read('public/sitemap.xml').matchAll(/<loc>([^<]+)<\/loc>/g)].map(([, url]) => {
  assert.ok(url.startsWith(SITE_ORIGIN), `URL del sitemap fuera del dominio: ${url}`)
  return url.slice(SITE_ORIGIN.length)
})
const seoRoutes = routesWithSeo()

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

if (failures) {
  console.error(`\n${failures} test(s) fallidos`)
  process.exit(1)
}
