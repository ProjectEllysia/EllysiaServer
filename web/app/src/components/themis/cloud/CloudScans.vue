<template>
  <div class="cloud-scans">
    <div class="list-head">
      <span class="list-title">{{ t('lybra.cloud.listTitle') }}</span>
      <button class="btn-refresh" :disabled="loading" @click="$emit('refresh')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" :class="{ spin: loading }"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        {{ t('themis.refresh') }}
      </button>
    </div>

    <p v-if="error" class="note error">{{ error }}</p>
    <div v-else-if="loading && !scans.length" class="skeleton-list" role="status" aria-busy="true" :aria-label="t('common.loading')">
      <span v-for="n in 3" :key="n" class="skeleton skeleton--block" :style="{ '--enter-delay': (n - 1) * 90 + 'ms' }"></span>
    </div>
    <div v-else-if="!scans.length" class="empty">
      <svg class="empty-cloud" width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" aria-hidden="true"><path d="M17.5 19a4.5 4.5 0 1 0-1.4-8.78A6 6 0 0 0 4.5 12.5 3.5 3.5 0 0 0 6 19z"/></svg>
      <span>{{ t('lybra.cloud.empty') }}</span>
    </div>

    <div v-else class="layout">
      <ul class="scan-list" role="listbox" :aria-label="t('lybra.cloud.listTitle')">
        <li v-for="(scan, index) in scans" :key="scan.osintScanId" class="scan-item" :style="{ '--enter-delay': Math.min(index, 12) * 45 + 'ms' }">
          <button type="button" class="scan-row" role="option" :aria-selected="scan.osintScanId === selectedId"
            :class="{ selected: scan.osintScanId === selectedId, updated: updatedIds.has(scan.osintScanId) }" @click="$emit('select', scan.osintScanId)">
            <span class="row-domain">{{ scan.domain }}</span>
            <span class="row-meta">
              <StatusBadge :status="scan.status" />
              <span v-if="scan.status === 'finished'" class="row-count" :class="{ open: scan.findingCount > 0 }">
                {{ scan.findingCount ? t('lybra.cloud.exposedCount', { count: scan.findingCount }, scan.findingCount) : t('lybra.cloud.nothingExposed') }}
              </span>
              <span class="row-date">{{ fmtDate(scan.finishedAt || scan.startedAt) }}</span>
            </span>
          </button>
        </li>
      </ul>

      <section class="detail" aria-live="polite">
        <p v-if="!selectedId" class="note">{{ t('lybra.cloud.pick') }}</p>
        <p v-else-if="detailError" class="note error">{{ detailError }}</p>
        <p v-else-if="!detail" class="note">{{ t('common.loading') }}</p>
        <div v-else :key="detail.osintScanId" class="detail-pane">
          <header class="detail-head">
            <h3 class="detail-domain">{{ detail.domain }}</h3>
            <StatusBadge :status="detail.status" />
          </header>

          <div v-if="detail.status === 'pending' || detail.status === 'running'" class="state-panel">
            <p class="state-title">{{ detail.status === 'pending' ? t('lybra.results.queued') : t('lybra.cloud.checking') }}</p>
            <div class="state-progress" aria-hidden="true"><span></span></div>
          </div>
          <div v-else-if="detail.status === 'failed'" class="state-panel failed">
            <p class="state-title">{{ t('lybra.cloud.failed') }}</p>
          </div>

          <template v-else>
            <!-- Cada recurso declarado recibe su veredicto, también los que
                 salieron bien: lo que se quiere saber es qué pasó con cada uno,
                 no solo con los abiertos. -->
            <section class="ledger" style="--enter-delay: 60ms">
              <header class="inscription">
                <span class="inscription-mark" aria-hidden="true"></span>
                <h4 class="inscription-title">{{ t('lybra.cloud.declared') }}</h4>
                <span class="inscription-rule" aria-hidden="true"></span>
                <span class="inscription-tally">{{ verdicts.resources.length }}</span>
              </header>
              <p v-if="!verdicts.resources.length" class="note">{{ t('lybra.cloud.noneDeclared') }}</p>
              <ul v-else class="verdicts">
                <li v-for="(entry, index) in verdicts.resources" :key="entry.subject" class="verdict" :class="entry.finding ? 'open' : 'closed'" :style="{ '--enter-delay': 120 + index * 60 + 'ms' }">
                  <span class="verdict-provider">{{ t(`lybra.cloud.providers.${cloudProviderKey(entry.subject)}`) }}</span>
                  <span class="verdict-subject mono">{{ entry.subject }}</span>
                  <span class="verdict-seal">{{ entry.finding ? t('lybra.cloud.open') : t('lybra.cloud.closed') }}</span>
                  <p v-if="entry.finding" class="verdict-detail">{{ entry.finding.title }}</p>
                </li>
              </ul>
            </section>

            <section class="ledger" style="--enter-delay: 160ms">
              <header class="inscription">
                <span class="inscription-mark" aria-hidden="true"></span>
                <h4 class="inscription-title">{{ t('lybra.cloud.subdomains') }}</h4>
                <span class="inscription-rule" aria-hidden="true"></span>
                <span v-if="detail.checkSubdomains" class="inscription-tally">{{ t('lybra.cloud.knownSubdomains', { count: detail.subdomainCount }, detail.subdomainCount) }}</span>
              </header>
              <p v-if="!detail.checkSubdomains" class="note">{{ t('lybra.cloud.subdomainsSkipped') }}</p>
              <p v-else-if="!verdicts.subdomains.length" class="note clean">{{ t('lybra.cloud.noTakeover') }}</p>
              <ul v-else class="verdicts">
                <li v-for="(finding, index) in verdicts.subdomains" :key="finding.dedupKey || finding.service" class="verdict open" :style="{ '--enter-delay': 220 + index * 60 + 'ms' }">
                  <span class="verdict-provider">{{ t('lybra.cloud.takeover') }}</span>
                  <span class="verdict-subject mono">{{ finding.service }}</span>
                  <span class="verdict-seal">{{ t('lybra.cloud.claimable') }}</span>
                  <p class="verdict-detail">{{ finding.title }}</p>
                </li>
              </ul>
            </section>

            <!-- Informes: se generan en segundo plano como los de un escaneo. -->
            <section class="ledger" style="--enter-delay: 260ms">
              <header class="inscription">
                <span class="inscription-mark" aria-hidden="true"></span>
                <h4 class="inscription-title">{{ t('themis.documents.title') }}</h4>
                <span class="inscription-rule" aria-hidden="true"></span>
                <span class="inscription-tally">{{ docs.length }}</span>
              </header>
              <p v-if="docsLoading && !docs.length" class="note">{{ t('themis.documents.loading') }}</p>
              <p v-else-if="!docs.length" class="note">{{ t('themis.documents.empty') }}</p>
              <TransitionGroup v-else tag="ul" name="doc-item" class="docs">
                <li v-for="doc in docs" :key="doc.documentId" class="doc">
                  <span class="doc-name">{{ t('lybra.cloud.pdfName') }}</span>
                  <span v-if="doc.createdAt" class="doc-date">{{ fmtDate(doc.createdAt) }}</span>
                  <span class="doc-right">
                    <template v-if="doc.status === 'done'">
                      <button class="doc-btn" :title="t('themis.documents.download')" :aria-label="t('themis.documents.download')" @click="$emit('download-doc', doc.documentId)">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                      </button>
                      <button class="doc-btn danger" :title="t('common.delete')" :aria-label="t('common.delete')" @click="$emit('delete-doc', doc.documentId)">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
                      </button>
                    </template>
                    <span v-else-if="doc.status === 'error'" class="doc-status error">{{ t('themis.documents.error') }}</span>
                    <span v-else class="doc-status running">{{ t('themis.documents.running') }}</span>
                  </span>
                </li>
              </TransitionGroup>
              <button class="btn-report" :disabled="generating" @click="$emit('generate-report', detail.osintScanId)">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
                {{ t('themis.documents.generatePdf') }}
              </button>
            </section>
          </template>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import StatusBadge from '@/components/themis/StatusBadge.vue'
