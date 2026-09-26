<template>
  <div class="config-page">
    <StarBackground />
    <Topbar :title="t('configView.title')" />

    <main class="main">
      <div v-if="store.loading" class="loading-block">
        <div class="skeleton skeleton--lg"></div>
      </div>

      <div v-else class="config-layout">
        <div class="config-nav-column">
          <aside class="config-nav">
            <nav>
              <template v-for="g in navGroups" :key="g.id">
                <span class="nav-group-label">{{ t(`configView.nav.${g.id}`) }}</span>
                <a v-for="s in g.items" :key="s.id"
                  :class="['nav-link', { active: activeSection === s.id }]"
                  href="#" @click.prevent="scrollTo(s.id)">
                  <span class="nav-icon" v-html="s.icon"></span>
                  <span class="nav-label">{{ t(s.labelKey) }}</span>
                </a>
              </template>
            </nav>
          </aside>
        </div>

        <form class="config-form" @submit.prevent="handleSave">
          <section id="section-launch" class="section">
            <div class="section-head"><h2>{{ t('configView.lanzamiento') }}</h2><p class="section-desc">{{ t('configView.queFuncionesEstanAbiertasAl') }}</p></div>
            <div class="section-body">
              <i18n-t keypath="configView.enS1TodasLasFunciones" tag="p" class="field-hint">
                <template #s1><strong>{{ t('configView.vistaPrevia') }}</strong></template>
                <template #s2><strong>{{ t('configView.abiertoAlPublico') }}</strong></template>
              </i18n-t>
              <div class="cfg-grid">
                <div class="form-group">
                  <label>{{ t('configView.modo') }}</label>
                  <select v-model="store.configFlat['general.launch.mode']" class="inp">
                    <option value="preview">{{ t('configView.vistaPrevia2') }}</option>
                    <option value="public">{{ t('configView.abiertoAlPublico2') }}</option>
                  </select>
                </div>
              </div>
              <ul class="launch-surfaces" :class="{ 'launch-surfaces--inactive': isLaunchPreview }">
                <li v-for="surface in LAUNCH_SURFACES" :key="surface.key" class="launch-surface">
                  <label class="launch-switch">
                    <input
                      v-model="store.configFlat[`general.launch.surfaces.${surface.key}`]"
                      type="checkbox" :disabled="isLaunchPreview"
                    />
                    <span class="launch-name">{{ t(`configView.surfaces.${surface.key}.label`) }}</span>
                  </label>
                  <span class="field-hint">{{ t(`configView.surfaces.${surface.key}.covers`) }} {{ t('configView.beforeOpening', { unlocks: t(`configView.surfaces.${surface.key}.unlocks`) }) }}</span>
                </li>
              </ul>
              <p v-if="isLaunchPreview" class="field-hint">{{ t('configView.switchesIgnored') }}</p>
            </div>
          </section>

          <section id="section-general" class="section">
            <div class="section-head section-head--row">
              <div><h2>{{ t('configView.general') }}</h2><p class="section-desc">{{ t('configView.directoriosDelSistemaYAlta') }}</p></div>
              <span class="version-chip" :title="t('configView.appVersion')">v{{ store.configFlat['appVersion'] }}</span>
            </div>
            <div class="section-body">
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.tech.temp') }}</label><input v-model="store.configFlat['general.directories.tempdir']" type="text" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.tech.logs') }}</label><input v-model="store.configFlat['general.directories.logdir']" type="text" class="inp" /></div>
                <div class="form-group">
                  <label>{{ t('configView.conservacionDelRegistroDeActividad') }}</label>
                  <input v-model.number="store.configFlat['general.logs.retentionDays']" type="number" min="1" max="365" class="inp" />
                  <span class="field-hint">{{ t('configView.cadaNocheSeArchivaEl') }}</span>
                </div>
                <div class="form-group">
                  <label>{{ t('configView.idiomaDeLaPlataforma') }}</label>
                  <select v-model="store.configFlat['general.localization.defaultLanguage']" class="inp">
                    <option v-for="option in LOCALE_OPTIONS" :key="option.code" :value="option.code">{{ option.name }}</option>
                  </select>
                  <span class="field-hint">{{ t('configView.elDeQuienNoHa') }}</span>
                </div>
              </div>
              <p class="field-hint">{{ t('configView.plazosDeLosEnlacesQue') }}</p>
              <div class="cfg-grid">
                <div class="form-group">
                  <label>{{ t('configView.vigenciaDelEnlaceDeVerificacion') }}</label>
                  <input v-model.number="store.configFlat['general.registration.verificationTtlHours']" type="number" min="1" max="720" class="inp" />
                </div>
                <div class="form-group">
                  <label>{{ t('configView.vigenciaDelEnlaceDeRecuperacion') }}</label>
                  <input v-model.number="store.configFlat['general.registration.passwordResetTtlMinutes']" type="number" min="5" max="1440" class="inp" />
                </div>
                <div class="form-group">
                  <label>{{ t('configView.vigenciaDeLaInvitacionA') }}</label>
                  <input v-model.number="store.configFlat['general.registration.invitationTtlHours']" type="number" min="1" max="2160" class="inp" />
                </div>
              </div>
            </div>
          </section>

          <section id="section-security" class="section">
            <div class="section-head"><h2>{{ t('configView.seguridad') }}</h2><p class="section-desc">{{ t('configView.contrasenasSesionYSegundoFactor') }}</p></div>
            <div class="section-body">
              <p class="field-hint">{{ t('configView.parametrosDeCosteDeArgon2id') }}</p>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.iteracionesTimeCost') }}</label><input v-model.number="store.configFlat['general.security.argon2.time_cost']" type="number" min="1" max="20" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.memoriaKib') }}</label><input v-model.number="store.configFlat['general.security.argon2.memory_cost']" type="number" min="8192" step="1024" class="inp" /><span class="field-hint">{{ t('configView.65536Kib64MibPor') }}</span></div>
                <div class="form-group"><label>{{ t('configView.paralelismoHilos') }}</label><input v-model.number="store.configFlat['general.security.argon2.parallelism']" type="number" min="1" max="16" class="inp" /></div>
              </div>

              <h3 class="subsection-title">{{ t('configView.sesionJwt') }}</h3>
              <i18n-t keypath="configView.cuantoViveUnaSesionEl" tag="p" class="field-hint">
                <template #c1><code>JWT_SECRET_KEY</code></template>
                <template #c2><code>JWT_ALGORITHM</code></template>
                <template #c3><code>ACCESS_TOKEN_EXPIRY_MINUTES</code></template>
                <template #c4><code>REFRESH_TOKEN_EXPIRY_DAYS</code></template>
              </i18n-t>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.algoritmoDeFirma') }}</label>
                  <select v-model="store.configFlat['general.security.jwt.algorithm']" class="inp sel">
                    <option v-for="alg in jwtAlgorithms" :key="alg" :value="alg">{{ alg }}</option>
                  </select>
                  <span class="field-hint">{{ t('configView.soloLaFamiliaHsLa') }}</span>
                </div>
                <div class="form-group"><label>{{ t('configView.vigenciaDelTokenDeAcceso') }}</label><input v-model.number="store.configFlat['general.security.jwt.access_token_expiry_minutes']" type="number" min="1" max="1440" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.vigenciaDelTokenDeRefresco') }}</label><input v-model.number="store.configFlat['general.security.jwt.refresh_token_expiry_days']" type="number" min="1" max="365" class="inp" /></div>
              </div>

              <h3 class="subsection-title">{{ t('configView.segundoFactorTotp') }}</h3>
              <p class="field-hint">{{ t('configView.elEmisorEsElNombre') }}</p>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.emisor') }}</label><input v-model="store.configFlat['general.security.mfa.issuer']" type="text" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.vigenciaDelRetoMin') }}</label><input v-model.number="store.configFlat['general.security.mfa.challenge_expiry_minutes']" type="number" min="1" max="60" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.intentosPorReto') }}</label><input v-model.number="store.configFlat['general.security.mfa.max_challenge_attempts']" type="number" min="1" max="20" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.codigosDeRecuperacion') }}</label><input v-model.number="store.configFlat['general.security.mfa.recovery_codes_count']" type="number" min="1" max="50" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.recordatorioDeActivacionDias') }}</label><input v-model.number="store.configFlat['general.security.mfa.notice_interval_days']" type="number" min="1" max="365" class="inp" /><span class="field-hint">{{ t('configView.cadaCuantoSeLeRecuerda') }}</span></div>
              </div>
            </div>
          </section>

          <section id="section-database" class="section">
            <div class="section-head"><h2>{{ t('configView.baseDeDatos') }}</h2><p class="section-desc">{{ t('configView.conexionPostgresqlYPoolDe') }}</p></div>
            <div class="section-body">
              <i18n-t keypath="configView.lasCredencialesVivenEnEl" tag="p" class="field-hint">
                <template #c1><code>{{ '.env' }}</code></template>
              </i18n-t>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.nivelDeAislamiento') }}</label>
                  <select v-model="store.configFlat['infrastructure.database.isolation_level']" class="inp sel">
                    <option v-for="lvl in isolationLevels" :key="lvl" :value="lvl">{{ lvl }}</option>
                  </select>
                </div>
                <div class="form-group"><label>{{ t('configView.tamanoDelPool') }}</label><input v-model.number="store.configFlat['infrastructure.database.pool_size']" type="number" min="1" max="100" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.conexionesExtraOverflow') }}</label><input v-model.number="store.configFlat['infrastructure.database.max_overflow']" type="number" min="0" max="100" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.timeoutDelPoolS') }}</label><input v-model.number="store.configFlat['infrastructure.database.pool_timeout']" type="number" min="1" max="300" class="inp" /></div>
              </div>
            </div>
          </section>

          <section id="section-redis" class="section">
            <div class="section-head"><h2>{{ t('configView.tech.redis') }}</h2><p class="section-desc">{{ t('configView.backendDeLaColaDe') }}</p></div>
            <div class="section-body">
              <i18n-t keypath="configView.laContrasenaSeTomaDe" tag="p" class="field-hint">
                <template #c1><code>REDIS_PASSWORD</code></template>
                <template #c2><code>{{ '.env' }}</code></template>
                <template #c3><code>REDIS_HOST</code></template>
                <template #c4><code>REDIS_PORT</code></template>
                <template #c5><code>REDIS_DB</code></template>
              </i18n-t>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.tech.host') }}</label><input v-model="store.configFlat['infrastructure.redis.host']" type="text" class="inp mono" /></div>
                <div class="form-group"><label>{{ t('configView.puerto') }}</label><input v-model.number="store.configFlat['infrastructure.redis.port']" type="number" min="1" max="65535" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.baseDeDatosDb') }}</label><input v-model.number="store.configFlat['infrastructure.redis.db']" type="number" min="0" max="15" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.timeoutDeConexionS') }}</label><input v-model.number="store.configFlat['infrastructure.redis.socket_connect_timeout']" type="number" min="1" max="60" class="inp" /></div>
              </div>
            </div>
          </section>

          <section id="section-taskqueue" class="section">
            <div class="section-head"><h2>{{ t('configView.tech.taskqueue') }}</h2><p class="section-desc">{{ t('configView.colaDeTareasEnSegundo') }}</p></div>
            <div class="section-body">
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.tech.maxWorkers') }}</label><input v-model.number="store.configFlat['infrastructure.taskqueue.max_workers']" type="number" min="1" max="32" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.historialTtlS') }}</label><input v-model.number="store.configFlat['infrastructure.taskqueue.history_ttl_seconds']" type="number" min="60" max="86400" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.maxItemsEnHistorial') }}</label><input v-model.number="store.configFlat['infrastructure.taskqueue.history_max_items']" type="number" min="10" max="1000" class="inp" /></div>
              </div>
            </div>
          </section>

          <section id="section-ai" class="section">
            <div class="section-head"><h2>{{ t('configView.ia') }}</h2><p class="section-desc">{{ t('configView.estrategiaDeLosModelosDe') }}</p></div>
            <div class="section-body">
              <i18n-t keypath="configView.eligeQueProveedorGeneraEl" tag="p" class="field-hint">
                <template #c1><code>{{ '.env' }}</code></template>
              </i18n-t>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.estrategiaPorDefecto') }}</label>
                  <select v-model="store.configFlat['tools.scribe.defaultStrategy']" class="inp sel">
                    <option v-for="s in aiStrategies" :key="s.value" :value="s.value">{{ s.label }}</option>
                  </select>
                </div>
                <div v-for="m in aiModules" :key="m.key" class="form-group"><label>{{ m.label }}</label>
                  <select v-model="store.configFlat[`tools.scribe.modules.${m.key}`]" class="inp sel">
                    <option v-for="s in aiStrategies" :key="s.value" :value="s.value">{{ s.label }}</option>
                  </select>
                </div>
              </div>

              <h3 class="subsection-title">{{ t('configView.modeloDeCadaProveedor') }}</h3>
              <p class="field-hint">{{ t('configView.laListaSaleDePreguntarle') }}</p>
              <div class="cfg-grid">
                <ModelPicker
                  v-for="s in aiStrategies" :key="s.value"
                  v-model="store.configFlat[`tools.scribe.strategies.${s.value}.model`]"
                  :label="s.label" :env-hint="s.envVar"
                  :catalog="store.aiModels[s.value]" :loading="store.aiModelsLoading" />
              </div>

              <h3 class="subsection-title">{{ t('configView.limitesYReintentos') }}</h3>
              <p class="field-hint">{{ t('configView.elTopeDeTokensRechaza') }}</p>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.tokensMaximosDelPrompt') }}</label><input v-model.number="store.configFlat['tools.scribe.maxInputTokens']" type="number" min="1000" max="200000" step="1000" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.intentosPorGeneracion') }}</label><input v-model.number="store.configFlat['tools.scribe.resilience.maxRetries']" type="number" min="1" max="10" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.baseDeLaEsperaEntre') }}</label><input v-model.number="store.configFlat['tools.scribe.resilience.retryBaseSeconds']" type="number" min="1" max="10" step="0.1" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.fallosQueAbrenElCorte') }}</label><input v-model.number="store.configFlat['tools.scribe.resilience.breakerThreshold']" type="number" min="1" max="20" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.duracionDelCorteS') }}</label><input v-model.number="store.configFlat['tools.scribe.resilience.breakerTimeoutSeconds']" type="number" min="5" max="3600" class="inp" /></div>
              </div>

              <h3 class="subsection-title">{{ t('configView.timeoutDeCadaProveedorS') }}</h3>
              <p class="field-hint">{{ t('configView.unModeloLocalTardaMucho') }}</p>
              <div class="cfg-grid">
                <div v-for="s in aiStrategies" :key="s.value" class="form-group">
                  <label>{{ s.label }}</label>
                  <input v-model.number="store.configFlat[`tools.scribe.strategies.${s.value}.timeout`]" type="number" min="10" max="1800" class="inp" />
                </div>
              </div>
            </div>
          </section>

          <section id="section-herald" class="section">
            <div class="section-head"><h2>{{ t('configView.correo') }}</h2><p class="section-desc">{{ t('configView.relayDeSalidaYMarca') }}</p></div>
            <div class="section-body">
              <i18n-t keypath="configView.porAquiSalenLasCampanas" tag="p" class="field-hint">
                <template #c1><code>SMTP_USERNAME</code></template>
                <template #c2><code>SMTP_PASSWORD</code></template>
                <template #c3><code>{{ '.env' }}</code></template>
              </i18n-t>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.estrategiaPorDefecto') }}</label>
                  <select v-model="store.configFlat['tools.herald.defaultStrategy']" class="inp sel">
                    <option v-for="s in mailStrategies" :key="s.value" :value="s.value">{{ s.label }}</option>
                  </select>
                </div>
                <div v-for="m in mailModules" :key="m.key" class="form-group"><label>{{ t(`configView.mailModules.${m.key}`) }}</label>
                  <select v-model="store.configFlat[`tools.herald.modules.${m.key}`]" class="inp sel">
                    <option v-for="s in mailStrategies" :key="s.value" :value="s.value">{{ s.label }}</option>
                  </select>
                </div>
              </div>

              <h3 class="subsection-title">{{ t('configView.relaySmtp') }}</h3>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.tech.host') }}</label><input v-model="store.configFlat['tools.herald.strategies.smtp.host']" type="text" class="inp mono" /></div>
                <div class="form-group"><label>{{ t('configView.puerto') }}</label><input v-model.number="store.configFlat['tools.herald.strategies.smtp.port']" type="number" min="1" max="65535" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.direccionDelRemitente') }}</label><input v-model="store.configFlat['tools.herald.strategies.smtp.fromAddress']" type="text" class="inp mono" /></div>
                <div class="form-group"><label>{{ t('configView.nombreDelRemitente') }}</label><input v-model="store.configFlat['tools.herald.strategies.smtp.fromName']" type="text" class="inp" /></div>
              </div>
              <div class="cfg-row"><label class="toggle-row"><input v-model="store.configFlat['tools.herald.strategies.smtp.useTls']" type="checkbox" class="toggle" /><span>{{ t('configView.cifrarConStarttls') }}</span></label></div>

              <h3 class="subsection-title">{{ t('configView.marcaDeLosCorreos') }}</h3>
              <p class="field-hint">{{ t('configView.loQuePintanLasPlantillas') }}</p>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.nombreDelProducto') }}</label><input v-model="store.configFlat['tools.herald.branding.productName']" type="text" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.colorDeAcento') }}</label><input v-model="store.configFlat['tools.herald.branding.accentColor']" type="color" class="inp color-inp" /></div>
                <div class="form-group"><label>{{ t('configView.urlDelLogotipo') }}</label><input v-model="store.configFlat['tools.herald.branding.logoUrl']" type="text" class="inp mono" /><span class="field-hint">{{ t('configView.vacioSinLogotipo') }}</span></div>
                <div class="form-group"><label>{{ t('configView.correoDeSoporte') }}</label><input v-model="store.configFlat['tools.herald.branding.supportEmail']" type="text" class="inp mono" /></div>
              </div>
              <div class="form-group"><label>{{ t('configView.notaDelPie') }}</label><input v-model="store.configFlat['tools.herald.branding.footerNote']" type="text" class="inp" /></div>
              <div class="form-group"><label>{{ t('configView.directorioDePlantillas') }}</label><input v-model="store.configFlat['tools.herald.templatesDir']" type="text" class="inp mono" /><span class="field-hint">{{ t('configView.vacioLasPlantillasQueTrae') }}</span></div>
            </div>
          </section>

          <section id="section-iris" class="section">
            <div class="section-head"><h2>Iris</h2><p class="section-desc">{{ t('configView.umbralesDeAnalisisDeCabeceras') }}</p></div>
            <div class="section-body">
              <p class="field-hint">{{ t('configView.puntuacionDeAutenticidadDeUn') }}</p>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.umbralLegitimo') }}</label><input v-model.number="store.configFlat['features.iris.legitimateThreshold']" type="number" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.umbralSospechoso') }}</label><input v-model.number="store.configFlat['features.iris.suspiciousThreshold']" type="number" class="inp" /></div>
                <div class="form-group">
                  <label>{{ t('configView.perfilDeSensibilidad') }}</label>
                  <select v-model="store.configFlat['features.iris.sensitivityProfile']" class="inp sel">
                    <option value="strict">{{ t('configView.estricto') }}</option>
                    <option value="balanced">{{ t('configView.equilibrado') }}</option>
                    <option value="lenient">{{ t('configView.permisivo') }}</option>
                  </select>
                  <span class="field-hint">{{ t('configView.estrictoSubeLosDosUmbrales') }}</span>
                </div>
                <div class="form-group"><label>{{ t('configView.cabecerasMinimas') }}</label><input v-model.number="store.configFlat['features.iris.minHeaders']" type="number" min="0" max="50" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.tamanoMaxDelMensajeBytes') }}</label><input v-model.number="store.configFlat['features.iris.maxMessageBytes']" type="number" min="1024" step="1024" class="inp" /><span class="field-hint">{{ t('configView.1048576010Mib') }}</span></div>
              </div>
              <h3 class="subsection-title">{{ t('configView.buzonesVigilados') }}</h3>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.conexionesPorUsuario') }}</label><input v-model.number="store.configFlat['features.iris.maxConnectionsPerUser']" type="number" min="1" max="50" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.correosIngeridosAlDia') }}</label><input v-model.number="store.configFlat['features.iris.maxIngestedPerDay']" type="number" min="1" max="10000" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.intervaloDeSondeoMin') }}</label><input v-model.number="store.configFlat['features.iris.pollIntervalMinutes']" type="number" min="1" max="1440" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.directorioDeSalida') }}</label><input v-model="store.configFlat['features.iris.directories.output']" type="text" class="inp" /></div>
              </div>
              <h3 class="subsection-title">{{ t('configView.resumenConIa') }}</h3>
              <PromptField v-model="store.configFlat['features.iris.prompts.summary.system']" :label="t('config.scanner.systemPrompt')" :title="t('config.scanner.systemPromptTitle', { name: 'Iris' })" />
              <PromptField v-model="store.configFlat['features.iris.prompts.summary.userTemplate']" :label="t('config.scanner.userTemplate')" :title="t('config.scanner.userTemplateTitle', { name: 'Iris' })" />
            </div>
          </section>

          <section id="section-themis" class="section">
            <div class="section-head"><h2>Themis</h2><p class="section-desc">{{ t('configView.escanerDeRedAnalisisWeb') }}</p></div>
            <div class="section-body">
              <div class="cfg-row"><label class="toggle-row"><input v-model="store.configFlat['features.themis.enabled']" type="checkbox" class="toggle" /><span>{{ t('configView.habilitado') }}</span></label></div>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.directorioDeSalidaPdfs') }}</label><input v-model="store.configFlat['features.themis.directories.output']" type="text" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.directorioCsv') }}</label><input v-model="store.configFlat['features.themis.directories.csv']" type="text" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.directorioDeRecursos') }}</label><input v-model="store.configFlat['features.themis.directories.resources']" type="text" class="inp" /></div>
              </div>
              <div class="cfg-row"><label class="toggle-row"><input v-model="store.configFlat['features.themis.areLocalIpsAllowed']" type="checkbox" class="toggle" /><span>{{ t('configView.permitirIpsLocales') }}</span></label></div>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.carpetaPorDefecto') }}</label><input v-model="store.configFlat['features.themis.folders.defaultFolderName']" type="text" class="inp" /><span class="field-hint">{{ t('configView.nombreDeLaCarpetaVirtual') }}</span></div>
                <div class="form-group"><label>{{ t('configView.escaneosEnEstadisticas') }}</label><input v-model.number="store.configFlat['features.themis.history.maxScans']" type="number" min="1" max="100" class="inp" /><span class="field-hint">{{ t('configView.escaneosRecientesQueSePromedian') }}</span></div>
                <div class="form-group"><label>{{ t('configView.vigenciaDelRiesgoAceptadoDias') }}</label><input v-model.number="store.configFlat['features.themis.acceptedRiskDays']" type="number" min="1" max="3650" class="inp" /><span class="field-hint">{{ t('configView.pasadoEsePlazoUnHallazgo') }}</span></div>
                <div class="form-group"><label>{{ t('configView.plazoPorDefectoDeUn') }}</label><input v-model.number="store.configFlat['features.themis.taskDefaults.timeout']" type="number" min="60" max="604800" class="inp" /><span class="field-hint">{{ t('configView.loQueEsperaLaCola') }}</span></div>
              </div>
              <h3 class="subsection-title">{{ t('configView.verificacionDeAccesibilidadDelHost') }}</h3>
              <div class="cfg-grid">
                <div class="form-group"><label class="toggle-row"><input v-model="store.configFlat['features.themis.hostReachabilityCheck.enabled']" type="checkbox" class="toggle" /><span>{{ t('configView.habilitado') }}</span></label></div>
                <div class="form-group"><label>{{ t('configView.timeoutS') }}</label><input v-model.number="store.configFlat['features.themis.hostReachabilityCheck.timeout']" type="number" step="0.5" min="0.5" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.puerto') }}</label><input v-model.number="store.configFlat['features.themis.hostReachabilityCheck.port']" type="number" min="1" max="65535" class="inp" /></div>
              </div>
              <h3 class="subsection-title">{{ t('configView.tech.traceroute') }}</h3>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.validezDeCacheH') }}</label><input v-model.number="store.configFlat['features.themis.traceroute.cacheHours']" type="number" min="1" max="720" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.saltosMaximos') }}</label><input v-model.number="store.configFlat['features.themis.traceroute.maxHops']" type="number" min="1" max="64" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.timeoutS') }}</label><input v-model.number="store.configFlat['features.themis.traceroute.timeout']" type="number" min="1" max="600" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.reintentoSiFallaMin') }}</label><input v-model.number="store.configFlat['features.themis.traceroute.retryFailedMinutes']" type="number" min="1" max="1440" class="inp" /></div>
              </div>
              <h3 class="subsection-title">{{ t('configView.baseDeConocimiento') }}</h3>
              <p class="field-hint">{{ t('configView.elEspejoLocalDeNvd') }}</p>
              <div class="cfg-row"><label class="toggle-row"><input v-model="store.configFlat['features.themis.kb.enabled']" type="checkbox" class="toggle" /><span>{{ t('configView.sincronizacionActiva') }}</span></label></div>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.cronDeSincronizacion') }}</label><input v-model="store.configFlat['features.themis.kb.syncCron']" type="text" class="inp mono" /><span class="field-hint">{{ t('configView.formatoCronDeCincoCampos') }}</span></div>
                <div class="form-group"><label>{{ t('configView.ventanaPedidaANvdDias') }}</label><input v-model.number="store.configFlat['features.themis.kb.nvdWindowDays']" type="number" min="1" max="120" class="inp" /><span class="field-hint">{{ t('configView.cuantoHistoricoSePideEn') }}</span></div>
                <div v-for="feed in kbFeeds" :key="feed.key" class="form-group">
                  <label>{{ t('configView.maxAge', { feed: feed.label }) }}</label>
                  <input v-model.number="store.configFlat[`features.themis.kb.maxAgeDays.${feed.key}`]" type="number" min="1" max="365" class="inp" />
                </div>
              </div>
              <div class="cfg-grid">
                <div v-for="source in kbSourcePaths" :key="source.path" class="form-group">
                  <label>{{ t('configView.source', { source: source.label }) }}</label>
                  <input v-model="store.configFlat[source.path]" type="text" class="inp mono" />
                </div>
              </div>
            </div>
            <div class="scanner-grid">
              <ScannerCard name="Nmap" icon="scan" :flat="store.configFlat" prefix="features.themis.scanners.nmap" />
              <ScannerCard name="Nikto" icon="web" :flat="store.configFlat" prefix="features.themis.scanners.nikto" />
              <ScannerCard name="Nuclei" icon="vuln" :flat="store.configFlat" prefix="features.themis.scanners.nuclei">
                <div class="cfg-grid cfg-grid--tight">
                  <div class="form-group"><label>{{ t('configView.binario') }}</label><input v-model="store.configFlat['features.themis.scanners.nuclei.binaryPath']" type="text" class="inp mono" /></div>
                  <div class="form-group"><label>{{ t('configView.directorioDePlantillas') }}</label><input v-model="store.configFlat['features.themis.scanners.nuclei.templatesDir']" type="text" class="inp mono" /><span class="field-hint">{{ t('configView.vacioLasQueTraeEl') }}</span></div>
                  <div class="form-group"><label>{{ t('configView.versionDePlantillas') }}</label><input v-model="store.configFlat['features.themis.scanners.nuclei.templatesVersion']" type="text" class="inp mono" /></div>
                  <div class="form-group"><label>{{ t('configView.peticionesPorSegundo') }}</label><input v-model.number="store.configFlat['features.themis.scanners.nuclei.rateLimit']" type="number" min="1" max="1000" class="inp" /></div>
                  <div class="form-group"><label>{{ t('configView.timeoutPorPeticionS') }}</label><input v-model.number="store.configFlat['features.themis.scanners.nuclei.requestTimeout']" type="number" min="1" max="120" class="inp" /></div>
                  <div class="form-group"><label>{{ t('configView.timeoutDelEscaneoS') }}</label><input v-model.number="store.configFlat['features.themis.scanners.nuclei.timeout']" type="number" min="60" max="14400" class="inp" /></div>
                </div>
                <div class="form-group">
                  <label>{{ t('configView.severidadesPorDefecto') }}</label>
                  <div class="chip-row">
                    <label v-for="sev in nucleiSeverities" :key="sev" class="chip">
                      <input v-model="store.configFlat['features.themis.scanners.nuclei.defaultSeverities']" type="checkbox" :value="sev" />
                      <span>{{ sev }}</span>
                    </label>
                  </div>
                  <span class="field-hint">{{ t('configView.loQueSeEscaneaSi') }}</span>
                </div>
              </ScannerCard>
              <ScannerCard name="Lybra" icon="scan" :flat="store.configFlat" prefix="features.themis.scanners.lybra">
                <div class="cfg-row"><label class="toggle-row"><input v-model="store.configFlat['features.themis.scanners.lybra.activeChecks']" type="checkbox" class="toggle" /><span>{{ t('configView.comprobacionesActivas') }}</span></label></div>
                <div class="cfg-row"><label class="toggle-row"><input v-model="store.configFlat['features.themis.scanners.lybra.fingerprintingEnabled']" type="checkbox" class="toggle" /><span>{{ t('configView.tech.fingerprinting') }}</span></label></div>
                <div class="cfg-row"><label class="toggle-row"><input v-model="store.configFlat['features.themis.scanners.lybra.ingest.enabled']" type="checkbox" class="toggle" /><span>{{ t('configView.ingestaDeHallazgos') }}</span></label></div>
                <div class="cfg-grid cfg-grid--tight">
                  <div class="form-group"><label>{{ t('configView.severidadMinima') }}</label>
                    <select v-model="store.configFlat['features.themis.scanners.lybra.ingest.minSeverity']" class="inp sel">
                      <option v-for="sev in severities" :key="sev" :value="sev">{{ sev }}</option>
                    </select>
                  </div>
                  <div class="form-group"><label>{{ t('configView.maxComprobaciones') }}</label><input v-model.number="store.configFlat['features.themis.scanners.lybra.ingest.maxChecks']" type="number" min="1" max="5000" class="inp" /></div>
                </div>

                <CollapsibleSection default-open>
                  <template #header><h4 class="card-subtitle">{{ t('configView.motor') }}</h4></template>
                  <p class="field-hint">{{ t('configView.cuantoEmpujaElMotorContra') }}</p>
                  <div class="cfg-grid cfg-grid--tight">
                    <div v-for="dial in lybraEngineDials" :key="dial.key" class="form-group">
                      <label>{{ t(`configView.dials.${dial.key}`) }}</label>
                      <input
                        v-model.number="store.configFlat[`features.themis.scanners.lybra.engine.${dial.key}`]"
                        type="number" :min="dial.min" :max="dial.max" :step="dial.step || 1" class="inp" />
                    </div>
                    <div class="form-group"><label>{{ t('configView.tech.userAgent') }}</label><input v-model="store.configFlat['features.themis.scanners.lybra.engine.httpUserAgent']" type="text" class="inp mono" /></div>
                  </div>
                </CollapsibleSection>

                <CollapsibleSection default-open>
                  <template #header><h4 class="card-subtitle">{{ t('configView.evidencia') }}</h4></template>
                  <p class="field-hint">{{ t('configView.elTrozoDeRespuestaCruda') }}</p>
                  <div class="cfg-row"><label class="toggle-row"><input v-model="store.configFlat['features.themis.scanners.lybra.evidence.enabled']" type="checkbox" class="toggle" /><span>{{ t('configView.guardarEvidencia') }}</span></label></div>
                  <div class="cfg-grid cfg-grid--tight">
                    <div class="form-group"><label>{{ t('configView.tamanoMaxBytes') }}</label><input v-model.number="store.configFlat['features.themis.scanners.lybra.evidence.maxBodyBytes']" type="number" min="256" step="256" class="inp" /></div>
                    <div class="form-group"><label>{{ t('configView.retencionDias') }}</label><input v-model.number="store.configFlat['features.themis.scanners.lybra.evidence.retentionDays']" type="number" min="1" max="3650" class="inp" /></div>
                  </div>
                </CollapsibleSection>

                <CollapsibleSection default-open>
                  <template #header><h4 class="card-subtitle">{{ t('configView.credencialesPorDefecto') }}</h4></template>
                  <p class="field-hint">{{ t('configView.esLaUnicaFaseQue') }}</p>
                  <div class="cfg-grid cfg-grid--tight">
                    <div class="form-group"><label>{{ t('configView.intentosPorCuenta') }}</label><input v-model.number="store.configFlat['features.themis.scanners.lybra.credentials.maxAttempts']" type="number" min="1" max="20" class="inp" /></div>
                  </div>
                </CollapsibleSection>

                <CollapsibleSection default-open>
                  <template #header><h4 class="card-subtitle">{{ t('configView.rastreoDeSoloLectura') }}</h4></template>
                  <p class="field-hint">{{ t('configView.descubreLoQueLosChecks') }}</p>
                  <div class="cfg-grid cfg-grid--tight">
                    <div class="form-group"><label>{{ t('configView.paginasMaximas') }}</label><input v-model.number="store.configFlat['features.themis.scanners.lybra.crawler.maxPages']" type="number" min="0" max="500" class="inp" /></div>
                    <div class="form-group"><label>{{ t('configView.profundidadMaxima') }}</label><input v-model.number="store.configFlat['features.themis.scanners.lybra.crawler.maxDepth']" type="number" min="1" max="10" class="inp" /></div>
                    <div class="form-group"><label>{{ t('configView.tiempoMaximoS') }}</label><input v-model.number="store.configFlat['features.themis.scanners.lybra.crawler.timeBudgetSeconds']" type="number" min="1" max="120" class="inp" /></div>
                  </div>
                </CollapsibleSection>
              </ScannerCard>
            </div>
          </section>

          <section id="section-aegis" class="section">
            <div class="section-head"><h2>Aegis</h2><p class="section-desc">{{ t('configView.generacionDePildorasDeConcienciacion') }}</p></div>
            <div class="section-body">
              <div class="cfg-row"><label class="toggle-row"><input v-model="store.configFlat['features.aegis.enabled']" type="checkbox" class="toggle" /><span>{{ t('configView.habilitado') }}</span></label></div>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.consejosPorPildora') }}</label><input v-model.number="store.configFlat['features.aegis.tipsAmount']" type="number" min="1" max="20" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.preguntasDelTest') }}</label><input v-model.number="store.configFlat['features.aegis.questionsAmount']" type="number" min="1" max="20" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.opcionesPorPregunta') }}</label><input v-model.number="store.configFlat['features.aegis.optionsAmount']" type="number" min="2" max="8" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.antiguedadMaxDeAlertasAnos') }}</label><input v-model.number="store.configFlat['features.aegis.vulnerabilitiesAntiquity']" type="number" min="1" max="30" class="inp" /></div>
              </div>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.directorioDeSalida') }}</label><input v-model="store.configFlat['features.aegis.directories.output']" type="text" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.stackDeDocumentos') }}</label><input v-model="store.configFlat['features.aegis.directories.stack']" type="text" class="inp" /></div>
              </div>
              <PromptField v-model="store.configFlat['features.aegis.prompts.system']" :label="t('config.scanner.systemPrompt')" :title="t('config.scanner.systemPromptTitle', { name: 'Aegis' })" />
              <PromptField v-model="store.configFlat['features.aegis.prompts.userTemplate']" :label="t('config.scanner.userTemplate')" :title="t('config.scanner.userTemplateTitle', { name: 'Aegis' })" />
            </div>
          </section>

          <section id="section-hygeia" class="section">
            <div class="section-head"><h2>Hygeia</h2><p class="section-desc">{{ t('configView.monitorizacionDeActivosViaAgente') }}</p></div>
            <div class="section-body">
              <p class="field-hint">{{ t('configView.unActivoPasaADesconectado') }}</p>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.intervaloDeLatidoS') }}</label><input v-model.number="store.configFlat['features.hygeia.heartbeatIntervalSec']" type="number" min="5" max="3600" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.latidosPerdidosParaDesconectar') }}</label><input v-model.number="store.configFlat['features.hygeia.offlineAfterMissed']" type="number" min="1" max="100" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.retencionDias') }}</label><input v-model.number="store.configFlat['features.hygeia.retentionDays']" type="number" min="1" max="3650" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.cronDePurga') }}</label><input v-model="store.configFlat['features.hygeia.retentionCron']" type="text" class="inp mono" /><span class="field-hint">{{ t('configView.formatoCronDeCincoCampos') }}</span></div>
                <div class="form-group"><label>{{ t('configView.precioDeLaElectricidadPor') }}</label><input v-model.number="store.configFlat['features.hygeia.energyPricePerKwh']" type="number" min="0" step="0.01" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.moneda') }}</label><input v-model="store.configFlat['features.hygeia.energyPriceCurrency']" type="text" maxlength="3" class="inp mono" /><span class="field-hint">{{ t('configView.codigoIso4217EurUsd') }}</span></div>
                <div class="form-group"><label>{{ t('configView.directorioDeSalidaCsvY') }}</label><input v-model="store.configFlat['features.hygeia.directories.output']" type="text" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.versionMinimaDeAgente') }}</label><input v-model="store.configFlat['features.hygeia.minAgentVersion']" type="text" class="inp mono" placeholder="0.0.0" /><span class="field-hint">{{ t('configView.formatoXYZUn') }}</span></div>
              </div>
              <h3 class="subsection-title">{{ t('configView.umbrales') }}</h3>
              <p class="field-hint">{{ t('configView.latidosSostenidosEvitaLasAlertas') }}</p>
              <div class="cfg-grid">
                <template v-for="metric in hygeiaMetrics" :key="metric.key">
                  <div class="form-group"><label>{{ t('configView.thresholdWarning', { metric: t(`configView.metrics.${metric.key}`) }) }}</label><input v-model.number="store.configFlat[`features.hygeia.thresholds.${metric.key}.warning`]" type="number" min="1" max="100" class="inp" /></div>
                  <div class="form-group"><label>{{ t('configView.thresholdCritical', { metric: t(`configView.metrics.${metric.key}`) }) }}</label><input v-model.number="store.configFlat[`features.hygeia.thresholds.${metric.key}.critical`]" type="number" min="1" max="100" class="inp" /></div>
                  <div v-if="metric.sustained" class="form-group"><label>{{ t('configView.thresholdSustained', { metric: t(`configView.metrics.${metric.key}`) }) }}</label><input v-model.number="store.configFlat[`features.hygeia.thresholds.${metric.key}.sustainedHeartbeats`]" type="number" min="1" max="60" class="inp" /></div>
                </template>
              </div>
              <h3 class="subsection-title">{{ t('configView.coloresDelInforme') }}</h3>
              <p class="field-hint">{{ t('configView.laPaletaConLaQue') }}</p>
              <div class="color-grid">
                <div v-for="color in reportColors" :key="color.key" class="color-pick">
                  <input v-model="store.configFlat[`features.hygeia.colorPalette.${color.key}`]" type="color" class="color-input" />
                  <span class="color-label">{{ t(`config.scanner.colors.${color.key}`) }}</span>
                  <span class="color-hex">{{ store.configFlat[`features.hygeia.colorPalette.${color.key}`] }}</span>
                </div>
              </div>
              <h3 class="subsection-title">{{ t('configView.analisisDerivado') }}</h3>
              <p class="field-hint">{{ t('configView.cuandoElAnalisisSeAtreve') }}</p>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.ajusteMinimoDeLaTendencia') }}</label><input v-model.number="store.configFlat['features.hygeia.analysis.minTrendRSquared']" type="number" min="0" max="1" step="0.05" class="inp" /><span class="field-hint">{{ t('configView.de0A1Cuanto') }}</span></div>
                <div class="form-group"><label>{{ t('configView.crecimientoMinimoPuntosPorcentualesAl') }}</label><input v-model.number="store.configFlat['features.hygeia.analysis.minTrendSlopePctPerDay']" type="number" min="0" step="0.01" class="inp" /><span class="field-hint">{{ t('configView.porDebajoDeEstoSe') }}</span></div>
                <div class="form-group"><label>{{ t('configView.ventanaDeCoincidenciaDePicos') }}</label><input v-model.number="store.configFlat['features.hygeia.analysis.peakCoincidenceWindowSec']" type="number" min="1" class="inp" /><span class="field-hint">{{ t('configView.cuantoPuedenSepararseDosPicos') }}</span></div>
              </div>
              <h3 class="subsection-title">{{ t('configView.cacheDeEstadisticas') }}</h3>
              <p class="field-hint">{{ t('configView.cuantoTiempoSeReutilizaUna') }}</p>
              <div class="cfg-row"><label class="toggle-row"><input v-model="store.configFlat['features.hygeia.statsCache.isEnabled']" type="checkbox" class="toggle" /><span>{{ t('configView.reutilizarResultados') }}</span></label></div>
              <div class="cfg-grid">
                <div class="form-group"><label>{{ t('configView.periodosDeHasta24H') }}</label><input v-model.number="store.configFlat['features.hygeia.statsCache.shortPeriodTtlSeconds']" type="number" min="1" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.periodosDeHasta7Dias') }}</label><input v-model.number="store.configFlat['features.hygeia.statsCache.mediumPeriodTtlSeconds']" type="number" min="1" class="inp" /></div>
                <div class="form-group"><label>{{ t('configView.periodosMasLargosS') }}</label><input v-model.number="store.configFlat['features.hygeia.statsCache.longPeriodTtlSeconds']" type="number" min="1" class="inp" /></div>
              </div>
              <h3 class="subsection-title">{{ t('configView.limites') }}</h3>
              <p class="field-hint">{{ t('configView.topesDeLoQueEl') }}</p>
              <div class="cfg-grid">
                <div v-for="limit in hygeiaLimits" :key="limit.key" class="form-group">
                  <label>{{ t(`configView.limits.${limit.key}.label`) }}</label>
                  <input v-model.number="store.configFlat[`features.hygeia.limits.${limit.key}`]" type="number" min="1" class="inp" />
                  <span v-if="limit.hasHint" class="field-hint">{{ t(`configView.limits.${limit.key}.hint`) }}</span>
                </div>
              </div>
            </div>
          </section>

          <div class="form-actions">
            <button type="button" class="btn btn--secondary" @click="store.resetForm()">{{ t('configView.reset') }}</button>
            <button type="submit" class="btn btn--primary" :disabled="store.saving">{{ store.saving ? t('common.saving') : t('configView.save') }}</button>
          </div>
        </form>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import Topbar from '@/components/shared/Topbar.vue'
