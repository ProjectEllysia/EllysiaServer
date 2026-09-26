<template>
  <div class="documents-page" data-module="hygeia">
    <StarBackground />
    <Topbar :title="'Hygeia'" :badge="t('hygeia.list.documents')" back-to="/hygeia/activos" :back-label="t('hygeia.list.title')" />

    <main class="documents-layout">
      <header class="head">
        <div class="head-text">
          <h2 class="head-title">{{ t('hygeia.list.documents') }}</h2>
          <p class="head-sub">{{ t('hygeiaDocuments.intro') }}</p>
        </div>
        <button
          type="button" class="btn-secondary" :disabled="store.state.loading"
          @click="store.fetchDocuments()"
        >{{ t('hygeiaDocuments.refresh') }}</button>
      </header>

      <!-- Filas fantasma con la silueta de las reales mientras carga la
           primera vez; en las recargas se queda la lista que ya había. -->
      <ul
        v-if="store.state.loading && !store.state.documents.length"
        class="rows" aria-busy="true" :aria-label="t('hygeiaDocuments.loading')"
      >
        <li v-for="n in SKELETON_ROWS" :key="n" class="row" aria-hidden="true">
          <span class="skeleton skeleton--block format-ghost"></span>
          <span class="row-text">
            <span class="row-title"><span class="skeleton skeleton--line skeleton-inline skeleton--w60"></span></span>
            <span class="row-detail"><span class="skeleton skeleton--line skeleton-inline skeleton--w40"></span></span>
          </span>
        </li>
      </ul>

      <p v-else-if="store.state.error" class="state-msg state-msg--error">
        {{ store.state.error }}
        <button type="button" class="retry" @click="store.fetchDocuments()">{{ t('common.retry') }}</button>
      </p>

      <div v-else-if="!store.state.documents.length" class="state-empty">
        <p class="empty-title">{{ t('hygeiaDocuments.emptyTitle') }}</p>
        <i18n-t keypath="hygeiaDocuments.emptySub" tag="p" class="empty-sub">
          <template #stats><RouterLink to="/hygeia/estadisticas">{{ t('hygeia.tabs.estadisticas') }}</RouterLink></template>
          <template #assets><RouterLink to="/hygeia/activos">{{ t('hygeia.list.title') }}</RouterLink></template>
        </i18n-t>
      </div>

      <ul v-else class="rows">
        <li v-for="document in store.state.documents" :key="document.id" class="row">
          <span class="format" :class="`format--${document.format}`">{{ formatLabel(document) }}</span>
          <span class="row-text">
            <span class="row-title">{{ describeDocument(document, t).title }}</span>
            <span class="row-detail">
              {{ [describeDocument(document, t).detail, describeWhen(document)].filter(Boolean).join(' · ') }}
            </span>
          </span>
          <span class="status" :class="`status--${document.status}`">
            <span v-if="documentStatusOf(document.status).isActive" class="status-spinner" aria-hidden="true"></span>
            {{ t(documentStatusOf(document.status).labelKey) }}
          </span>
          <span class="row-actions">
            <button
              v-if="document.status === 'done'" type="button" class="btn-download"
              :aria-label="t('hygeiaDocuments.downloadLabel', { title: describeDocument(document, t).title })"
              @click="store.downloadDocument(document)"
            >{{ t('hygeiaDocuments.download') }}</button>
            <button
              type="button" class="btn-icon btn-icon--danger"
              :title="t('common.delete')" :aria-label="t('hygeiaDocuments.deleteLabel', { title: describeDocument(document, t).title })"
              @click="pendingDelete = document"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
                <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
              </svg>
            </button>
          </span>
        </li>
      </ul>

      <nav v-if="pageCount > 1" class="pager" :aria-label="t('hygeiaDocuments.pages')">
        <button
          type="button" class="btn-secondary" :disabled="store.state.page <= 1 || store.state.loading"
          @click="store.fetchDocuments({ page: store.state.page - 1 })"
        >{{ t('hygeiaDocuments.previous') }}</button>
        <span class="pager-label">{{ t('hygeiaDocuments.page', { page: store.state.page, total: pageCount }) }}</span>
        <button
          type="button" class="btn-secondary" :disabled="store.state.page >= pageCount || store.state.loading"
          @click="store.fetchDocuments({ page: store.state.page + 1 })"
        >{{ t('hygeiaDocuments.next') }}</button>
      </nav>
    </main>

    <ConfirmModal
      :show="!!pendingDelete"
      :title="t('hygeiaDocuments.deleteTitle')"
      :message="pendingDelete ? t('hygeiaDocuments.deleteMessage', { title: describeDocument(pendingDelete, t).title }) : ''"
      :confirm-label="t('common.delete')"
      danger
      @confirm="confirmDelete"
      @cancel="pendingDelete = null"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import Topbar from '@/components/shared/Topbar.vue'
