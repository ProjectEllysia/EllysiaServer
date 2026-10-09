import { revealScrollDelta } from './motionMath'
import { prefersReducedMotion } from './useMotion'

/** Alto de la cabecera fija del sitio (`SiteHeader`), que tapa la parte de arriba de la ventana. */
const SITE_HEADER_HEIGHT = 72

/**
 * Lleva a la vista el principio de un elemento que acaba de aparecer o de cambiar,
 * solo si no se ve ya (ver `revealScrollDelta`): un resultado que sale debajo del
 * pliegue, el correo siguiente del quiz que queda por encima.
 *
 * Desplaza con suavidad, o de golpe si el usuario pide movimiento reducido. No mueve
 * el foco: de eso se encarga quien lo llama, si hace falta.
 *
 * @param {Element | null | undefined} element - Lo que hay que enseñar. Si no existe, no hace nada.
 */
export function revealResult(element) {
  if (!element || typeof window === 'undefined') return
  const delta = revealScrollDelta({
    targetTop: element.getBoundingClientRect().top,
    viewportHeight: window.innerHeight,
    headerHeight: SITE_HEADER_HEIGHT,
  })
  if (delta !== 0) window.scrollBy({ top: delta, behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
}