import StarBackground from '@/components/shared/StarBackground.vue'
import { useConfigStore } from '@/stores/configStore'
import ScannerCard from '@/components/config/ScannerCard.vue'
import CollapsibleSection from '@/components/config/CollapsibleSection.vue'
import ModelPicker from '@/components/config/ModelPicker.vue'
import PromptField from '@/components/shared/PromptField.vue'
import { LOCALE_OPTIONS } from '@/i18n'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const store = useConfigStore()

const ICON = {
  launch:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/></svg>',
  general:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
  security:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>',
  database:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>',
  redis:     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/></svg>',
  taskqueue: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><line x1="8" y1="9" x2="16" y2="9"/><line x1="8" y1="13" x2="14" y2="13"/></svg>',
  ai:        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="6" height="6" rx="1"/><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 15h3M1 9h3M1 15h3"/></svg>',
  herald:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16v16H4z"/><path d="m4 7 8 6 8-6"/><path d="M2 20h6"/></svg>',
  iris:      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 5L2 7"/></svg>',
  themis:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>',
  aegis:     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>',
  hygeia:    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>',
}

/** Índice lateral; `labelKey` es la clave del rótulo de cada sección (el mismo título que su cabecera). */
const navGroups = [
  { id: 'platform', items: [
    { id: 'launch',    labelKey: 'configView.lanzamiento', icon: ICON.launch },
    { id: 'general',   labelKey: 'configView.general',     icon: ICON.general },
    { id: 'security',  labelKey: 'configView.seguridad',   icon: ICON.security },
    { id: 'database',  labelKey: 'configView.baseDeDatos', icon: ICON.database },
    { id: 'redis',     labelKey: 'configView.tech.redis',  icon: ICON.redis },
    { id: 'taskqueue', labelKey: 'configView.tech.taskqueue', icon: ICON.taskqueue },
  ]},
  { id: 'modules', items: [
    { id: 'ai',       labelKey: 'configView.ia',     icon: ICON.ai },
    { id: 'herald',   labelKey: 'configView.correo', icon: ICON.herald },
    { id: 'iris',     labelKey: 'configView.modules.iris',   icon: ICON.iris },
    { id: 'themis',   labelKey: 'configView.modules.themis', icon: ICON.themis },
    { id: 'aegis',    labelKey: 'configView.modules.aegis',  icon: ICON.aegis },
    { id: 'hygeia',   labelKey: 'configView.modules.hygeia', icon: ICON.hygeia },
  ]},
]
const navSections = navGroups.flatMap((g) => g.items)

