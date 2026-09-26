<template>
  <div class="agents-wrap">
    <!-- ── Tarjetas de agentes ── -->
    <div class="agents-head">
      <span class="agents-title">{{ t('lybra.agents.title') }}</span>
      <button class="btn-refresh" :disabled="assetsLoading" @click="$emit('refresh-assets')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ spin: assetsLoading }"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        {{ t('themis.refresh') }}
      </button>
    </div>

    <div v-if="assetsLoading && !assets.length" class="empty-state">
      <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="spin"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg>
      <span>{{ t('lybra.agents.loading') }}</span>
    </div>

    <div v-else-if="!assets.length" class="empty-state">
      <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
      <span>{{ t('lybra.agents.empty') }}</span>
    </div>

    <!-- Entrada escalonada: cada tarjeta aparece con un pequeño retardo
         creciente por posición (mismo patrón --enter-delay que .finding-item
         de LybraResults.vue), en vez de que toda la rejilla salte de golpe. -->
    <TransitionGroup v-else tag="div" name="agent-card" class="agent-grid">
      <button
        v-for="(asset, idx) in assets" :key="asset.id"
        type="button" class="agent-card" :class="{ active: selectedAssetId === asset.id }"
        :style="{ '--enter-delay': (idx % 24) * 25 + 'ms' }"
        @click="$emit('select', selectedAssetId === asset.id ? null : asset.id)"
      >
        <span class="agent-top">
          <span class="agent-status" :class="asset.status" :title="statusLabel(asset)"></span>
          <span class="agent-host" :title="asset.hostname">{{ asset.hostname }}</span>
        </span>
        <span class="agent-meta">
          <span v-if="asset.os" class="agent-os">{{ asset.os }}</span>
          <span class="agent-state-label">{{ statusLabel(asset) }}</span>
        </span>
        <span class="agent-findings">
          <span v-if="countFor(asset) === null" class="agent-pill muted">{{ t('lybra.agents.notAnalyzed') }}</span>
          <span v-else-if="countFor(asset) === 0" class="agent-pill clean">{{ t('lybra.results.noFindings') }}</span>
          <span v-else class="agent-pill vulnerable">
            {{ t('lybra.results.findingCount', { count: countFor(asset) }, countFor(asset)) }}
          </span>
        </span>
      </button>
    </TransitionGroup>

    <!-- ── Escaneos del agente seleccionado ── -->
    <Transition name="fade-swap">
    <div v-if="selectedAssetId" key="scans" class="agent-scans">
      <div class="agent-scans-head">
        <span class="agent-scans-title">
          <i18n-t keypath="lybra.agents.analysesOf" tag="span">
            <template #host><strong>{{ selectedAsset?.hostname || t('lybra.agents.assetFallback', { id: selectedAssetId }) }}</strong></template>
          </i18n-t>
        </span>
        <span class="agent-scans-note">{{ t('lybra.agents.note') }}</span>
      </div>

      <!-- Se reutiliza LybraResults tal cual: un escaneo de agente es un
           escaneo Lybra normal y corriente, solo cambia de dónde salió la
           lista de servicios. Duplicar el componente sería duplicar el
           acordeón, los hallazgos y toda la gestión de PDFs por nada. -->
      <LybraResults
        :scans="scans"
        :loading="loading"
        :total-count="totalCount"
        :current-page="currentPage"
        :per-page="perPage"
        :selected-ids="selectedIds"
        :docs-by-scan="docsByScan"
        :groups-by-scan="groupsByScan"
        @refresh="$emit('refresh-scans')"
        @page-change="page => $emit('page-change', page)"
        @toggle-select="id => $emit('toggle-select', id)"
        @select-all="ids => $emit('select-all', ids)"
        @bulk-delete="$emit('bulk-delete')"
        @load-groups="id => $emit('load-groups', id)"
        @set-finding-state="(...a) => $emit('set-finding-state', ...a)"
        @delete="id => $emit('delete', id)"
        @load-docs="id => $emit('load-docs', id)"
        @generate-pdf="(id, ai) => $emit('generate-pdf', id, ai)"
        @download-doc="id => $emit('download-doc', id)"
        @delete-doc="(scanId, docId) => $emit('delete-doc', scanId, docId)"
      />
    </div>

    <p v-else-if="assets.length" key="hint" class="pick-hint">{{ t('lybra.agents.pick') }}</p>
    </Transition>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import LybraResults from '@/components/themis/lybra/LybraResults.vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  assets: { type: Array, default: () => [] },
  assetsLoading: { type: Boolean, default: false },
  selectedAssetId: { type: Number, default: null },
  scans: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  totalCount: { type: Number, default: 0 },
  currentPage: { type: Number, default: 1 },
  perPage: { type: Number, default: 10 },
  selectedIds: { type: Array, default: () => [] },
  docsByScan: { type: Object, default: () => ({}) },
  groupsByScan: { type: Object, default: () => ({}) },
})
defineEmits([
  'select', 'refresh-assets', 'refresh-scans', 'page-change', 'toggle-select', 'select-all', 'bulk-delete',
  'delete', 'load-docs', 'load-groups', 'set-finding-state', 'generate-pdf', 'download-doc', 'delete-doc',
])

/** Estados de un activo con rótulo en `assetStatus`. */
const ASSET_STATUSES = ['pending', 'online', 'stale', 'offline']

