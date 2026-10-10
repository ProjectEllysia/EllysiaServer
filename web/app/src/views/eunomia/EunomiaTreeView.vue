<template>
  <div class="eunomia-page" data-module="eunomia">
    <StarBackground />
    <Topbar :title="'Eunomia'" :badge="data?.shortName || ''" back-to="/eunomia/marcos" :back-label="t('eunomia.frameworks.title')" />

    <main class="layout">
      <p v-if="loading" class="state-msg">{{ t('eunomia.frameworks.loading') }}</p>
      <p v-else-if="notAdopted" class="state-msg">
        {{ t('eunomia.tree.notAdopted') }}
        <router-link to="/eunomia/marcos" class="link">{{ t('eunomia.frameworks.title') }}</router-link>
      </p>
      <p v-else-if="error" class="state-msg state-msg--error">{{ error }}</p>

      <template v-else-if="data">
        <header class="head">
          <h1>{{ data.name }}</h1>
          <p class="meta">
            {{ t('eunomia.frameworks.version', { version: data.version }) }}
            <template v-if="data.status === 'draft'"> · {{ t('eunomia.frameworks.draft') }}</template>
          </p>
        </header>

        <section v-if="summary" class="summary" :aria-label="t('eunomia.summary.title')">
          <div class="summary-global">
            <p class="big">{{ percent(summary.global.percent) }}</p>
            <div class="summary-main">
              <ProgressBar :percent="summary.global.percent" :label="t('eunomia.summary.global')" />
              <p class="counts">
                {{ t('eunomia.summary.counts', {
                  implemented: summary.global.counts.implemented, countable: summary.global.countable,
                  notApplicable: summary.global.counts.not_applicable }) }}
              </p>
            </div>
          </div>
          <ul class="branches">
            <li v-for="branch in summary.branches" :key="branch.code">
              <span class="branch-title">{{ branch.identifier }} · {{ branch.title }}</span>
              <ProgressBar :percent="branch.percent" :label="branch.title" />
              <span class="branch-pct">{{ branch.countable ? percent(branch.percent) : '—' }}</span>
            </li>
          </ul>
          <div class="attention">
            <div v-if="summary.upcoming.length">
              <h2>{{ t('eunomia.summary.upcoming') }}</h2>
              <ul>
                <li v-for="item in summary.upcoming" :key="item.code">
                  <button type="button" class="link-btn" @click="goTo(item.code)">{{ item.identifier }}</button>
                  {{ item.title }} · {{ formatDate(item.dueDate) }}
                  <strong v-if="item.isOverdue" class="overdue">{{ t('eunomia.summary.overdue') }}</strong>
                </li>
              </ul>
            </div>
            <div v-if="summary.unassignedCount">
              <h2>{{ t('eunomia.summary.unassigned', { count: summary.unassignedCount }, summary.unassignedCount) }}</h2>
              <ul>
                <li v-for="item in summary.unassigned" :key="item.code">
                  <button type="button" class="link-btn" @click="goTo(item.code)">{{ item.identifier }}</button>
                  {{ item.title }}
                </li>
              </ul>
            </div>
          </div>
        </section>

        <div class="filters">
          <input v-model.trim="query" type="search" class="search" :placeholder="t('eunomia.tree.search')" :aria-label="t('eunomia.tree.search')" />
          <select v-model="statusFilter" class="status-filter" :aria-label="t('eunomia.tree.filterStatus')">
            <option value="">{{ t('eunomia.tree.allStatuses') }}</option>
            <option v-for="status in STATUSES" :key="status" :value="status">{{ t(`eunomia.status.${status}`) }}</option>
          </select>
          <button type="button" class="link-btn" @click="expandAll">{{ t('eunomia.tree.expandAll') }}</button>
          <button type="button" class="link-btn" @click="collapseAll">{{ t('eunomia.tree.collapseAll') }}</button>
        </div>

        <div class="panes">
          <section class="pane pane--tree" :aria-label="t('eunomia.tree.treeLabel')">
            <ControlTree
              :nodes="filtered"
              :selected="selectedCode"
              :expanded="effectiveExpanded"
              @update:expanded="expanded = $event"
              :label="data.name"
              @select="selectNode"
            />
          </section>
          <section class="pane pane--detail">
            <ControlDetail
              v-if="selectedNode"
              :node="selectedNode"
              :framework="framework"
              :people="data.people"
              :saving="saving"
              :conflict="conflict"
              :history="history"
              @save="save"
              @take-current="takeCurrent"
              @evidence-changed="onEvidenceChanged"
            />
            <p v-else class="state-msg">{{ t('eunomia.tree.pickOne') }}</p>
          </section>
        </div>
      </template>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import Topbar from '@/components/shared/Topbar.vue'
