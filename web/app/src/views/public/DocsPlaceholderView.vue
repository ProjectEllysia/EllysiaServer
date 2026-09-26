<template>
  <InfoPage :eyebrow="t('docs.eyebrow')" :title="t(`docs.${route.meta.docKey}.title`)">
    <p>{{ t(`docs.${route.meta.docKey}.intro`) }}</p>
    <p class="note">{{ t('docs.underConstruction') }}</p>
  </InfoPage>
</template>

<script setup>
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import InfoPage from '@/components/shared/InfoPage.vue'

const { t } = useI18n()
const route = useRoute()
</script>
