<template>
  <section v-if="node.suggestions && node.suggestions.length" class="suggestions" :aria-label="t('eunomia.suggestions.title')">
    <h3>{{ t('eunomia.suggestions.title') }}</h3>
    <p class="muted">{{ t('eunomia.suggestions.intro') }}</p>
    <ul>
      <li v-for="item in node.suggestions" :key="`${item.frameworkKey}:${item.identifier}`">
        <p class="line">
          <strong>{{ item.frameworkKey.toUpperCase() }} · {{ item.identifier }}</strong>
          {{ item.title }}
        </p>
        <p class="meta">
          {{ t(`eunomia.suggestions.coverage.${item.coverage}`) }}
          · {{ t(`eunomia.status.${item.status}`) }}
        </p>
        <ul v-if="item.evidence.length && canEdit" class="evidence">
          <li v-for="evidence in item.evidence" :key="evidence.id">
            {{ evidence.title }}
            <button type="button" class="link-btn" :disabled="busy" @click="link(evidence)">
              {{ t('eunomia.suggestions.linkHere') }}
            </button>
          </li>
        </ul>
      </li>
    </ul>
  </section>
</template>

<script setup>
/**
 * Lo que el usuario ya tiene hecho en los otros marcos adoptados y cubre, total o parcialmente,
 * este control. Son sugerencias: nada se traslada solo. Enlazar una evidencia sugerida crea un
 * enlace, sin copiar ningún fichero.
 */
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useEunomiaStore } from '@/stores/eunomiaStore'
import { useToastStore } from '@/stores/toastStore'

const props = defineProps({
  node: { type: Object, required: true },
  framework: { type: String, required: true },
  canEdit: { type: Boolean, default: true },
})
const emit = defineEmits(['changed'])
const { t } = useI18n()
const store = useEunomiaStore()
const toast = useToastStore()
const busy = ref(false)

/** Enlaza una evidencia del otro marco con este control. */
async function link(evidence) {
  busy.value = true
  const result = await store.setEvidenceLink(evidence.id, props.framework, props.node.identifier, true)
  busy.value = false
  if (!result.ok) { toast.show(result.message, 'error'); return }
  emit('changed')
}
</script>

<style scoped>
.suggestions { padding-top: 1rem; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 0.6rem; }
h3 { font-size: var(--fs-md); font-weight: 600; color: var(--text); }
.muted, .meta { color: var(--text-muted); font-size: var(--fs-body); }
ul { list-style: none; padding: 0; display: flex; flex-direction: column; gap: 0.7rem; }
.line { color: var(--text-dim); font-size: var(--fs-md); }
.evidence { margin-top: 0.3rem; padding-inline-start: 1rem; font-size: var(--fs-body); color: var(--text-dim); }
.link-btn { color: var(--accent); text-decoration: underline; margin-left: 0.5rem; }
</style>