import { formatDateTime } from '@/i18n/format'
import { cloudProviderKey, cloudVerdicts } from '../lybra/beyondHost'

const { t } = useI18n()

const props = defineProps({
  scans: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  error: { type: String, default: null },
  selectedId: { type: Number, default: null },
  /** Detalle del escaneo abierto, de `GET /themis/osint/<id>`. */
  detail: { type: Object, default: null },
  detailError: { type: String, default: null },
  docs: { type: Array, default: () => [] },
  docsLoading: { type: Boolean, default: false },
  generating: { type: Boolean, default: false },
})
defineEmits(['refresh', 'select', 'generate-report', 'download-doc', 'delete-doc'])

const verdicts = computed(() => cloudVerdicts(props.detail))

/** Cuánto dura el destello de una fila cuyo estado acaba de cambiar. */
const UPDATED_FLASH_MS = 1800

/** Ids de los análisis cuyo estado cambió hace un momento (para iluminar su fila). */
const updatedIds = ref(new Set())
const flashTimers = new Set()

/**
 * Ilumina un instante la fila de cada análisis cuyo estado cambió respecto a la
 * lista anterior (por ejemplo, de «en marcha» a «terminado»). La primera carga
 * no destella: solo cuentan los cambios sobre una lista ya mostrada.
 */