const isolationLevels = ['READ UNCOMMITTED', 'READ COMMITTED', 'REPEATABLE READ', 'SERIALIZABLE']
// Solo la familia HS*: la firma usa un secreto simétrico, y el backend
// rechaza cualquier otra cosa (S8).
const jwtAlgorithms = ['HS256', 'HS384', 'HS512']
// `envVar` es la variable que se usa cuando el campo de modelo queda vacío, y
// se enseña como pista dentro del propio control: sin ella, un campo vacío se
// lee como «sin modelo» en vez de como «el que diga el entorno».
const aiStrategies = computed(() => [
  { value: 'ollama', label: t('configView.ollamaLocal'), envVar: 'OLLAMA_MODEL' },
  { value: 'openai', label: 'OpenAI',        envVar: 'OPENAI_MODEL' },
  { value: 'google', label: 'Google Gemini', envVar: 'GOOGLE_MODEL' },
])
// Los módulos que generan contenido con IA. Iris faltaba: llama a
// `build_generator("iris")` desde su redactor de resúmenes, pero su estrategia
// no estaba declarada, así que caía en la de por defecto sin que se viera.
const aiModules = [
  { key: 'themis', label: 'Themis' },
  { key: 'aegis',  label: 'Aegis' },
  { key: 'iris',   label: 'Iris' },
]

