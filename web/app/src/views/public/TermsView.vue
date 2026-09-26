<template>
  <InfoPage :eyebrow="t('legal.eyebrow')" :title="t('terms.title')">
    <p v-if="locale !== 'es'" class="note">{{ t('legal.translationNotice') }}</p>
    <p>{{ t('terms.intro') }}</p>

    <h2>{{ t('terms.responsibleUseHeading') }}</h2>
    <p>{{ t('terms.responsibleUse') }}</p>

    <h2>{{ t('terms.noWarrantyHeading') }}</h2>
    <p>{{ t('terms.noWarranty') }}</p>

    <p class="note">{{ t('terms.note') }}</p>
  </InfoPage>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import InfoPage from '@/components/shared/InfoPage.vue'

const { t, locale } = useI18n()
</script>