watch(() => props.scans, (next, previous) => {
  if (!previous?.length) return
  const previousStatus = new Map(previous.map(scan => [scan.osintScanId, scan.status]))
  const changed = next.filter(scan => previousStatus.has(scan.osintScanId) && previousStatus.get(scan.osintScanId) !== scan.status)
  if (!changed.length) return
  updatedIds.value = new Set([...updatedIds.value, ...changed.map(scan => scan.osintScanId)])
  const timer = setTimeout(() => {
    flashTimers.delete(timer)
    const remaining = new Set(updatedIds.value)
    changed.forEach(scan => remaining.delete(scan.osintScanId))
    updatedIds.value = remaining
  }, UPDATED_FLASH_MS)
  flashTimers.add(timer)
})

onBeforeUnmount(() => flashTimers.forEach(clearTimeout))

function fmtDate(iso) {
  if (!iso) return '—'
  try { return formatDateTime(iso, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) }
  catch { return iso }
}
</script>

<style scoped>
.mono { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); }
.cloud-scans { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1rem 1.1rem 1.2rem; }
.list-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.8rem; }
.list-title { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-lg); font-weight: 600; color: var(--text); }
.btn-refresh {
  display: inline-flex; align-items: center; gap: 0.35rem; padding: 0.35rem 0.7rem;
  background: var(--surface-2); border: 1px solid var(--border); border-radius: 7px; color: var(--text-dim);
  font-size: var(--fs-md); cursor: pointer;
}
.btn-refresh { transition: border-color 0.2s ease, color 0.2s ease, transform 0.12s ease; }
.btn-refresh:hover:not(:disabled) { border-color: var(--accent); color: var(--text); }
.btn-refresh:active:not(:disabled) { transform: scale(0.96); }
.btn-refresh svg { width: 13px; height: 13px; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.note { margin: 0; font-size: var(--fs-md); color: var(--text-muted); line-height: 1.45; }
.note.error { color: var(--danger); }
.note.clean { color: var(--success); }
.empty-cloud { animation: cloud-bob 3.4s ease-in-out infinite; }
@keyframes cloud-bob { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-4px); } }
.empty { display: flex; flex-direction: column; align-items: center; gap: 0.5rem; padding: 2rem 1rem; color: var(--text-muted); font-size: var(--fs-md); text-align: center; }

.layout { display: grid; grid-template-columns: minmax(0, 18rem) minmax(0, 1fr); gap: 1.1rem; align-items: start; }
.skeleton-list { display: flex; flex-direction: column; gap: 0.5rem; }
.skeleton-list .skeleton { animation: seq-fade-up 0.35s ease-out var(--enter-delay, 0ms) backwards, seq-shimmer 1.6s linear infinite; background-size: 200% 100%; }
.scan-item { animation: seq-fade-up 0.35s ease-out var(--enter-delay, 0ms) backwards; }
.scan-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.35rem; }
.scan-row {
  width: 100%; display: flex; flex-direction: column; gap: 0.3rem; padding: 0.6rem 0.7rem; text-align: left;
  background: var(--surface-2); border: 1px solid var(--border-solid); border-radius: 8px; color: inherit; font: inherit; cursor: pointer;
  transition: border-color 0.2s ease, background 0.2s ease, transform 0.15s ease;
  position: relative; overflow: hidden;
}
.scan-row:hover { border-color: var(--accent); transform: translateX(2px); }
/* La barra de selección crece desde el centro en vez de aparecer de golpe. */
.scan-row::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--accent); transform: scaleY(0); transition: transform 0.25s cubic-bezier(0.34, 1.56, 0.64, 1); }
.scan-row.selected { border-color: var(--accent); background: var(--accent-dim); }
.scan-row.selected::before { transform: scaleY(1); }
.scan-row.updated { animation: row-updated 1.8s ease-out; }
@keyframes row-updated { 0%, 35% { background: var(--accent-dim); border-color: var(--accent-bright); box-shadow: 0 0 0 3px var(--accent-dim); } }
.scan-row:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.row-domain { font-size: var(--fs-md); color: var(--text); font-weight: 500; overflow-wrap: anywhere; }
.row-meta { display: flex; align-items: center; gap: 0.45rem; flex-wrap: wrap; }
.row-count { font-size: var(--fs-sm); color: var(--success); }
.row-count.open { color: var(--danger); font-weight: 600; }
.row-date { margin-left: auto; font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-sm); color: var(--text-muted); }

