import { onBeforeUnmount, ref, toValue, watch } from 'vue'
import { countUpValue } from './motionMath'

/**
 * @returns {boolean} `true` si el sistema pide menos movimiento
 *   (`prefers-reduced-motion: reduce`). Fuera del navegador devuelve `true`, para que
 *   nada se anime donde no hay pantalla que lo enseñe.
 */
export function prefersReducedMotion() {
  if (typeof window === 'undefined' || !window.matchMedia) return true
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

/**
 * Número que sube (o baja) hasta su valor en vez de saltar.
 *
 * Al montarse arranca desde `from` y llega a la fuente; cada vez que la fuente cambia,
 * se desplaza desde lo que se enseñaba hasta el valor nuevo. Con movimiento reducido,
 * o si la fuente no es un número, enseña el valor sin animar.
 *
 * @param {number|import('vue').Ref<number>|(() => number)} source - Valor al que llegar.
 * @param {object} [options] - Opciones.
 * @param {number} [options.duration=700] - Milisegundos que dura cada desplazamiento.
 * @param {number} [options.decimals=0] - Decimales que se enseñan.
 * @param {number} [options.from=0] - Valor del que parte al montarse; `null` empieza ya en el valor final.
 * @returns {import('vue').Ref<number>} El número que se enseña ahora.
 */
export function useCountUp(source, { duration = 700, decimals = 0, from = 0 } = {}) {
  const target = () => toValue(source)
  const isNumber = (value) => typeof value === 'number' && Number.isFinite(value)
  const displayed = ref(isNumber(target()) && from !== null && !prefersReducedMotion() ? from : target())
  let frame = null

  /**
   * Anima `displayed` hasta un valor.
   *
   * @param {number} to - Valor de llegada.
   */
  function animateTo(to) {
    cancelAnimationFrame(frame)
    if (!isNumber(to) || !isNumber(displayed.value) || prefersReducedMotion()) {
      displayed.value = to
      return
    }
    const start = displayed.value
    const startedAt = performance.now()
    const step = (now) => {
      const progress = (now - startedAt) / duration
      displayed.value = countUpValue(start, to, progress, decimals)
      if (progress < 1) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
  }

  watch(target, animateTo, { immediate: true, flush: 'post' })
  onBeforeUnmount(() => cancelAnimationFrame(frame))
  return displayed
}