import StarBackground from '@/components/shared/StarBackground.vue'
import ControlTree from '@/components/eunomia/ControlTree.vue'
import ProgressBar from '@/components/eunomia/ProgressBar.vue'
import ControlDetail from '@/components/eunomia/ControlDetail.vue'
import { STATUSES, filterTree, findNode, groupCodes } from '@/components/eunomia/tree'
import { formatDate, formatNumber } from '@/i18n/format'
import { useEunomiaStore } from '@/stores/eunomiaStore'
import { useToastStore } from '@/stores/toastStore'

const { t } = useI18n()
const route = useRoute()
const store = useEunomiaStore()
const toast = useToastStore()

const framework = computed(() => String(route.params.framework))
const data = ref(null)
const loading = ref(true)
const notAdopted = ref(false)
const error = ref('')

const query = ref('')
const statusFilter = ref('')
const expanded = ref(new Set())
const selectedCode = ref('')
const saving = ref(false)
const conflict = ref(null)
const history = ref([])
const summary = ref(null)

const filtered = computed(() => filterTree(data.value?.tree ?? [], { query: query.value, status: statusFilter.value }))
const selectedNode = computed(() => (selectedCode.value ? findNode(data.value?.tree ?? [], selectedCode.value) : null))

/** Con un filtro activo se despliega todo para que las coincidencias se vean. */
const effectiveExpanded = computed(() => (query.value || statusFilter.value ? groupCodes(filtered.value) : expanded.value))

/** Carga el árbol; en la primera carga despliega la primera rama. */
async function load() {
  loading.value = true
  const result = await store.loadTree(framework.value)
  loading.value = false
  notAdopted.value = result.notAdopted
  error.value = result.message || ''
  if (!result.ok) return
  const first = !data.value
  data.value = result.data
  summary.value = await store.loadSummary(framework.value)
  if (first) expanded.value = new Set(data.value.tree.slice(0, 1).map((node) => node.code))
}

/** Un porcentaje (0 a 100) con el formato del idioma activo. */
function percent(value) {
  return formatNumber(value / 100, { style: 'percent', maximumFractionDigits: 0 })
}

/** Despliega hasta un control y lo selecciona (desde las listas del resumen). */
async function goTo(code) {
  const node = findNode(data.value.tree, code)
  if (!node) return
  const next = new Set(expanded.value)
  const open = (list, trail) => list.some((item) => {
    if (item.code === code) { trail.forEach((c) => next.add(c)); return true }
    return open(item.children, [...trail, item.code])
  })
  open(data.value.tree, [])
  expanded.value = next
  query.value = ''
  statusFilter.value = ''
  await selectNode(node)
}

function expandAll() { expanded.value = groupCodes(data.value?.tree ?? []) }
function collapseAll() { expanded.value = new Set() }

/** Carga el historial del control seleccionado, si es evaluable. */
async function loadHistory() {
  const node = selectedNode.value
  history.value = node?.assessment ? await store.loadHistory(framework.value, node.identifier) : []
}