.detail { min-width: 0; display: flex; flex-direction: column; gap: 1.2rem; }
.detail-pane { display: flex; flex-direction: column; gap: 1.2rem; animation: seq-fade-up 0.3s ease-out; }
.detail-head { display: flex; align-items: center; gap: 0.7rem; flex-wrap: wrap; }
.detail-domain { margin: 0; font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-xl); font-weight: 600; color: var(--text); overflow-wrap: anywhere; }

.state-panel { padding: 0.8rem 0.9rem; border-radius: 9px; border: 1px solid var(--border-solid); background: var(--surface-2); }
.state-panel.failed { border-color: var(--danger); background: var(--danger-dim); }
.state-title { margin: 0 0 0.5rem; font-size: var(--fs-md); color: var(--text); }
.state-panel.failed .state-title { margin: 0; }
.state-progress { height: 3px; border-radius: 2px; background: var(--border); overflow: hidden; }
.state-progress span { display: block; width: 35%; height: 100%; background: var(--accent); animation: indeterminate 1.4s ease-in-out infinite; }
@keyframes indeterminate { from { transform: translateX(-100%); } to { transform: translateX(300%); } }

.ledger { display: flex; flex-direction: column; gap: 0.5rem; animation: seq-fade-up 0.4s ease-out var(--enter-delay, 0ms) backwards; }
.inscription { display: flex; align-items: center; gap: 0.6rem; }
.inscription-mark { width: 8px; height: 8px; flex: none; transform: rotate(45deg); border: 1px solid var(--accent); background: var(--accent-dim); }
.inscription-title {
  margin: 0; font-family: var(--font-epic); font-size-adjust: var(--fsa-epic);
  font-size: var(--fs-md); font-weight: 600; letter-spacing: 0.24em; text-transform: uppercase; color: var(--accent); white-space: nowrap;
}
.inscription-rule { flex: 1; min-width: 1.5rem; height: 1px; background: linear-gradient(to right, var(--accent), transparent); opacity: 0.45; }
.inscription-tally { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-sm); color: var(--text-dim); white-space: nowrap; }

/* El registro de veredictos: una fila por cosa comprobada, con el sello a la
   derecha. Abierto se lee en rojo y con su explicación debajo; cerrado, en
   verde y sin más: no hay nada que hacer con él. */
.verdicts { list-style: none; margin: 0; padding: 0; border: 1px solid var(--border-solid); border-radius: 9px; overflow: hidden; }
.verdict {
  display: grid; grid-template-columns: 6.5em minmax(0, 1fr) auto; align-items: center; column-gap: 0.7rem; row-gap: 0.25rem;
  padding: 0.55rem 0.75rem; background: var(--surface-2); position: relative;
}
.verdict { animation: verdict-in 0.4s ease-out var(--enter-delay, 0ms) backwards; }
@keyframes verdict-in { from { opacity: 0; transform: translateX(-8px); } to { opacity: 1; transform: none; } }
.verdict + .verdict { border-top: 1px solid var(--border-solid); }
.verdict::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; }
.verdict.open::before { background: var(--danger); }
.verdict.closed::before { background: var(--success); opacity: 0.6; }
.verdict-provider {
  font-family: var(--font-epic); font-size-adjust: var(--fsa-epic); font-size: var(--fs-xs); font-weight: 600;
  letter-spacing: 0.14em; text-transform: uppercase; color: var(--text-muted);
}
.verdict-subject { font-size: var(--fs-md); color: var(--text); overflow-wrap: anywhere; }
.verdict-seal { font-size: var(--fs-sm); font-weight: 700; padding: 0.12rem 0.55rem; border-radius: 999px; white-space: nowrap; }
/* El sello se estampa un instante después de su fila: lo importante llega el último. */
.verdict-seal { animation: seal-stamp 0.42s cubic-bezier(0.34, 1.56, 0.64, 1) calc(var(--enter-delay, 0ms) + 220ms) backwards; }
@keyframes seal-stamp { from { transform: scale(1.6) rotate(-6deg); opacity: 0; } to { transform: scale(1) rotate(0); opacity: 1; } }
.verdict.open { animation: verdict-in 0.4s ease-out var(--enter-delay, 0ms) backwards, verdict-alert 1.1s ease-out calc(var(--enter-delay, 0ms) + 250ms); }
@keyframes verdict-alert { 0% { background: var(--danger-dim); } 100% { background: var(--surface-2); } }
.verdict.open .verdict-seal { color: var(--danger); background: var(--danger-dim); }
.verdict.closed .verdict-seal { color: var(--success); background: var(--success-dim); }
.verdict-detail { grid-column: 2 / -1; margin: 0; font-size: var(--fs-md); color: var(--text-dim); line-height: 1.4; }

