<template>
  <span class="count-up">{{ text }}</span>
</template>

<script setup>
import { computed } from 'vue'
import { useCountUp } from '@/composables/useMotion'
import { formatNumber } from '@/i18n/format'

/**
 * Número que sube hasta su valor al aparecer y se desplaza cuando cambia, en vez de saltar.
 *
 * Con movimiento reducido enseña el valor directamente. Ocupa el ancho de sus cifras,
 * así que conviene un tipo de letra de cifras tabulares (`font-variant-numeric`) si el
 * ancho no debe bailar.
 */
const props = defineProps({
  /** Valor al que llega. */
  value: { type: Number, required: true },
  /** Decimales que se enseñan. */
  decimals: { type: Number, default: 0 },
  /** Milisegundos que dura el desplazamiento. */
  duration: { type: Number, default: 700 },
  /** Cómo se escribe el número de cada instante; por defecto, con el formato del idioma activo. */
  format: { type: Function, default: null },
})

const displayed = useCountUp(() => props.value, { duration: props.duration, decimals: props.decimals })
const text = computed(() => (
  props.format
    ? props.format(displayed.value)
    : formatNumber(displayed.value, { minimumFractionDigits: props.decimals, maximumFractionDigits: props.decimals })
))
</script>

<style scoped>
.count-up { font-variant-numeric: tabular-nums; }
</style>
