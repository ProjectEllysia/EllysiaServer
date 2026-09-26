<template>
  <!-- Silueta del registro de hallazgos: inscripción, balanza y filas de
       grupo con su insignia, su nombre y su recuento. Ocupa el sitio del
       registro real, así que al llegar los datos no hay salto. El estado se
       anuncia con aria-busy y `label`, no repitiendo la silueta, que va
       marcada como decorativa (misma convención que `.skeleton` de shared.css). -->
  <div class="findings-skeleton" aria-busy="true" role="status" :aria-label="label || t('lybra.toolbar.loadingFindings')">
    <div class="ghost-inscription" aria-hidden="true">
      <span class="ghost-mark"></span>
      <span class="skeleton skeleton--line ghost-title"></span>
      <span class="ghost-rule"></span>
    </div>
    <span class="skeleton ghost-balance" aria-hidden="true"></span>
    <div class="ghost-ledger" aria-hidden="true">
      <div v-for="row in rows" :key="row" class="ghost-group">
        <span class="skeleton ghost-prio"></span>
        <span class="skeleton skeleton--line" :class="WIDTHS[row % WIDTHS.length]"></span>
        <span class="skeleton skeleton--line ghost-count"></span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
defineProps({
  /** Qué se está esperando, para quien usa lector de pantalla. Por defecto,
   *  «Cargando hallazgos» en el idioma activo. */
  label: { type: String, default: '' },
  /** Filas de grupo fantasma. Por defecto `4`, las que caben sin alargar el panel. */
  rows: { type: Number, default: 4 },
})

/** Anchos alternos, para que las filas no queden iguales y se lean como silueta. */
const WIDTHS = ['skeleton--w40', 'skeleton--w60', 'skeleton--w40', 'skeleton--w80']
</script>

<style scoped>
.ghost-inscription { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.45rem; }
.ghost-mark { width: 8px; height: 8px; flex: none; transform: rotate(45deg); border: 1px solid var(--border-solid); }
.ghost-title { width: 11rem; }
.ghost-rule { flex: 1; height: 1px; background: linear-gradient(to right, var(--border-solid), transparent); }
.ghost-balance { height: 3px; margin-bottom: 0.65rem; border-radius: 2px; }
.ghost-ledger { border: 1px solid var(--border-med); border-radius: 10px; background: var(--surface); overflow: hidden; }
/* Mismo relleno que `.group` de LybraResults.vue, para que la silueta tenga su alto. */
.ghost-group { display: flex; align-items: center; gap: 0.6rem; padding: 0.75rem 0.9rem 0.75rem 1.15rem; }
.ghost-group + .ghost-group { border-top: 1px solid var(--border-med); }
.ghost-group .skeleton--line { flex: none; }
.ghost-prio { width: 4.4em; height: 1.3em; flex: none; border-radius: 5px; }
.ghost-count { width: 5rem; margin-left: auto; }
</style>
