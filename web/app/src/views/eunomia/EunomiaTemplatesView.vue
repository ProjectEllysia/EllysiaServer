<template>
  <div class="eunomia-page" data-module="eunomia">
    <StarBackground />
    <Topbar :title="'Eunomia'" :badge="t('eunomia.templates.title')" back-to="/eunomia/marcos" :back-label="t('eunomia.frameworks.title')" />

    <main class="layout">
      <header class="head">
        <h1>{{ t('eunomia.templates.title') }}</h1>
        <p class="sub">{{ t('eunomia.templates.intro') }}</p>
        <router-link to="/eunomia/documentos" class="docs-link">{{ t('eunomia.documents.title') }}</router-link>
      </header>

      <p v-if="loading" class="state-msg">{{ t('eunomia.frameworks.loading') }}</p>
      <p v-else-if="error" class="state-msg state-msg--error">{{ error }}</p>
      <ul v-else class="cards">
        <li v-for="item in templates" :key="item.key" class="card">
          <div class="card-main">
            <h2>{{ item.title }}</h2>
            <p class="meta">{{ item.summary }}</p>
            <p v-if="item.hasDraft" class="draft">{{ t('eunomia.templates.hasDraft') }}</p>
            <p v-if="!item.isFrameworkAdopted" class="meta">{{ t('eunomia.templates.frameworkNotAdopted') }}</p>
          </div>
          <router-link :to="`/eunomia/plantillas/${item.key}`" class="btn btn--primary">
            {{ t('eunomia.templates.fill') }}
          </router-link>
        </li>
      </ul>
    </main>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Topbar from '@/components/shared/Topbar.vue'
import StarBackground from '@/components/shared/StarBackground.vue'
import { useEunomiaStore } from '@/stores/eunomiaStore'

const { t } = useI18n()
const store = useEunomiaStore()
const templates = ref([])
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  const result = await store.loadTemplates()
  loading.value = false
  templates.value = result.templates
  error.value = result.message || ''
})
</script>

<style scoped>
.eunomia-page { min-height: 100vh; background: var(--bg); padding-top: var(--topbar-h); position: relative; }
.layout { max-width: 900px; margin: 0 auto; padding: 2rem 1.5rem 4rem; display: flex; flex-direction: column; gap: 1.5rem; position: relative; z-index: 1; }
.head h1 { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-2xl); color: var(--text); }
.sub { color: var(--text-muted); margin-top: 0.4rem; max-width: 62ch; font-size: var(--fs-md); }
.cards { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 0.7rem; }
.card { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; background: var(--surface); border: 1px solid var(--border-solid); border-radius: 10px; padding: 1rem 1.2rem; }
.card h2 { font-size: var(--fs-lg); font-weight: 600; color: var(--text); }
.meta { color: var(--text-muted); font-size: var(--fs-body); margin-top: 0.2rem; max-width: 60ch; }
.draft { color: var(--accent); font-size: var(--fs-body); margin-top: 0.2rem; }
.docs-link { display: inline-block; margin-top: 0.6rem; color: var(--accent); text-decoration: underline; font-size: var(--fs-md); }
.state-msg { color: var(--text-muted); font-size: var(--fs-md); }
.state-msg--error { color: var(--danger); }
.btn { font-family: var(--font-epic); font-size-adjust: var(--fsa-epic); font-size: var(--fs-body); font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; padding: 0.6rem 1.2rem; border-radius: 3px; border: 1px solid var(--border-med); color: var(--text-dim); text-decoration: none; transition: all var(--transition); }
.btn--primary { background: var(--accent-dim); border-color: var(--accent); color: var(--accent-bright); }
.btn--primary:hover { background: var(--accent); color: var(--on-accent); }
</style>
