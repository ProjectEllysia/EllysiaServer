/**
 * Formato en línea de los textos de la documentación.
 *
 * Los textos viven en JSON y se pintan como nodos de Vue, nunca con
 * `v-html`: así un texto no puede inyectar marcado, y el formato se limita a
 * las dos marcas que de verdad hacen falta en una explicación técnica:
 *
 * - `**negrita**` para el término que se está definiendo;
 * - `` `código` `` para nombres que se escriben tal cual (un endpoint, una
 *   clave de configuración, un estado).
 *
 * Módulo puro, sin Vue, para poder probarlo con node a secas.
 */

/** Una marca completa: negrita o código, sin anidar. */
const INLINE_MARK_RE = /(\*\*[^*]+\*\*|`[^`]+`)/

/**
 * Parte un texto en tramos de texto llano, negrita y código.
 *
 * Una marca sin cerrar no es una marca: el texto se queda tal cual, con su
 * asterisco o su acento grave, en vez de tragarse el resto del párrafo.
 *
 * @param {string} text - Texto con las marcas `**…**` y `` `…` ``.
 * @returns {Array<{ kind: 'text'|'strong'|'code', value: string }>} Los
 *   tramos en orden; los vacíos se omiten.
 */
export function parseInlineText(text) {
  return text
    .split(INLINE_MARK_RE)
    .filter((piece) => piece !== '')
    .map((piece) => {
      if (piece.startsWith('**') && piece.endsWith('**') && piece.length > 4) {
        return { kind: 'strong', value: piece.slice(2, -2) }
      }
      if (piece.startsWith('`') && piece.endsWith('`') && piece.length > 2) {
        return { kind: 'code', value: piece.slice(1, -1) }
      }
      return { kind: 'text', value: piece }
    })
}
