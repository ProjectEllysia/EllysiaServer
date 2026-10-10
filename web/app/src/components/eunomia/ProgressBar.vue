<template>
  <div class="progress" role="progressbar" :aria-valuenow="percent" aria-valuemin="0" aria-valuemax="100"
       :aria-label="label">
    <div class="bar" :style="{ width: `${percent}%` }"></div>
  </div>
</template>

<script setup>
/**
 * Barra de progreso de un conjunto de controles. Pinta el porcentaje que ya calcula el
 * servidor (sin los «no aplica»); no lo recalcula.
 */
defineProps({
  /** Porcentaje de 0 a 100. */
  percent: { type: Number, default: 0 },
  /** Texto alternativo para lectores de pantalla. */
  label: { type: String, default: '' },
})
</script>

<style scoped>
.progress { height: 0.5rem; border-radius: 999px; background: var(--border); overflow: hidden; }
.bar { height: 100%; background: var(--accent); border-radius: 999px; transition: width var(--transition); }
</style>
