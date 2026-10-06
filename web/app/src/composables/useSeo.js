import { watch } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useLaunch } from '@/composables/useLaunch'

/**
 * Origen público con el que se escriben las URL canónicas. Es el mismo que
 * declaran `public/sitemap.xml` y `public/robots.txt`: si el dominio cambia,
 * cambia en los tres sitios.
 */
export const SITE_ORIGIN = 'https://www.ellysia.es'

/**
 * Busca la etiqueta `<meta>` o `<link>` que casa con el selector y, si no
 * existe, la crea en el `<head>` con los atributos de identidad dados.
 *
 * @param {string} selector - Selector CSS de la etiqueta (`meta[name="robots"]`).
 * @param {string} tagName - `'meta'` o `'link'`.
 * @param {Record<string, string>} identity - Atributos que la identifican
 *   (`{ name: 'robots' }`, `{ rel: 'canonical' }`); se ponen al crearla.
 * @returns {HTMLElement} La etiqueta, ya presente en el documento.
 */
function ensureHeadTag(selector, tagName, identity) {
  let tag = document.head.querySelector(selector)
  if (!tag) {
    tag = document.createElement(tagName)
    for (const [attribute, value] of Object.entries(identity)) tag.setAttribute(attribute, value)
    document.head.appendChild(tag)
  }
  return tag
}

/**
 * Quita del `<head>` la etiqueta que casa con el selector, si la hay.
 *
 * @param {string} selector - Selector CSS de la etiqueta.
 */
function removeHeadTag(selector) {
  document.head.querySelector(selector)?.remove()
}

/**
 * Escribe en el `<head>` lo que los buscadores y las redes leen de la página
 * actual: título, descripción, URL canónica, Open Graph y la orden `robots`.
 *
 * @param {object} page - Lo que se quiere publicar de la página.
 * @param {string} page.title - Título del documento (y de `og:title`).
 * @param {string|null} page.description - Descripción para el resultado de
 *   búsqueda; `null` deja la de `index.html`.
 * @param {string|null} page.canonicalUrl - URL absoluta canónica; `null` quita
 *   la etiqueta canónica (páginas que no se indexan).
 * @param {boolean} page.isIndexable - `false` pone `noindex`; `true` quita la
 *   etiqueta `robots`.
 */
export function applyPageSeo({ title, description, canonicalUrl, isIndexable }) {
  document.title = title
  ensureHeadTag('meta[property="og:title"]', 'meta', { property: 'og:title' }).setAttribute('content', title)
  if (description) {
    ensureHeadTag('meta[name="description"]', 'meta', { name: 'description' }).setAttribute('content', description)
    ensureHeadTag('meta[property="og:description"]', 'meta', { property: 'og:description' }).setAttribute('content', description)
  }
  if (canonicalUrl) {
    ensureHeadTag('link[rel="canonical"]', 'link', { rel: 'canonical' }).setAttribute('href', canonicalUrl)
    ensureHeadTag('meta[property="og:url"]', 'meta', { property: 'og:url' }).setAttribute('content', canonicalUrl)
  } else {
    removeHeadTag('link[rel="canonical"]')
    removeHeadTag('meta[property="og:url"]')
  }
  if (isIndexable) {
    removeHeadTag('meta[name="robots"]')
  } else {
    ensureHeadTag('meta[name="robots"]', 'meta', { name: 'robots' }).setAttribute('content', 'noindex')
  }
}

/**
 * Mantiene el `<head>` al día con la ruta, el idioma y el modo de lanzamiento.
 *
 * Una ruta es indexable solo si declara `meta.seo` (la clave de sus textos en
 * `seo.pages.<clave>` del diccionario) y Ellysia está abierta al público. El
 * resto —vistas con sesión, aterrizajes de enlaces con token, la vista de
 * error— lleva `noindex` siempre: el servidor responde 200 con el mismo
 * `index.html` a cualquier URL, así que esta etiqueta es lo único que impide
 * que una dirección inexistente se indexe como página.
 *
 * Mientras Ellysia está en vista previa todo lleva `noindex`, porque sus
 * textos legales todavía no son definitivos. Hasta tener la respuesta del
 * servidor cuenta como vista previa, así que la etiqueta está desde el primer
 * momento. Caddy no conoce el modo, por eso lo decide la aplicación.
 *
 * Se llama una sola vez, desde `App.vue`.
 */
export function useSeo() {
  const route = useRoute()
  const { t, locale } = useI18n()
  const { isPreview } = useLaunch()

  watch(
    () => [route.path, route.meta.seo, locale.value, isPreview.value],
    ([path, seoKey, , isInPreview]) => {
      const hasPublicPage = Boolean(seoKey)
      applyPageSeo({
        title: hasPublicPage ? t(`seo.pages.${seoKey}.title`) : t('seo.siteName'),
        description: hasPublicPage ? t(`seo.pages.${seoKey}.description`) : null,
        canonicalUrl: hasPublicPage ? SITE_ORIGIN + path : null,
        isIndexable: hasPublicPage && !isInPreview,
      })
    },
    { immediate: true },
  )
}
