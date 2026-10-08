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
  opacity: 0.85;
  /* El color corre por detrás y la greca lo deja pasar: el brillo recorre el dibujo. */
  background: linear-gradient(90deg, var(--accent) 0%, var(--accent-bright) 25%, var(--accent) 50%, var(--accent-bright) 75%, var(--accent) 100%);
  background-size: 300% 100%;
  animation: gleam 18s linear infinite;
  --meander: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='24' height='16' viewBox='0 0 24 16'%3E%3Cpath d='M0 15H24M3 15V3H21V11H9V7H15' fill='none' stroke='black' stroke-width='1.6' stroke-linecap='square'/%3E%3C/svg%3E");
  -webkit-mask: var(--meander) repeat-x center / 24px 16px;
  mask: var(--meander) repeat-x center / 24px 16px;
}
@keyframes gleam { to { background-position: -300% 0; } }
@media (prefers-reduced-motion: reduce) { .frieze { animation: none; } }
</style>