/**
 * Texto del estado de un activo. Un activo no persistente está "caído" por
 * diseño — se apaga a propósito, así que no es un fallo del agente de
 * Hygeia sino el comportamiento esperado, y eso es lo que el texto dice.
 */
function statusLabel(asset) {
  if (asset.status === 'offline' && asset.isPersistent === false) return t('assetStatus.poweredOff')
  return ASSET_STATUSES.includes(asset.status) ? t(`assetStatus.${asset.status}`) : t('common.unknown')
}

const selectedAsset = computed(() =>
  props.assets.find(a => a.id === props.selectedAssetId) || null
)

/**
 * Hallazgos del último análisis de un activo, o `null` si nunca se analizó.
 *
 * La rejilla entera lo sabe sin N peticiones por render: `GET /hygeia/assets`
 * enriquece cada activo con su `totalFindings` (una query agrupada en el
 * backend, no una por tarjeta). La tarjeta abierta manda además con los
 * escaneos en vivo mientras están cargados: eso mantiene el contador al día
 * al terminar un análisis sin esperar al refresco de la lista de activos.
 */
function countFor(asset) {
  if (asset.id === props.selectedAssetId && props.scans.length) {
    return props.scans[0].totalFindings ?? 0
  }
  return asset.totalFindings ?? null
}
</script>

<style scoped>
.agents-wrap { display: flex; flex-direction: column; gap: 1rem; }

.agents-head { display: flex; align-items: center; justify-content: space-between; }
.agents-title { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-weight: 600; font-size: var(--fs-xl); color: var(--text); }
.btn-refresh { display: flex; align-items: center; gap: 0.35rem; padding: 0.35rem 0.7rem; background: var(--surface-2); border: 1px solid var(--border-solid); border-radius: 6px; color: var(--text-dim); font-size: var(--fs-md); cursor: pointer; transition: all 0.2s; }
.btn-refresh:hover:not(:disabled) { border-color: var(--accent); color: var(--text); }
.btn-refresh:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-refresh svg { width: 12px; height: 12px; }
.spin { animation: seq-spin 0.8s linear infinite; }

.empty-state { display: flex; flex-direction: column; align-items: center; gap: 0.6rem; padding: 2.5rem 1rem; color: var(--text-muted); font-size: var(--fs-lg); text-align: center; background: var(--surface); border: 1px solid var(--border); border-radius: 10px; }
.empty-state span { max-width: 42ch; line-height: 1.5; }
.empty-state svg { color: var(--text-muted); opacity: 0.7; }

/* ── Rejilla de agentes ── */
.agent-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 0.6rem; }
.agent-card-enter-active {
  transition: opacity 0.3s ease var(--enter-delay, 0ms), transform 0.3s ease var(--enter-delay, 0ms);
}
.agent-card-enter-from { opacity: 0; transform: translateY(8px); }
.agent-card-move { transition: transform 0.2s ease; }

.fade-swap-enter-active, .fade-swap-leave-active { transition: opacity 0.2s ease; }
.fade-swap-enter-from, .fade-swap-leave-to { opacity: 0; }
.agent-card {
  display: flex; flex-direction: column; gap: 0.45rem; text-align: left;
  padding: 0.7rem 0.8rem; cursor: pointer;
  background: var(--surface); border: 1px solid var(--border); border-radius: 9px;
  transition: border-color 0.15s, background 0.15s, transform 0.15s;
}
.agent-card:hover { border-color: var(--accent); }
.agent-card.active { border-color: var(--accent); background: var(--surface-2); }
.agent-top { display: flex; align-items: center; gap: 0.4rem; min-width: 0; }
.agent-status { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; background: var(--text-muted); }
.agent-status.online { background: var(--success); }
.agent-status.stale { background: var(--warn); }
.agent-status.offline { background: var(--danger); }
.agent-host { font-size: var(--fs-lg); font-weight: 600; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.agent-meta { display: flex; align-items: center; gap: 0.35rem; font-size: var(--fs-sm); color: var(--text-muted); }
.agent-os { text-transform: capitalize; font-size: var(--fs-md);}
.agent-state-label {font-size: var(--fs-md);}
.agent-state-label::before { content: '·'; margin-right: 0.35rem; }
.agent-findings { display: flex; }
.agent-pill { font-size: var(--fs-sm); font-weight: 600; padding: 0.1rem 0.45rem; border-radius: 5px; }
.agent-pill.muted { color: var(--text-muted); background: var(--surface-2); }
.agent-pill.clean { color: var(--success); background: var(--success-dim); }
.agent-pill.vulnerable { color: var(--danger); background: var(--danger-dim); }

/* ── Escaneos del agente ── */
.agent-scans { display: flex; flex-direction: column; gap: 0.5rem; }
.agent-scans-head { display: flex; align-items: baseline; gap: 0.6rem; flex-wrap: wrap; }
.agent-scans-title { font-size: var(--fs-lg); color: var(--text-dim); }
.agent-scans-title strong { color: var(--text); }
.agent-scans-note { font-size: var(--fs-sm); color: var(--text-muted); margin-left: auto; }

.pick-hint { margin: 0; padding: 1.2rem; text-align: center; font-size: var(--fs-md); color: var(--text-muted); background: var(--surface); border: 1px dashed var(--border-solid); border-radius: 10px; }

@media (prefers-reduced-motion: reduce) {
  .spin { animation: none !important; }
  .agent-card-enter-active, .agent-card-move,
  .fade-swap-enter-active, .fade-swap-leave-active { transition: none !important; }
}
</style>
