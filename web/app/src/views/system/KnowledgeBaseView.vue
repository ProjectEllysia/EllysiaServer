<template>
  <div class="kb-page">
    <StarBackground />
    <Topbar :title="t('kbAdmin.title')" />

    <main class="main">
      <header class="page-header">
        <div>
          <span class="eyebrow">{{ t('kbAdmin.eyebrow') }}</span>
          <h1>{{ t('kbAdmin.title') }}</h1>
          <p class="subtitle">{{ t('kbAdmin.subtitle') }}</p>
        </div>
        <button class="btn btn--secondary" type="button" :disabled="loading" @click="loadStatus">
          {{ loading ? t('kbAdmin.refreshing') : t('kbAdmin.refresh') }}
        </button>
      </header>

      <section class="card">
        <div class="card-head">
          <h2>{{ t('kbAdmin.status.heading') }}</h2>
          <span v-if="feedVersion" class="mono muted">{{ feedVersion }}</span>
        </div>
        <table class="kb-table">
          <thead>
            <tr>
              <th>{{ t('kbAdmin.status.source') }}</th>
              <th>{{ t('kbAdmin.status.state') }}</th>
              <th>{{ t('kbAdmin.status.lastSuccess') }}</th>
              <th>{{ t('kbAdmin.status.lastAttempt') }}</th>
              <th class="num">{{ t('kbAdmin.status.rows') }}</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="source in sources" :key="source.source">
              <tr>
                <td class="mono">{{ source.source }}</td>
                <td><span class="badge" :class="`badge--${stateOf(source)}`">{{ t(`kbAdmin.state.${stateOf(source)}`) }}</span></td>
                <td>{{ source.lastSuccessAt ? formatDateTime(source.lastSuccessAt) : '—' }}</td>
                <td>{{ source.lastAttemptAt ? formatDateTime(source.lastAttemptAt) : '—' }}</td>
                <td class="num">{{ source.rowsUpserted != null ? formatNumber(source.rowsUpserted) : '—' }}</td>
              </tr>
              <tr v-if="source.error" class="error-row">
                <td colspan="5"><span class="mono">{{ source.error }}</span></td>
              </tr>
            </template>
          </tbody>
        </table>
      </section>

      <section class="card">
        <div class="card-head">
          <h2>{{ t('kbAdmin.sync.heading') }}</h2>
        </div>
        <p class="hint">{{ t('kbAdmin.sync.hint') }}</p>
        <div class="sync-grid">
          <div v-for="target in SYNC_TARGETS" :key="target" class="sync-item">
            <button class="btn" :class="target === 'all' ? 'btn--primary' : 'btn--secondary'" type="button"
                    :disabled="isSyncRunning || requesting" @click="requestSync(target)">
              {{ t(`kbAdmin.sync.targets.${target}`) }}
            </button>
            <span v-if="tasks[target]?.status" class="task-state" :class="`task-state--${tasks[target].status}`">
              {{ t(`kbAdmin.sync.taskStatus.${tasks[target].status}`) }}
            </span>
          </div>
        </div>
      </section>

      <section class="card">
        <div class="card-head">
          <h2>{{ t('kbAdmin.search.heading') }}</h2>
        </div>
        <form class="search-row" @submit.prevent="search">
          <input v-model.trim="query" class="inp" type="search" :placeholder="t('kbAdmin.search.placeholder')" minlength="2" />
          <button class="btn btn--primary" type="submit" :disabled="query.length < 2 || searching">
            {{ t('kbAdmin.search.submit') }}
          </button>
        </form>

        <template v-if="result">
          <p v-if="result.kind === 'cve' && !result.cve" class="hint">{{ t('kbAdmin.search.cveUnknown') }}</p>
          <div v-else-if="result.kind === 'cve'" class="cve">
            <h3 class="mono">{{ result.cve.cveId }}</h3>
            <p v-if="result.cve.description" class="description">{{ result.cve.description }}</p>
            <dl class="facts">
              <dt>{{ t('kbAdmin.search.cvss') }}</dt>
              <dd>{{ result.cve.cvssScore ?? '—' }} <span v-if="result.cve.severity" class="muted">{{ result.cve.severity }}</span></dd>
              <dt>{{ t('kbAdmin.search.kev') }}</dt>
              <dd>{{ result.cve.inKev ? t('kbAdmin.search.yes') : t('kbAdmin.search.no') }}</dd>
              <dt>{{ t('kbAdmin.search.epss') }}</dt>
              <dd>{{ result.cve.epssScore != null ? formatNumber(result.cve.epssScore, { style: 'percent', maximumFractionDigits: 2 }) : '—' }}</dd>
              <dt>{{ t('kbAdmin.search.products') }}</dt>
              <dd class="mono">{{ result.cve.products.map((p) => `${p.vendor}:${p.product}`).join(', ') || '—' }}</dd>
            </dl>
            <table v-if="result.cve.distroStatuses.length" class="kb-table">
              <thead>
                <tr>
                  <th>{{ t('kbAdmin.search.distro') }}</th>
                  <th>{{ t('kbAdmin.search.package') }}</th>
                  <th>{{ t('kbAdmin.status.state') }}</th>
                  <th>{{ t('kbAdmin.search.fixedIn') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in result.cve.distroStatuses" :key="`${row.vendor}-${row.release}-${row.package}`">
                  <td class="mono">{{ row.vendor }}{{ row.release ? ` ${row.release}` : '' }}</td>
                  <td class="mono">{{ row.package }}</td>
                  <td>{{ t(`kbAdmin.search.distroStatus.${row.status}`) }}</td>
                  <td class="mono">{{ row.fixedIn || '—' }}</td>
                </tr>
              </tbody>
            </table>
            <p v-else class="hint">{{ t('kbAdmin.search.noDistroStatus') }}</p>
          </div>
          <template v-else>
            <p v-if="!result.products.length" class="hint">{{ t('kbAdmin.search.noProducts') }}</p>
            <ul v-else class="products">
              <li v-for="product in result.products" :key="`${product.vendor}:${product.product}`">
                <strong>{{ product.displayName }}</strong>
                <span class="mono muted">{{ product.vendor }}:{{ product.product }}</span>
              </li>
            </ul>
          </template>
        </template>
      </section>
    </main>
  </div>
</template>

<script setup>
/**
 * Panel de administración de la base de conocimiento de Lybra.
 *
 * Lybra decide qué vulnerabilidades tiene un servicio cruzándolo con un espejo
 * local de NVD, KEV, EPSS y las listas de parches de las distribuciones
 * (OVAL). Aquí se ve cómo está cada fuente y por qué falló si falló, se lanza
 * a mano su sincronización sin esperar al job nocturno, y se consulta qué
 * sabe el espejo de una CVE o de un producto. Sólo administradores: la ruta
 * lo exige y la API también.
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Topbar from '@/components/shared/Topbar.vue'
import StarBackground from '@/components/shared/StarBackground.vue'
import { useApi } from '@/composables/useApi'
import { usePolling } from '@/composables/usePolling'
import { useToastStore } from '@/stores/toastStore'
import { formatDateTime, formatNumber } from '@/i18n/format'

/** Lo que se puede sincronizar a mano; mismo orden que en la API. */
const SYNC_TARGETS = ['all', 'nvd', 'kev', 'epss', 'oval']
const ACTIVE = ['pending', 'running']

const { t } = useI18n()
const { apiFetch, apiError } = useApi()
const toast = useToastStore()

const sources = ref([])
const feedVersion = ref(null)
const loading = ref(false)
const tasks = ref({})
const requesting = ref(false)
const query = ref('')
const searching = ref(false)
const result = ref(null)

const isSyncRunning = computed(() => Object.values(tasks.value).some((task) => ACTIVE.includes(task?.status)))

/**
 * El estado de una fuente, en una palabra que elige la etiqueta y el color.
 * @param {object} source - Una entrada de `sources` de `GET /themis/kb/status`.
 * @returns {'failing'|'stale'|'unverified'|'ok'} `failing` si el último intento falló,
 *   `stale` si pasa de su antigüedad máxima, `unverified` si tiene datos pero ningún
 *   registro de sincronización, y `ok` en otro caso.
 */
function stateOf(source) {
  if (source.error) return 'failing'
  if (source.isStale) return 'stale'
  if (source.isUnverified) return 'unverified'
  return 'ok'
}

/** Carga el estado de cada fuente. */
async function loadStatus() {
  loading.value = true
  try {
    const res = await apiFetch('/themis/kb/status')
    if (!res?.ok) { toast.show(await apiError(res, t('kbAdmin.errors.status')), 'error'); return }
    const data = await res.json()
    sources.value = data.sources ?? []
    feedVersion.value = data.feedVersion ?? null
  } finally { loading.value = false }
}

/**
 * Lee el estado de las sincronizaciones manuales. Cuando deja de haber una en
 * marcha, para el sondeo y recarga el estado de las fuentes, que es lo que ha
 * cambiado.
 */
async function loadTasks() {
  const res = await apiFetch('/themis/kb/sync')
  if (!res?.ok) return
  const wasRunning = isSyncRunning.value
  tasks.value = (await res.json()).tasks ?? {}
  if (isSyncRunning.value) polling.start()
  else if (wasRunning) { polling.stop(); await loadStatus() }
}

const polling = usePolling(loadTasks, { intervalMs: 5000, immediate: false })

/**
 * Pide una sincronización manual.
 * @param {string} target - Uno de `SYNC_TARGETS`.
 */
async function requestSync(target) {
  requesting.value = true
  try {
    const res = await apiFetch('/themis/kb/sync', { method: 'POST', body: JSON.stringify({ source: target }) })
    if (!res?.ok) { toast.show(await apiError(res, t('kbAdmin.errors.sync')), 'error'); return }
    const data = await res.json()
    if (data.queued) toast.show(t('kbAdmin.sync.queued', { target: t(`kbAdmin.sync.targets.${target}`) }), 'success')
    else toast.show(t('kbAdmin.sync.alreadyRunning', { target: t(`kbAdmin.sync.targets.${data.runningTarget}`) }), 'warn')
    await loadTasks()
  } finally { requesting.value = false }
}

/** Busca en la base de conocimiento una CVE o un producto. */
async function search() {
  searching.value = true
  try {
    const res = await apiFetch(`/themis/kb/search?query=${encodeURIComponent(query.value)}`)
    if (!res?.ok) { toast.show(await apiError(res, t('kbAdmin.errors.search')), 'error'); return }
    result.value = await res.json()
  } finally { searching.value = false }
}

onMounted(() => {
  loadStatus()
  loadTasks()
})
</script>

<style scoped>
.kb-page {
  min-height: 100vh;
  background: radial-gradient(circle at 88% 8%, rgba(212,160,74,0.08), transparent 28rem), var(--bg);
  padding-top: var(--topbar-h);
  position: relative;
}
.main { max-width: 1120px; margin: 0 auto; padding: 2rem 1.1rem 4.5rem; position: relative; z-index: 1; }
.page-header { display: flex; justify-content: space-between; align-items: flex-end; gap: 1rem; margin-bottom: 1.4rem; }
.eyebrow {
  display: block; color: var(--accent);
  font-family: var(--font-mono); font-size-adjust: var(--fsa-mono);
  font-size: var(--fs-sm); letter-spacing: 0.15em; text-transform: uppercase;
}
.page-header h1 { margin: 0.35rem 0 0; color: var(--text); font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-3xl); font-weight: 800; }
.subtitle { margin: 0.35rem 0 0; color: var(--text-dim); font-size: var(--fs-lg); }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; box-shadow: 0 18px 50px rgba(0,0,0,0.18); padding: 1.15rem; margin-bottom: 1.1rem; }
.card-head { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; padding-bottom: 0.8rem; border-bottom: 1px solid var(--border); margin-bottom: 0.9rem; }
.card-head h2 { margin: 0; color: var(--text); font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-xl); }
.mono { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); }
.muted { color: var(--text-muted); font-size: var(--fs-sm); }
.hint { color: var(--text-muted); font-size: var(--fs-md); margin: 0 0 0.9rem; }
.kb-table { width: 100%; border-collapse: collapse; font-size: var(--fs-md); }
.kb-table th { text-align: left; color: var(--text-muted); font-weight: 600; padding: 0.45rem 0.6rem; border-bottom: 1px solid var(--border); }
.kb-table td { padding: 0.45rem 0.6rem; color: var(--text); border-bottom: 1px solid var(--border); }
.kb-table .num { text-align: right; }
.error-row td { color: var(--danger); background: var(--surface-2); font-size: var(--fs-sm); word-break: break-word; }
.badge { padding: 0.15rem 0.55rem; border-radius: 999px; font-size: var(--fs-sm); font-weight: 600; border: 1px solid currentColor; }
.badge--ok { color: var(--success); }
.badge--unverified { color: var(--text-dim); }
.badge--stale { color: var(--warn); }
.badge--failing { color: var(--danger); }
.sync-grid { display: flex; gap: 0.75rem; flex-wrap: wrap; }
.sync-item { display: flex; flex-direction: column; align-items: flex-start; gap: 0.35rem; }
.task-state { font-size: var(--fs-sm); color: var(--text-muted); }
.task-state--running, .task-state--pending { color: var(--accent-bright); }
.task-state--failed, .task-state--timeout { color: var(--danger); }
.search-row { display: flex; gap: 0.6rem; margin-bottom: 1rem; }
.search-row .inp { flex: 1; }
.cve h3 { margin: 0 0 0.5rem; color: var(--text); }
.description { color: var(--text-dim); margin: 0 0 0.8rem; }
.facts { display: grid; grid-template-columns: max-content 1fr; gap: 0.35rem 1rem; margin: 0 0 1rem; }
.facts dt { color: var(--text-muted); font-weight: 600; }
.facts dd { margin: 0; color: var(--text); }
.products { list-style: none; margin: 0; padding: 0; display: grid; gap: 0.4rem; }
.products li { display: flex; gap: 0.6rem; align-items: baseline; color: var(--text); }
@media (max-width: 640px) {
  .page-header { flex-direction: column; align-items: flex-start; }
  .kb-table { display: block; overflow-x: auto; }
}
</style>
