<template>
  <div class="eunomia-page" data-module="eunomia">
    <StarBackground />
    <Topbar :title="'Eunomia'" :badge="t('eunomia.registers.title')" back-to="/eunomia/marcos" :back-label="t('eunomia.frameworks.title')" />

    <main class="layout">
      <header class="head">
        <h1>{{ t('eunomia.registers.title') }}</h1>
        <p class="sub">{{ t('eunomia.registers.intro') }}</p>
      </header>

      <p v-if="loading" class="state-msg">{{ t('eunomia.frameworks.loading') }}</p>
      <p v-else-if="error" class="state-msg state-msg--error">{{ error }}</p>
      <ul v-else class="cards">
        <li v-for="item in registers" :key="item.key" class="card">
          <div class="card-main">
            <span class="card-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 3v18M7 21h10M5 7h14M5 7l-2.5 5a3 3 0 0 0 5 0L5 7zM19 7l-2.5 5a3 3 0 0 0 5 0L19 7z"/></svg></span>
            <div class="card-text">
            <h2>{{ item.title }}</h2>
            <p class="meta">{{ item.summary }}</p>
            <p class="meta">{{ t('eunomia.registers.recordCount', { count: item.recordCount }, item.recordCount) }}</p>
          </div>
          </div>
          <div class="card-actions">
            <router-link :to="`/eunomia/registros/${item.key}`" class="btn btn--primary">{{ t('eunomia.registers.open') }}</router-link>
          </div>
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
const registers = ref([])
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  const result = await store.loadRegisters()
  loading.value = false
  registers.value = result.registers
  error.value = result.message || ''
})
</script>

<style scoped>
.eunomia-page { min-height: 100vh; background: var(--bg); padding-top: var(--topbar-h); position: relative; }
.layout { max-width: 900px; margin: 0 auto; padding: 2rem 1.5rem 4rem; display: flex; flex-direction: column; gap: 1.5rem; position: relative; z-index: 1; }
.head h1 { font-family: var(--font-display); font-size-adjust: var(--fsa-display); font-size: var(--fs-2xl); color: var(--text); }
.sub { color: var(--text-muted); margin-top: 0.4rem; max-width: 62ch; font-size: var(--fs-md); }
.cards { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 0.7rem; }
.card {
  display: flex; flex-direction: column; gap: 0.9rem;
  background: linear-gradient(180deg, var(--surface) 0%, var(--surface-2) 220%);
  border: 1px solid var(--border-solid); border-radius: 12px; padding: 1.1rem 1.3rem;
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.14);
  transition: border-color 0.3s var(--ease-settle), box-shadow 0.3s var(--ease-settle), transform 0.3s var(--ease-settle);
}
.card:hover { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent-dim), 0 14px 34px rgba(0, 0, 0, 0.2); transform: translateY(-1px); }
.card-main { display: flex; gap: 0.9rem; align-items: flex-start; flex: 1; }
.card-text { flex: 1; min-width: 0; }
.card-mark { width: 40px; height: 40px; border-radius: 50%; flex: none; display: grid; place-items: center; color: var(--accent); background: var(--accent-dim); border: 1px solid var(--accent); }
.card-mark svg { width: 21px; height: 21px; }
.card-actions { display: flex; gap: 0.6rem; flex-wrap: wrap; justify-content: flex-end; margin-top: auto; }
.card h2 { font-size: var(--fs-lg); font-weight: 600; color: var(--text); }
.meta { color: var(--text-muted); font-size: var(--fs-body); margin-top: 0.2rem; max-width: 60ch; }
.state-msg { color: var(--text-muted); font-size: var(--fs-md); }
.state-msg--error { color: var(--danger); }
.btn { font-family: var(--font-epic); font-size-adjust: var(--fsa-epic); font-size: var(--fs-body); font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; padding: 0.6rem 1.2rem; border-radius: 3px; border: 1px solid var(--border-med); color: var(--text-dim); text-decoration: none; transition: all var(--transition); }
.btn--primary { background: var(--accent-dim); border-color: var(--accent); color: var(--accent-bright); }
.btn--primary:hover { background: var(--accent); color: var(--on-accent); }
@media (prefers-reduced-motion: reduce) {
  .card, .row, .btn { transition: none !important; }
  .card:hover, .row:hover { transform: none; }
}
</style>