.docs { position: relative; list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.3rem; }
.doc { display: flex; align-items: center; gap: 0.6rem; padding: 0.45rem 0.6rem; background: var(--surface-2); border: 1px solid var(--border-solid); border-radius: 7px; }
.doc-name { font-size: var(--fs-md); color: var(--text); }
.doc-date { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-sm); color: var(--text-muted); }
.doc-right { margin-left: auto; display: inline-flex; align-items: center; gap: 0.3rem; }
.doc-btn { width: 28px; height: 28px; display: grid; place-items: center; background: none; border: 1px solid var(--border); border-radius: 6px; color: var(--text-dim); cursor: pointer; }
.doc-btn svg { width: 14px; height: 14px; }
.doc-btn { transition: border-color 0.2s ease, color 0.2s ease, transform 0.12s ease; }
.doc-btn:active { transform: scale(0.92); }
.doc-btn:hover { border-color: var(--accent); color: var(--accent-bright); }
.doc-btn.danger:hover { border-color: var(--danger); color: var(--danger); }
.doc-btn:focus-visible, .btn-report:focus-visible, .btn-refresh:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.doc-status { font-size: var(--fs-sm); }
.doc-status.running { color: var(--accent-bright); }
.doc-status.error { color: var(--danger); }
.btn-report {
  align-self: flex-start; display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.45rem 0.9rem;
  background: var(--surface-2); border: 1px solid var(--accent); border-radius: 7px; color: var(--accent-bright);
  font-size: var(--fs-md); font-weight: 600; cursor: pointer;
}
.btn-report svg { width: 14px; height: 14px; }
.btn-report { transition: background 0.2s ease, transform 0.12s ease; }
.btn-report:hover:not(:disabled) { background: var(--accent-dim); }
.btn-report:active:not(:disabled) { transform: scale(0.97); }
.btn-report:disabled { opacity: 0.45; cursor: not-allowed; }

.doc-item-enter-active { transition: opacity 0.25s ease, transform 0.25s ease; }
.doc-item-enter-from { opacity: 0; transform: translateY(-3px); }
.doc-item-leave-active { transition: opacity 0.15s ease; position: absolute; inset-inline: 0; }
.doc-item-leave-to { opacity: 0; }

@media (max-width: 760px) {
  .layout { grid-template-columns: minmax(0, 1fr); }
  .verdict { grid-template-columns: minmax(0, 1fr) auto; }
  .verdict-provider { grid-column: 1 / -1; }
  .verdict-detail { grid-column: 1 / -1; }
  .inscription-title { letter-spacing: 0.16em; white-space: normal; }
}
@media (prefers-reduced-motion: reduce) {
  .spin, .state-progress span, .empty-cloud, .scan-item, .scan-row.updated, .detail-pane, .ledger,
  .verdict, .verdict.open, .verdict-seal, .skeleton-list .skeleton { animation: none !important; }
  .skeleton-list .skeleton { background-size: auto; }
  .doc-item-enter-active, .doc-item-leave-active, .scan-row, .scan-row::before, .btn-refresh, .doc-btn, .btn-report { transition: none !important; }
  .scan-row:hover { transform: none; }
}
</style>
