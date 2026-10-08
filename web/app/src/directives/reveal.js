import { prefersReducedMotion } from '@/composables/useMotion'

/** Cuánto del elemento tiene que verse para que aparezca. */
const VISIBLE_THRESHOLD = 0.15

let observer = null

/**
 * Observador compartido por todos los elementos con `v-reveal`: uno solo para toda la página.
 *
 * @returns {IntersectionObserver|null} El observador, o `null` si el navegador no lo tiene.
 */
function sharedObserver() {
  if (observer || typeof IntersectionObserver === 'undefined') return observer
  observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue
      entry.target.classList.add('is-in')
      observer.unobserve(entry.target)
    }
  }, { threshold: VISIBLE_THRESHOLD })
  return observer
}

/**
 * Directiva `v-reveal`: el elemento aparece (sube y se hace visible) cuando entra en pantalla.
 *
 * El valor es el retraso en milisegundos, para escalonar una serie
 * (`v-reveal="staggerDelay(index)"`). El estilo está en `assets/css/motion.css`
 * (`.reveal`, `.is-in`). Con movimiento reducido, o sin `IntersectionObserver`, el
 * elemento se ve desde el principio y no se anima.
 *
 * @type {import('vue').Directive<HTMLElement, number|undefined>}
 */
export const vReveal = {
  beforeMount(element, binding) {
    element.classList.add('reveal')
    if (binding.value) element.style.setProperty('--reveal-delay', `${binding.value}ms`)
  },
  mounted(element) {
    const watcher = prefersReducedMotion() ? null : sharedObserver()
    if (watcher) watcher.observe(element)
    else element.classList.add('is-in')
  },
  unmounted(element) {
    observer?.unobserve(element)
  },
}
