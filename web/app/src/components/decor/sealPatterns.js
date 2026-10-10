/**
 * Patrón del sello de grabado de cada módulo (`EmblemSeal.vue`): cuántas ondas da cada
 * una de sus tres redes de guilloché en una vuelta. Cambiar un número cambia el dibujo
 * entero, así que cada módulo tiene el suyo, como una firma. Los números son enteros
 * para que cada curva se cierre sobre sí misma.
 *
 * - `outerLobes`: la red exterior, que gira en un sentido.
 * - `crossLobes`: la red que gira al revés sobre la anterior; al cruzarse, tiembla.
 * - `innerLobes`: la red interior, junto al emblema.
 */
export const SEAL_PATTERNS = Object.freeze({
  themis: Object.freeze({ outerLobes: 21, crossLobes: 26, innerLobes: 36 }),
  aegis: Object.freeze({ outerLobes: 18, crossLobes: 23, innerLobes: 32 }),
  iris: Object.freeze({ outerLobes: 24, crossLobes: 29, innerLobes: 40 }),
  acheron: Object.freeze({ outerLobes: 15, crossLobes: 19, innerLobes: 28 }),
  hygeia: Object.freeze({ outerLobes: 27, crossLobes: 31, innerLobes: 44 }),
  eunomia: Object.freeze({ outerLobes: 12, crossLobes: 17, innerLobes: 24 }),
})
