<template>
  <InfoPage eyebrow="Ellysia" :title="t('about.title')">
    <i18n-t keypath="about.intro" tag="p">
      <template #project><strong>{{ t('about.introProject') }}</strong></template>
      <template #notService><strong>{{ t('about.introNotService') }}</strong></template>
    </i18n-t>

    <h2>{{ t('about.contentsHeading') }}</h2>
    <ul>
      <li v-for="module in MODULES" :key="module">
        <strong>{{ MODULE_NAMES[module] }}</strong> — {{ t(`about.modules.${module}`) }}
      </li>
    </ul>

    <h2>{{ t('about.ideaHeading') }}</h2>
    <p>{{ t('about.idea') }}</p>

    <h2>{{ t('about.sourcesHeading') }}</h2>
    <p>{{ t('about.sourcesIntro') }}</p>
    <ul>
      <li>
        <strong>NVD</strong> {{ t('about.nvd') }}
        <em lang="en">{{ t('about.nvdNotice') }}</em>
      </li>
      <li><strong>KEV</strong> — {{ t('about.kev') }}</li>
      <li><strong>EPSS</strong> — {{ t('about.epss') }}</li>
    </ul>

    <i18n-t keypath="about.sourceCode" tag="p" class="note">
      <template #link>
        <a href="https://github.com/ProjectEllysia/EllysiaServer" target="_blank" rel="noopener noreferrer">GitHub</a>
      </template>
    </i18n-t>
  </InfoPage>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import InfoPage from '@/components/shared/InfoPage.vue'

const { t } = useI18n()

/** Módulos que se presentan, en el orden del panteón. */
const MODULES = ['themis', 'aegis', 'iris', 'acheron', 'hygeia']

/** Los nombres de los módulos son propios y no se traducen. */
const MODULE_NAMES = { themis: 'Themis', aegis: 'Aegis', iris: 'Iris', acheron: 'Acheron', hygeia: 'Hygeia' }
</script>
