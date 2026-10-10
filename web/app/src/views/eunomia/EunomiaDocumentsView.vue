<template>
  <div class="eunomia-page" data-module="eunomia">
    <StarBackground />
    <Topbar :title="'Eunomia'" :badge="t('eunomia.documents.title')" back-to="/eunomia/plantillas" :back-label="t('eunomia.templates.title')" />

    <main class="layout">
      <header class="head">
        <h1>{{ t('eunomia.documents.title') }}</h1>
        <p class="sub">{{ t('eunomia.documents.intro') }}</p>
      </header>

      <p v-if="loading" class="state-msg">{{ t('eunomia.frameworks.loading') }}</p>
      <p v-else-if="error" class="state-msg state-msg--error">{{ error }}</p>
      <p v-else-if="!documents.length" class="state-msg">{{ t('eunomia.documents.empty') }}</p>

      <ul v-else class="rows">
        <li v-for="item in documents" :key="item.id" class="row">
          <div class="row-main">
            <h2>{{ item.title }}</h2>
            <p class="meta">
              {{ item.format.toUpperCase() }} · {{ t(`eunomia.documents.status.${item.status}`) }}
              · {{ formatDate(item.createdAt) }} · {{ item.requestedByName }}
            </p>
          </div>
          <div class="row-actions">
            <button v-if="item.status === 'done'" type="button" class="btn btn--primary" @click="download(item)">
              {{ t('eunomia.documents.download') }}
            </button>
            <button type="button" class="btn btn--danger" @click="remove(item)">{{ t('eunomia.documents.delete') }}</button>
          </div>
        </li>
      </ul>
    </main>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Topbar from '@/components/shared/Topbar.vue'
import StarBackground from '@/components/shared/StarBackground.vue'
import { hasActiveDocuments } from '@/components/eunomia/templates'
import { formatDate } from '@/i18n/format'
import { useEunomiaStore } from '@/stores/eunomiaStore'
import { useToastStore } from '@/stores/toastStore'

const { t } = useI18n()
const store = useEunomiaStore()
const toast = useToastStore()

/** Cada cuánto se pregunta mientras algún documento sigue generándose. */
const POLL_MS = 3000

const documents = ref([])
const loading = ref(true)
const error = ref('')
let timer = null

/** Recarga la lista y mantiene el sondeo solo mientras haya algo en marcha. */
async function refresh() {
  const result = await store.loadDocuments()
  loading.value = false
  documents.value = result.documents
  error.value = result.message || ''
  clearTimeout(timer)
  if (result.ok && hasActiveDocuments(result.documents)) timer = setTimeout(refresh, POLL_MS)
}

async function download(item) {
  if (!(await store.downloadDocument(item))) toast.show(t('eunomia.documents.downloadFailed'), 'error')
}

async function remove(item) {
  if (await store.deleteDocument(item.id)) await refresh()
  else toast.show(t('eunomia.documents.deleteFailed'), 'error')
}

onMounted(refresh)
onBeforeUnmount(() => clearTimeout(timer))
</script>

<style scoped>
.eunomia-page { min-height: 100vh; background: var(--bg); padding-top: var(--topbar-h); position: relative; }
.layout { max-width: 900px; margin: 0 auto; padding: 2rem 1.5rem 4rem; display: flex; flex-direction: column; gap: 1.5rem; position: relative; z-index: 1; }
.head h1 { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-2xl); color: var(--text); }
.sub { color: var(--text-muted); margin-top: 0.4rem; max-width: 62ch; font-size: var(--fs-md); }
.rows { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 0.7rem; }
.row { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; background: var(--surface); border: 1px solid var(--border-solid); border-radius: 10px; padding: 1rem 1.2rem; }
.row h2 { font-size: var(--fs-lg); font-weight: 600; color: var(--text); }
.meta { color: var(--text-muted); font-size: var(--fs-body); margin-top: 0.2rem; }
.row-actions { display: flex; gap: 0.6rem; flex-wrap: wrap; }
.state-msg { color: var(--text-muted); font-size: var(--fs-md); }
.state-msg--error { color: var(--danger); }
.btn { font-family: var(--font-epic); font-size-adjust: var(--fsa-epic); font-size: var(--fs-body); font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; padding: 0.6rem 1.2rem; border-radius: 3px; border: 1px solid var(--border-med); color: var(--text-dim); transition: all var(--transition); }
.btn--primary { background: var(--accent-dim); border-color: var(--accent); color: var(--accent-bright); }
.btn--primary:hover { background: var(--accent); color: var(--on-accent); }
.btn--danger { border-color: var(--danger); color: var(--danger); }
.btn--danger:hover { background: var(--danger-dim); }
</style>