// Herald solo tiene una estrategia registrada hoy (relay SMTP). El selector se
// mantiene porque la capa es enchufable por diseño y la alternativa —esconder
// el control— haría invisible qué está eligiendo el sistema.
const mailStrategies = computed(() => [
  { value: 'smtp', label: t('configView.relaySmtp') },
])
/** Módulos que envían correo; su rótulo está en `configView.mailModules.<key>`. */
const mailModules = [{ key: 'aegis' }, { key: 'iris' }, { key: 'hygeia' }, { key: 'accounts' }]
const severities = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL']
// Nuclei etiqueta sus plantillas en minúsculas; el valor que se guarda tiene
// que coincidir exactamente con lo que espera el binario.
const nucleiSeverities = ['critical', 'high', 'medium', 'low', 'info']

const kbFeeds = [
  { key: 'nvd',  label: 'NVD' },
  { key: 'kev',  label: 'KEV' },
  { key: 'epss', label: 'EPSS' },
  { key: 'oval', label: 'OVAL' },
]

// Los diales del motor de Lybra son quince campos numéricos con la misma
// forma: se describen aquí y se pintan con v-for, como ya se hace con los
// umbrales y los límites de Hygeia.
const lybraEngineDials = [
  { key: 'tcpConcurrency',       min: 1,   max: 2000 },
  { key: 'tcpTimeout',           min: 0.1, max: 60, step: 0.1 },
  { key: 'udpTimeout',           min: 0.1, max: 60, step: 0.1 },
  { key: 'udpRetries',           min: 0,   max: 10 },
  { key: 'udpBudgetSeconds',     min: 1,   max: 600, step: 0.5 },
  { key: 'rateLimitInterval',    min: 0,   max: 10, step: 0.05 },
  { key: 'hostPoolSize',         min: 1,   max: 64 },
  { key: 'httpTimeout',          min: 1,   max: 120 },
  { key: 'httpMaxBodyBytes',     min: 1024, max: 8388608, step: 1024 },
  { key: 'networkTimeout',       min: 0.5, max: 120, step: 0.5 },
  { key: 'bannerTimeout',        min: 0.5, max: 60, step: 0.5 },
  { key: 'maxBlindProbes',       min: 0,   max: 20 },
  { key: 'maxPayloadExpansions', min: 1,   max: 500 },
]

