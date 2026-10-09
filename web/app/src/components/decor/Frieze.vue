<template>
  <div class="frieze" aria-hidden="true"></div>
</template>

<script setup>
/**
 * Friso de greca: la banda de meandros con que los templos griegos rematan un
 * muro, aquí con el color del módulo y un brillo que la recorre despacio. Separa
 * la cabecera del resto de la página en el hub y en las herramientas gratuitas.
 * Toma el acento del módulo en que se coloque (`data-module`).
 */
</script>

<style scoped>
.frieze {
  position: relative;
  z-index: 1;
  height: 16px;
  width: 100%;
  overflow: hidden;
  opacity: 0.85;
  background: var(--accent);
  --meander: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='16' viewBox='0 0 24 16'%3E%3Cpath d='M0 15H24M3 15V3H21V11H9V7H15' fill='none' stroke='black' stroke-width='1.6' stroke-linecap='square'/%3E%3C/svg%3E");
  -webkit-mask: var(--meander) repeat-x center / 24px 16px;
  mask: var(--meander) repeat-x center / 24px 16px;
}
/* El brillo es una capa que se desliza por detrás y la greca lo deja pasar. Se mueve
   con un desplazamiento, que hace la tarjeta gráfica, en vez de animar la posición del
   fondo, que obligaría a repintar la banda en cada fotograma. El degradado se repite
   cada medio ancho de la capa, así que el bucle no tiene salto. */
.frieze::before {
  content: '';
  position: absolute;
  inset: 0 auto 0 0;
  width: 300%;
  background: linear-gradient(90deg, transparent 0%, var(--accent-bright) 25%, transparent 50%, var(--accent-bright) 75%, transparent 100%);
  animation: gleam 18s linear infinite;
}
@keyframes gleam { from { transform: translateX(0); } to { transform: translateX(-50%); } }
@media (prefers-reduced-motion: reduce) { .frieze::before { animation: none; } }
</style>
