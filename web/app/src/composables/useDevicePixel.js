import { onBeforeUnmount, onMounted, ref } from 'vue'
import { devicePixelInUnits } from './motionMath'

/**
 * Mide cuánto ocupa un píxel físico de la pantalla en las unidades de un dibujo SVG,
 * para que sus trazos más finos nunca queden por debajo de un píxel real.
 *
 * Un dibujo escalado pinta sus líneas en unidades propias: una línea de 0,6 unidades
 * mide 0,3 píxeles si el dibujo sale a la mitad, y en una pantalla sin retina se ve
 * gris y borrosa. Con esta medida, el CSS del dibujo puede pedir
 * `max(<grosor>px, calc(var(--device-pixel) * 1px))`. Se recalcula al cambiar el
 * tamaño del elemento o el zoom del navegador.
 *
 * @param {import('vue').Ref<Element | null>} target - Elemento cuyo tamaño se observa.
 * @param {(box: DOMRectReadOnly) => number} scaleOf - Escala a la que se pinta el dibujo
 *   (píxeles CSS por unidad) según el tamaño del elemento.
 * @returns {{devicePixel: import('vue').Ref<number>, scale: import('vue').Ref<number>}}
 *   `devicePixel`: unidades del dibujo por píxel físico, `0` mientras no se ha medido
 *   (en ese caso manda el grosor de diseño). `scale`: píxeles CSS por unidad, `0`
 *   mientras no se ha medido; sirve para saber si el dibujo sale tan pequeño que su
 *   texto no se leería, sea cual sea la densidad de la pantalla.
 */
export function useDevicePixel(target, scaleOf) {
  const devicePixel = ref(0)
  const scale = ref(0)
  let observer = null

  const measure = (box) => {
    const ratio = typeof window === 'undefined' ? 1 : window.devicePixelRatio || 1
    scale.value = scaleOf(box)
    devicePixel.value = devicePixelInUnits(scale.value, ratio)
  }

  onMounted(() => {
    if (!target.value) return
    // Primera medida en el acto: el observador no avisa hasta el siguiente fotograma, y
    // en una pestaña en segundo plano puede tardar.
    measure(target.value.getBoundingClientRect())
    if (typeof ResizeObserver === 'undefined') return
    observer = new ResizeObserver(([entry]) => measure(entry.contentRect))
    observer.observe(target.value)
  })
  onBeforeUnmount(() => observer?.disconnect())

  return { devicePixel, scale }
}