// Los umbrales y los límites de Hygeia son 22 campos con la misma forma: se
// describen aquí y se pintan con v-for en vez de a mano uno por uno.
const hygeiaMetrics = [
  { key: 'cpuPct',  sustained: true },
  { key: 'memPct',  sustained: true },
  { key: 'diskPct', sustained: false },
  { key: 'swapPct', sustained: false },
]
// Las seis tintas de una paleta de informe. Mismo juego que usa ScannerCard
// para los escáneres de Themis; aquí se repite la lista porque Hygeia no pasa
// por ese componente (no es un escáner, no tiene prompts ni tarjeta propia).
/** Colores de la paleta del informe; el rótulo está en `config.scanner.colors.<key>`. */
const reportColors = ['black', 'dark', 'main', 'secondary', 'light', 'white'].map((key) => ({ key }))

const hygeiaLimits = [
  { key: 'maxBodyBytes',         hasHint: true },
  { key: 'maxDecompressedBytes', hasHint: true },
  { key: 'maxProcesses' },
  { key: 'maxDiskMounts' },
  { key: 'maxNetInterfaces' },
  { key: 'maxSeriesPoints' },
  { key: 'maxStatsPeriodDays',   hasHint: true },
  { key: 'maxEntityStatsPeriodDays', hasHint: true },
  { key: 'minIntervalSec' },
  { key: 'clockSkewSec',         hasHint: true },
  { key: 'maxBackfillSec',       hasHint: true },
  { key: 'maxAssetsPerUser' },
  { key: 'maxInventoryItems' },
]

