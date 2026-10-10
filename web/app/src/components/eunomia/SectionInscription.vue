<template>
  <component :is="tag" class="inscription">
    <span class="inscription-mark" aria-hidden="true"></span>
    <span class="inscription-title"><slot /></span>
    <span class="inscription-rule" aria-hidden="true"></span>
    <span v-if="tally !== null" class="inscription-tally">{{ tally }}</span>
  </component>
</template>

<script setup>
/**
 * Rótulo de sección grabado: rombo, título en versalitas, filete que se desvanece y,
 * si se pide, un recuento. Es la misma inscripción que usan los paneles de Lybra.
 */
defineProps({
  /** Elemento HTML que lo pinta (`h2`, `h3`, `div`...). Por defecto `h2`. */
  tag: { type: String, default: 'h2' },
  /** Recuento que se muestra al final; `null` no pinta nada. */
  tally: { type: [Number, String], default: null },
})
</script>

<style scoped>
.inscription { display: flex; align-items: center; gap: 0.6rem; margin: 0; }
.inscription-mark { width: 8px; height: 8px; flex: none; transform: rotate(45deg); border: 1px solid var(--accent); background: var(--accent-dim); }
.inscription-title {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-md); font-weight: 600; letter-spacing: 0.24em; text-transform: uppercase;
  color: var(--accent);
}
.inscription-rule { flex: 1; min-width: 1.5rem; height: 1px; background: linear-gradient(to right, var(--accent), transparent); opacity: 0.45; }
.inscription-tally { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-sm); color: var(--text-dim); }
@media (max-width: 520px) { .inscription-title { letter-spacing: 0.16em; } }
</style>