import StarBackground from '@/components/shared/StarBackground.vue'
import ConfirmModal from '@/components/shared/ConfirmModal.vue'
import { timeAgo } from '@/components/hygeia/format'
import { describeDocument, documentStatusOf } from '@/components/hygeia/documents'
import { useHygeiaDocumentsStore } from '@/stores/hygeiaDocumentsStore'
import { useToastStore } from '@/stores/toastStore'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const store = useHygeiaDocumentsStore()
const toast = useToastStore()

/** Filas fantasma mientras carga la lista por primera vez. */
const SKELETON_ROWS = 4

/** Documento cuya confirmación de borrado está abierta, o `null`. */
const pendingDelete = ref(null)

const pageCount = computed(() => Math.ceil(store.state.total / store.state.perPage))

// Cada cuánto se reescribe «hace X»: medio minuto basta para una lista que se
// mira en minutos, no en segundos.
const AGE_TICK_MS = 30000
const ageNow = ref(Date.now())
let ageTimer = null

/**
 * Rótulo corto del formato para la insignia de la fila.
 *
 * @param {{format?: string}} document - Documento.
 * @returns {string} `CSV`, `PDF`, o el formato en mayúsculas si es otro.
 */
function formatLabel(document) {
  return (document.format ?? '').toUpperCase() || '—'
}

/**
 * Cuándo se pidió o se generó un documento, en palabras.
 *
 * @param {{status: string, createdAt: string, generatedAt?: string}} document - Documento.
 * @returns {string} «generado hace X» si está listo; «pedido hace X» en otro caso.
 */
function describeWhen(document) {
  void ageNow.value
  return document.status === 'done' && document.generatedAt
    ? t('hygeiaDocuments.generated', { when: timeAgo(document.generatedAt, t) })
    : t('hygeiaDocuments.requested', { when: timeAgo(document.createdAt, t) })
}

/** Borra el documento cuya confirmación está abierta. */
async function confirmDelete() {
  const document = pendingDelete.value
  pendingDelete.value = null
  if (!document) return
  if (await store.deleteDocument(document.id)) toast.show(t('hygeiaDocuments.deleted'), 'success')
}

onMounted(() => {
  store.fetchDocuments({ page: 1 })
  ageTimer = setInterval(() => { ageNow.value = Date.now() }, AGE_TICK_MS)
})

onUnmounted(() => clearInterval(ageTimer))
</script>

<style scoped>
.documents-page {
  min-height: 100vh;
  background: var(--bg);
  padding-top: var(--topbar-h);
  position: relative;
}

.documents-layout {
  position: relative;
  z-index: 1;
  max-width: 900px;
  margin: 0 auto;
  padding: 1.5rem 1.5rem 3rem;
}

.head { display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; flex-wrap: wrap; margin-bottom: 1.2rem; }
.head-title { margin: 0 0 0.3rem; font-size: var(--fs-2xl); font-weight: 600; color: var(--text); }
.head-sub { margin: 0; max-width: 60ch; font-size: var(--fs-md); color: var(--text-muted); line-height: 1.5; }

.btn-secondary {
  padding: 0.4rem 0.85rem; border-radius: 6px; font-size: var(--fs-md); font-weight: 600; cursor: pointer;
  background: var(--surface-2); border: 1px solid var(--border); color: var(--text-dim);
}
.btn-secondary:hover:not(:disabled) { border-color: var(--text-muted); color: var(--text); }
.btn-secondary:disabled { opacity: 0.55; cursor: not-allowed; }

/* ── Lista ── */
.rows { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 0.4rem; }