const kbSourcePaths = computed(() => {
  const prefix = 'features.themis.kb.sources.'
  return Object.keys(store.configFlat)
    .filter((key) => key.startsWith(prefix))
    .sort()
    .map((path) => ({
      path,
      // Las claves con punto propio llegan escapadas (`ubuntu:20\.04`, ver `flatten`).
      label: path.slice(prefix.length).replace('oval.', 'OVAL ').replaceAll('\\.', '.').toUpperCase(),
    }))
})

const activeSection = ref('general')
let observer = null
function scrollTo(sectionId) { const el = document.getElementById(`section-${sectionId}`); if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' }) }

onMounted(async () => {
  // Hay que esperar a la carga: mientras `store.loading` es true el formulario
  // no está en el DOM (v-else), así que registrar el observer antes dejaba el
  // resaltado del nav sin observar nada — no fallaba, simplemente no hacía nada.
  await store.loadConfig()
  // Sin `await`: son llamadas a proveedores externos que pueden tardar, y el
  // formulario no debe esperarlas para pintarse.
  store.loadAiModels()
  await nextTick()
  observer = new IntersectionObserver((entries) => {
    // Con este rootMargin varias secciones intersecan a la vez; la activa es la
    // más alta de las visibles, no la última que reporte el observer.
    const visible = entries.filter((entry) => entry.isIntersecting)
    if (!visible.length) return
    visible.sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
    activeSection.value = visible[0].target.id.replace('section-', '')
  }, { rootMargin: '-80px 0px -60% 0px' })
  for (const section of navSections) {
    const el = document.getElementById(`section-${section.id}`)
    if (el) observer.observe(el)
  }
})
onUnmounted(() => { if (observer) observer.disconnect() })

// El catálogo fijo de marcas se retiró: los productos vigilados se eligen por
// usuario contra el índice CPE del espejo local de NVD (GET /aegis/products),
// no desde la configuración global.
/**
 * Funciones que general.launch puede cerrar al público, en el orden en que se
 * pintan. `unlocks` resume qué tiene que estar resuelto antes de abrir cada
 * una (lo detalla el proyecto «Legal» de la organización).
 */
/** Funciones que se abren por separado; sus textos están en `configView.surfaces.<key>`. */
const LAUNCH_SURFACES = ['registration', 'pricing', 'thirdPartyScanners', 'campaigns', 'mailboxConnectors', 'externalAi'].map((key) => ({ key }))

const isLaunchPreview = computed(() => store.configFlat['general.launch.mode'] !== 'public')

/** Modo guardado en el servidor, para saber cuándo se está abriendo Ellysia. */
const savedLaunchMode = ref(null)
watch(() => store.loading, (isLoading) => {
  if (!isLoading) savedLaunchMode.value = store.configFlat['general.launch.mode']
}, { immediate: true })

/** Milisegundos entre un guardado correcto y la recarga de la pestaña. */
const RELOAD_DELAY_MS = 800

/**
 * Guarda la configuración y, si sale bien, recarga la pestaña. Pasar de vista previa a abierto al público pide
 * confirmación y enumera lo que se va a abrir: es el cambio de más alcance
 * del panel, y un clic distraído no debería bastar.
 */
async function handleSave() {
  const selectedMode = store.configFlat['general.launch.mode']
  if (savedLaunchMode.value !== 'public' && selectedMode === 'public') {
    const openingLabels = LAUNCH_SURFACES
      .filter((surface) => store.configFlat[`general.launch.surfaces.${surface.key}`] === true)
      .map((surface) => `• ${t(`configView.surfaces.${surface.key}.label`)}`)
    const message = openingLabels.length
      ? t('configView.confirmOpen', { surfaces: openingLabels.join('\n') })
      : t('configView.confirmOpenNothing')
    if (!window.confirm(message)) return
  }
  if (!(await store.saveConfig())) return
  savedLaunchMode.value = selectedMode
  // La SPA lee algunos ajustes una sola vez al arrancar (p. ej. el estado de
  // lanzamiento de useLaunch): se recarga para aplicarlos. La espera deja leer
  // el aviso de «guardado», que la recarga destruiría.
  setTimeout(() => window.location.reload(), RELOAD_DELAY_MS)
}
</script>

<style scoped>
.config-page { min-height: 100vh; background: var(--bg); padding-top: var(--topbar-h); position: relative; }
.main { max-width: 1600px; margin: 0 auto; padding: 1.75rem 1.1rem 4rem; position: relative; z-index: 1; }
.config-layout { display: flex; gap: 1.25rem; align-items: flex-start; }
.config-nav-column { width: 160px; flex-shrink: 0; align-self: stretch; }
/* El overflow propio no rompe el sticky (solo lo rompería en un ancestro): es la
   válvula para que el nav siga siendo usable en pantallas bajas. */
.config-nav { position: sticky; top: calc(var(--topbar-h) + 1.75rem); max-height: calc(100vh - var(--topbar-h) - 3.5rem); overflow-y: auto; }
.config-nav nav { display: flex; flex-direction: column; gap: 0.2rem; }
.nav-link { display: flex; align-items: center; gap: 0.45rem; padding: 0.45rem 0.6rem; border-radius: 7px; color: var(--text-muted); font-size: var(--fs-lg); font-weight: 500; text-decoration: none; transition: all var(--transition); }
.nav-link:hover { background: var(--surface-2); color: var(--text-dim); }
.nav-link.active { background: var(--accent-dim); color: var(--accent-bright); font-weight: 600; }
.nav-icon { width: 16px; height: 16px; flex-shrink: 0; display: flex; align-items: center; }
.nav-icon svg { width: 100%; height: 100%; }
.nav-label { white-space: nowrap; }
.nav-group-label { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-body); font-weight: 600; text-transform: uppercase; letter-spacing: 0.1em; color: var(--text-muted); padding: 0 0.6rem; margin: 0.7rem 0 0.25rem; }
.nav-group-label:first-child { margin-top: 0; }
.config-form { flex: 1; min-width: 0; }
.section { margin-bottom: 2rem; }
.section-head { margin-bottom: 0.85rem; padding-bottom: 0.55rem; border-bottom: 1px solid var(--border); }
.section-head--row { display: flex; align-items: flex-start; justify-content: space-between; gap: 0.85rem; }
.section-head h2 { font-size: var(--fs-2xl); font-weight: 700; color: var(--text); margin: 0; font-family: var(--font-display); font-size-adjust: var(--fsa-display); }
.section-desc { font-size: var(--fs-lg); color: var(--text-muted); margin: 0.15rem 0 0; }
.version-chip { flex-shrink: 0; font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-md); font-weight: 600; color: var(--accent-bright); background: var(--accent-dim); border: 1px solid var(--border-solid); border-radius: 999px; padding: 0.2rem 0.6rem; }
.section-body { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 1.1rem 1.25rem; display: flex; flex-direction: column; gap: 0.85rem; }
.subsection-title { font-size: var(--fs-lg); font-weight: 600; color: var(--text-dim); margin: 0.2rem 0 0.3rem; }
.cfg-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 0.85rem; }
.cfg-grid--tight { grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0.5rem; }
.cfg-row { display: flex; align-items: center; }
.color-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(90px, 1fr)); gap: 0.35rem; max-width: 560px; }
.color-pick { display: flex; flex-direction: column; align-items: center; gap: 0.1rem; padding: 0.4rem 0.2rem; background: var(--bg); border-radius: 5px; border: 1px solid var(--border); }
.color-input { width: 30px; height: 22px; border: none; border-radius: 3px; cursor: pointer; background: transparent; padding: 0; }
.color-label { font-size: var(--fs-body); font-weight: 600; color: var(--text-dim); }
.color-hex { font-size: var(--fs-body); color: var(--text-muted); font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); }
.chip-row { display: flex; flex-wrap: wrap; gap: 0.35rem; }
.chip { display: flex; align-items: center; gap: 0.3rem; padding: 0.25rem 0.5rem; background: var(--bg); border: 1px solid var(--border-solid); border-radius: 999px; font-size: var(--fs-md); color: var(--text-dim); cursor: pointer; }
.chip input { accent-color: var(--accent); cursor: pointer; }
.card-subtitle { font-size: var(--fs-md); font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.04em; margin: 0; }
/* Separación entre los tres bloques colapsables de Lybra (Motor, Evidencia,
   Credenciales): antes la daba el margin-top de `.card-subtitle`, que ahora
   vive dentro del botón de cada CollapsibleSection y no puede seguir
   cumpliendo ese papel. El nodo raíz de un componente hijo lleva también el
   atributo scoped del padre, así que este selector sin :deep() sí alcanza a
   las tres instancias declaradas aquí, dentro del slot de Lybra. */
