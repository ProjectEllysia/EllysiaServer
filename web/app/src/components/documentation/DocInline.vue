<template>
  <template v-for="(segment, index) in segments" :key="index">
    <strong v-if="segment.kind === 'strong'">{{ segment.value }}</strong>
    <code v-else-if="segment.kind === 'code'">{{ segment.value }}</code>
    <template v-else>{{ segment.value }}</template>
  </template>
</template>

<script setup>
import { computed } from 'vue'
import { parseInlineText } from '@/content/documentation/inline'

/**
 * Pinta un texto de la documentación con su formato en línea (negrita y
 * código), como nodos y no como HTML. Ver `content/documentation/inline.js`.
 */
const props = defineProps({
  /** Texto con las marcas `**…**` y `` `…` ``. */
  text: { type: String, required: true },
})

const segments = computed(() => parseInlineText(props.text))
</script>