/** Selecciona un nodo y descarta cualquier conflicto del anterior. */
async function selectNode(node) {
  selectedCode.value = node.code
  conflict.value = null
  await loadHistory()
}

/**
 * Guarda la evaluación del nodo seleccionado.
 *
 * @param {object} body - Cuerpo ya armado por el detalle, con el testigo de concurrencia.
 */
async function save(body) {
  const node = selectedNode.value
  saving.value = true
  const result = await store.saveAssessment(framework.value, node.identifier, body)
  saving.value = false
  if (result.ok) {
    conflict.value = null
    toast.show(t('eunomia.tree.saved'), 'success')
    await load()
    await loadHistory()
  } else if (result.conflict) {
    conflict.value = result.conflict
  } else {
    toast.show(result.message, 'error')
  }
}

/** Recarga árbol e historial tras enlazar, desenlazar o subir una evidencia. */
async function onEvidenceChanged() {
  await load()
  await loadHistory()
}

/** Toma el valor que dejó otra persona y vuelve a pintar el control con él. */
async function takeCurrent() {
  conflict.value = null
  await load()
}

onMounted(load)
</script>

<style scoped>
.eunomia-page { min-height: 100vh; background: var(--bg); padding-top: var(--topbar-h); position: relative; }
.layout { max-width: 1200px; margin: 0 auto; padding: 1.5rem 1.5rem 3rem; display: flex; flex-direction: column; gap: 1rem; position: relative; z-index: 1; }
.head h1 { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-2xl); color: var(--text); }
.meta { color: var(--text-muted); font-size: var(--fs-body); }
.summary { background: var(--surface); border: 1px solid var(--border-solid); border-radius: 10px; padding: 1rem 1.2rem; display: flex; flex-direction: column; gap: 1rem; }
.summary-global { display: flex; gap: 1rem; align-items: center; }
.big { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-2xl); color: var(--text); min-width: 4.5rem; }
.summary-main { flex: 1; display: flex; flex-direction: column; gap: 0.4rem; }
.counts { color: var(--text-muted); font-size: var(--fs-body); }
.branches { list-style: none; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(18rem, 1fr)); gap: 0.6rem 1.2rem; }
.branches li { display: grid; grid-template-columns: 1fr auto; gap: 0.2rem 0.6rem; align-items: center; font-size: var(--fs-body); color: var(--text-dim); }
.branches li .progress { grid-column: 1 / -1; }
.branch-pct { font-variant-numeric: tabular-nums; color: var(--text-muted); }
.attention { display: grid; grid-template-columns: repeat(auto-fit, minmax(16rem, 1fr)); gap: 1rem; }
.attention h2 { font-size: var(--fs-md); font-weight: 600; color: var(--text); margin-bottom: 0.3rem; }
.attention ul { list-style: none; padding: 0; font-size: var(--fs-body); color: var(--text-dim); display: flex; flex-direction: column; gap: 0.25rem; }
.overdue { color: var(--danger); margin-left: 0.3rem; }
.filters { display: flex; gap: 0.7rem; flex-wrap: wrap; align-items: center; }
.search, .status-filter { padding: 0.5rem 0.7rem; border-radius: 6px; background: var(--bg); color: var(--text); border: 1px solid var(--border-med); }
.search { flex: 1; min-width: 14rem; }
.link-btn { color: var(--accent); text-decoration: underline; font-size: var(--fs-body); }
.panes { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr); gap: 1.2rem; align-items: start; }
.pane { background: var(--surface); border: 1px solid var(--border-solid); border-radius: 10px; padding: 1rem; }
.pane--tree { max-height: 75vh; overflow: auto; }
.state-msg { color: var(--text-muted); font-size: var(--fs-md); }
.state-msg--error { color: var(--danger); }
.link { color: var(--accent); text-decoration: underline; margin-left: 0.4rem; }
@media (max-width: 860px) { .panes { grid-template-columns: 1fr; } .pane--tree { max-height: 50vh; } }
</style>