.collapsible + .collapsible { margin-top: 0.5rem; }
/* `align-items: start` evita que Grid estire cada tarjeta a la altura de la más
   alta de su fila (Lybra, con varias subsecciones, frente a Nmap/Nikto casi
   sin opciones propias) — ese estirado era el hueco vacío que se veía, no
   un exceso de contenido de Lybra. */
.scanner-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 0.85rem; margin-top: 0.85rem; align-items: start; }
.form-group { display: flex; flex-direction: column; gap: 0.25rem; }
.form-group label { font-size: var(--fs-md); font-weight: 600; color: var(--text-dim); }
.inp { background: var(--bg); border: 1px solid var(--border-solid); border-radius: 6px; padding: 0.45rem 0.6rem; color: var(--text); font-size: var(--fs-input); outline: none; transition: border-color 0.2s; }
.inp:focus { border-color: var(--accent); }
.sel { cursor: pointer; appearance: none; -webkit-appearance: none; padding-right: 1.8rem; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%2382829a' stroke-width='2.5'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 0.55rem center; background-size: 0.85rem; }
.sel option { background: var(--surface-2); color: var(--text); }
.mono { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); }
/* Un `input[type=color]` con el relleno de `.inp` deja la muestra reducida a
   una línea: aquí el control ES la muestra, así que se le quita el relleno. */
