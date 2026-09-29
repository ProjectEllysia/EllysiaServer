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
    <p v-else-if="loading && !scans.length" class="note">{{ t('common.loading') }}</p>
    <div v-else-if="!scans.length" class="empty">
      <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" aria-hidden="true"><path d="M17.5 19a4.5 4.5 0 1 0-1.4-8.78A6 6 0 0 0 4.5 12.5 3.5 3.5 0 0 0 6 19z"/></svg>
      <span>{{ t('lybra.cloud.empty') }}</span>
    </div>

    <div v-else class="layout">
      <ul class="scan-list" role="listbox" :aria-label="t('lybra.cloud.listTitle')">
        <li v-for="scan in scans" :key="scan.osintScanId">
          <button type="button" class="scan-row" role="option" :aria-selected="scan.osintScanId === selectedId"
            :class="{ selected: scan.osintScanId === selectedId }" @click="$emit('select', scan.osintScanId)">
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
        <template v-else>
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
            <section class="ledger">
              <header class="inscription">
                <span class="inscription-mark" aria-hidden="true"></span>
                <h4 class="inscription-title">{{ t('lybra.cloud.declared') }}</h4>
                <span class="inscription-rule" aria-hidden="true"></span>
                <span class="inscription-tally">{{ verdicts.resources.length }}</span>
              </header>
              <p v-if="!verdicts.resources.length" class="note">{{ t('lybra.cloud.noneDeclared') }}</p>
              <ul v-else class="verdicts">
                <li v-for="entry in verdicts.resources" :key="entry.subject" class="verdict" :class="entry.finding ? 'open' : 'closed'">
                  <span class="verdict-provider">{{ t(`lybra.cloud.providers.${cloudProviderKey(entry.subject)}`) }}</span>
                  <span class="verdict-subject mono">{{ entry.subject }}</span>
                  <span class="verdict-seal">{{ entry.finding ? t('lybra.cloud.open') : t('lybra.cloud.closed') }}</span>
                  <p v-if="entry.finding" class="verdict-detail">{{ entry.finding.title }}</p>
                </li>
              </ul>
            </section>

            <section class="ledger">
              <header class="inscription">
                <span class="inscription-mark" aria-hidden="true"></span>
                <h4 class="inscription-title">{{ t('lybra.cloud.subdomains') }}</h4>
                <span class="inscription-rule" aria-hidden="true"></span>
                <span v-if="detail.checkSubdomains" class="inscription-tally">{{ t('lybra.cloud.knownSubdomains', { count: detail.subdomainCount }, detail.subdomainCount) }}</span>
              </header>
              <p v-if="!detail.checkSubdomains" class="note">{{ t('lybra.cloud.subdomainsSkipped') }}</p>
              <p v-else-if="!verdicts.subdomains.length" class="note clean">{{ t('lybra.cloud.noTakeover') }}</p>
              <ul v-else class="verdicts">
                <li v-for="finding in verdicts.subdomains" :key="finding.dedupKey || finding.service" class="verdict open">
                  <span class="verdict-provider">{{ t('lybra.cloud.takeover') }}</span>
                  <span class="verdict-subject mono">{{ finding.service }}</span>
                  <span class="verdict-seal">{{ t('lybra.cloud.claimable') }}</span>
                  <p class="verdict-detail">{{ finding.title }}</p>
                </li>
              </ul>
            </section>

            <!-- Informes: se generan en segundo plano como los de un escaneo. -->
            <section class="ledger">
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
        </template>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
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
.btn-refresh:hover:not(:disabled) { border-color: var(--accent); color: var(--text); }
.btn-refresh svg { width: 13px; height: 13px; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.note { margin: 0; font-size: var(--fs-md); color: var(--text-muted); line-height: 1.45; }
.note.error { color: var(--danger); }
.note.clean { color: var(--success); }
.empty { display: flex; flex-direction: column; align-items: center; gap: 0.5rem; padding: 2rem 1rem; color: var(--text-muted); font-size: var(--fs-md); text-align: center; }

.layout { display: grid; grid-template-columns: minmax(0, 18rem) minmax(0, 1fr); gap: 1.1rem; align-items: start; }
.scan-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.35rem; }
.scan-row {
  width: 100%; display: flex; flex-direction: column; gap: 0.3rem; padding: 0.6rem 0.7rem; text-align: left;
  background: var(--surface-2); border: 1px solid var(--border-solid); border-radius: 8px; color: inherit; font: inherit; cursor: pointer;
  transition: border-color 0.2s ease;
}
.scan-row:hover { border-color: var(--accent); }
.scan-row.selected { border-color: var(--accent); box-shadow: inset 3px 0 0 var(--accent); }
.scan-row:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.row-domain { font-size: var(--fs-md); color: var(--text); font-weight: 500; overflow-wrap: anywhere; }
.row-meta { display: flex; align-items: center; gap: 0.45rem; flex-wrap: wrap; }
.row-count { font-size: var(--fs-sm); color: var(--success); }
.row-count.open { color: var(--danger); font-weight: 600; }
.row-date { margin-left: auto; font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-sm); color: var(--text-muted); }

.detail { min-width: 0; display: flex; flex-direction: column; gap: 1.2rem; }
.detail-head { display: flex; align-items: center; gap: 0.7rem; flex-wrap: wrap; }
.detail-domain { margin: 0; font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-xl); font-weight: 600; color: var(--text); overflow-wrap: anywhere; }

.state-panel { padding: 0.8rem 0.9rem; border-radius: 9px; border: 1px solid var(--border-solid); background: var(--surface-2); }
.state-panel.failed { border-color: var(--danger); background: var(--danger-dim); }
.state-title { margin: 0 0 0.5rem; font-size: var(--fs-md); color: var(--text); }
.state-panel.failed .state-title { margin: 0; }
.state-progress { height: 3px; border-radius: 2px; background: var(--border); overflow: hidden; }
.state-progress span { display: block; width: 35%; height: 100%; background: var(--accent); animation: indeterminate 1.4s ease-in-out infinite; }
@keyframes indeterminate { from { transform: translateX(-100%); } to { transform: translateX(300%); } }

.ledger { display: flex; flex-direction: column; gap: 0.5rem; }
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
.btn-report:hover:not(:disabled) { background: var(--accent-dim); }
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
  .spin, .state-progress span { animation: none; }
  .doc-item-enter-active, .doc-item-leave-active, .scan-row { transition: none; }
}
</style>