.row {
  display: flex; align-items: center; gap: 0.8rem;
  padding: 0.65rem 0.75rem;
  background: var(--surface); border: 1px solid var(--border-med); border-radius: 8px;
  animation: seq-fade-up 0.3s cubic-bezier(0.22, 1, 0.36, 1) backwards;
}

.format, .format-ghost {
  width: 2.6rem; height: 2.6rem; flex-shrink: 0;
  display: grid; place-items: center; border-radius: 6px;
  font-size: var(--fs-xs); font-weight: 700; letter-spacing: 0.04em;
}
.format { background: var(--surface-2); color: var(--text-dim); border: 1px solid var(--border); }
.format--csv { color: var(--accent-bright); border-color: var(--accent); background: var(--accent-dim); }
.format--pdf { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 45%, transparent); }

.row-text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 0.15rem; }
.row-title { color: var(--text); font-weight: 600; font-size: var(--fs-md); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.row-detail { color: var(--text-muted); font-size: var(--fs-sm); }
.skeleton-inline { display: inline-block; vertical-align: middle; }

.status {
  display: inline-flex; align-items: center; gap: 0.35rem; flex-shrink: 0;
  padding: 0.15rem 0.55rem; border-radius: 999px;
  font-size: var(--fs-sm); font-weight: 600;
  background: var(--surface-2); color: var(--text-muted);
}
.status--done { background: var(--accent-dim); color: var(--accent-bright); }
.status--error { background: var(--danger-dim); color: var(--danger); }

.status-spinner {
  width: 0.7rem; height: 0.7rem; border-radius: 50%;
  border: 2px solid currentColor; border-right-color: transparent;
  animation: seq-spin 0.9s linear infinite;
}

.row-actions { display: flex; align-items: center; gap: 0.4rem; flex-shrink: 0; }

.btn-download {
  padding: 0.35rem 0.75rem;
  background: var(--accent-dim); border: 1px solid var(--accent); border-radius: 6px;
  color: var(--accent-bright); font-size: var(--fs-sm); font-weight: 600; cursor: pointer;
  transition: background var(--transition), color var(--transition);
}
.btn-download:hover { background: var(--accent); color: var(--on-accent); }

.btn-icon {
  width: 30px; height: 30px; display: grid; place-items: center;
  background: transparent; border: 1px solid var(--border-med); border-radius: 6px;
  color: var(--text-muted); cursor: pointer;
  transition: border-color var(--transition), color var(--transition);
}
.btn-icon svg { width: 14px; height: 14px; }
.btn-icon--danger:hover { border-color: var(--danger); color: var(--danger); }

.btn-download:focus-visible, .btn-icon:focus-visible, .btn-secondary:focus-visible, .retry:focus-visible {
  outline: 2px solid var(--accent-bright); outline-offset: 2px;
}

/* ── Estados ── */
.state-msg { margin: 1.2rem 0; font-size: var(--fs-md); color: var(--text-muted); }
.state-msg--error { color: var(--danger); }
.retry {
  margin-left: 0.5rem; padding: 0.2rem 0.6rem;
  background: transparent; border: 1px solid currentColor; border-radius: 6px;
  color: inherit; font-size: var(--fs-sm); cursor: pointer;
}

.state-empty {
  padding: 2rem 1rem; text-align: center;
  background: var(--surface); border: 1px dashed var(--border-med); border-radius: 8px;
}
.empty-title { margin: 0 0 0.35rem; color: var(--text); font-weight: 600; font-size: var(--fs-md); }
.empty-sub { margin: 0; color: var(--text-muted); font-size: var(--fs-md); }
.empty-sub a { color: var(--accent-bright); }

.pager { display: flex; align-items: center; justify-content: center; gap: 0.8rem; margin-top: 1rem; }
.pager-label { color: var(--text-muted); font-size: var(--fs-sm); }

@media (max-width: 640px) {
  .row { flex-wrap: wrap; }
  .row-text { flex-basis: calc(100% - 3.4rem); }
  .status { margin-left: 3.4rem; }
  .row-actions { margin-left: auto; }
}

@media (prefers-reduced-motion: reduce) {
  .row { animation: none; }
  .status-spinner { animation: none; border-right-color: currentColor; }
}
</style>