.color-inp { padding: 0.15rem; height: 2.1rem; cursor: pointer; }
.toggle-row { display: flex; align-items: center; gap: 0.4rem; cursor: pointer; font-size: var(--fs-lg); font-weight: 500; color: var(--text); }
.toggle { width: 16px; height: 16px; accent-color: var(--accent); cursor: pointer; }
.field-hint { font-size: var(--fs-md); color: var(--text-muted); line-height: 1.5; }
.field-hint code { font-family: var(--font-mono); font-size-adjust: var(--fsa-mono); font-size: var(--fs-md); background: var(--surface-2); padding: 1px 4px; border-radius: 3px; color: var(--text-dim); }
/* Barra flotante, no una tarjeta más: con `--surface` y `--border` era idéntica
   a los `.section-body` por encima de los que pasa, y al solaparse parecía una
   sección rota. `--surface-2` es un tono distinto del de las tarjetas en los dos
   temas (`--topbar-bg` no valía: en dawn es el mismo color de tarjeta al 85%), y
   la sombra la despega del contenido que va pasando por debajo. */
.form-actions { display: flex; gap: 0.6rem; justify-content: flex-end; position: sticky; bottom: 0.85rem; background: var(--surface-2); border: 1px solid var(--border-med); border-radius: 10px; padding: 0.85rem 1.1rem; box-shadow: 0 4px 20px rgba(0,0,0,0.28); z-index: 10; }
.loading-block { padding: 5rem 0; display: flex; justify-content: center; width: 100%; }
.skeleton { background: var(--surface); border-radius: 8px; animation: pulse 1.4s ease-in-out infinite; }
.skeleton--lg { width: 100%; height: 380px; }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .4; } }
.launch-surfaces { list-style: none; margin: 0.9rem 0 0; padding: 0; display: flex; flex-direction: column; gap: 0.55rem; }
.launch-surfaces--inactive { opacity: 0.55; }
.launch-surface { display: flex; flex-direction: column; gap: 0.15rem; padding: 0.55rem 0.7rem; border: 1px solid var(--border); border-radius: 7px; background: var(--surface); }
.launch-switch { display: flex; align-items: center; gap: 0.5rem; cursor: pointer; }
.launch-switch input:disabled { cursor: not-allowed; }
.launch-name { font-weight: 600; color: var(--text); }
@media (max-width: 800px) { .config-layout { flex-direction: column; } .config-nav-column { width: 100%; } .config-nav { position: static; } .config-nav nav { flex-direction: row; flex-wrap: wrap; } .nav-link { flex: 1; justify-content: center; min-width: 80px; } }
</style>
