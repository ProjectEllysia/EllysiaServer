import { defineStore } from 'pinia'
import { reactive, ref } from 'vue'
import { useApi } from '@/composables/useApi'
import { useToastStore } from '@/stores/toastStore'
import { useCache } from '@/composables/useCache'
import { i18n, setLocale } from '@/i18n'

const CACHE_KEY = 'me'
const PROFILE_TTL = 5 * 60 * 1000

/**
 * Store de perfil de usuario — carga y actualiza los datos personales.
 *
 * Sustituye la lógica de profile.js (122 líneas de manipulación DOM directa).
 * Centraliza las llamadas GET/PUT de /users/me y el cambio de contraseña.
 * Cachea GET /users/me con TTL de 5min para evitar peticiones redundantes.
 */
export const useProfileStore = defineStore('profile', () => {
  const { apiFetch, apiError } = useApi()
  const toast = useToastStore()
  const profileCache = useCache({ storage: 'session', keyPrefix: 'profile:', ttl: PROFILE_TTL, maxSize: 20 })

  /** Datos del perfil del usuario autenticado */
  // emailVerified arranca en null y no en false: hasta que el perfil llega
  // no se sabe, y pintar el aviso de "confirma tu correo" a quien ya lo
  // confirmo seria acusarle por un dato que aun no habia cargado.
  // language es lo que eligió el usuario (null = no eligió) y effectiveLanguage
  // el idioma que le corresponde según el servidor: el suyo, si no el de su
  // organización, si no el de la plataforma.
  const profile = reactive({ first_name: '', last_name: '', email: '', username: '', role: '', created_at: '', emailVerified: null, mustChangePassword: false, language: null, effectiveLanguage: null })
  /** Indicador de carga en curso */
  const loading = ref(false)

  function _hydrate(data) {
    Object.assign(profile, {
      first_name: data.first_name || '',
      last_name: data.last_name || '',
      email: data.email || '',
      username: data.username || '',
      role: data.role || '',
      created_at: data.created_at || '',
      emailVerified: data.emailVerified ?? null,
      mustChangePassword: data.mustChangePassword ?? false,
    })
    hydrateLanguage(data)
  }

  /**
   * Copia el idioma del perfil y pone la interfaz en el idioma efectivo.
   *
   * Es el único sitio donde la sesión decide el idioma: al iniciar sesión, al
   * recargar y al cambiarlo desde otro dispositivo, lo que diga el servidor
   * manda sobre lo recordado en este navegador. `setLocale` ignora un código
   * que la interfaz no tenga.
   *
   * @param {{ language?: string|null, effectiveLanguage?: string }} data - Respuesta de GET /users/me.
   */
  function hydrateLanguage(data) {
    profile.language = data.language ?? null
    profile.effectiveLanguage = data.effectiveLanguage ?? null
    if (profile.effectiveLanguage) setLocale(profile.effectiveLanguage)
  }

  function _snapshot() {
    // emailVerified y el idioma se quedan fuera a propósito: cambian desde
    // fuera de esta pestaña (el clic en el enlace del correo, el idioma
    // elegido en otro dispositivo o fijado por el dueño de la organización) y
    // una copia en caché los mantendría obsoletos tras recargar.
    return {
      first_name: profile.first_name,
      last_name: profile.last_name,
      email: profile.email,
      username: profile.username,
      role: profile.role,
      created_at: profile.created_at,
      mustChangePassword: profile.mustChangePassword,
    }
  }

  /**
   * Obtiene el perfil del usuario autenticado desde GET /users/me.
   * Usa caché con TTL de 5 minutos para evitar peticiones redundantes.
   */
  async function loadProfile() {
    const cached = profileCache.get(CACHE_KEY)
    if (cached) {
      // El resto del perfil sale de la caché, pero el estado del correo se
      // pide siempre al servidor: es el único dato que cambia "desde fuera"
      // (activar la cuenta desde el correo) y la caché de sesión lo dejaría
      // obsoleto durante su TTL. Se descarta el valor cacheado, también el de
      // las entradas antiguas que aún lo llevan.
      const { emailVerified: _ignored, ...rest } = cached
      _hydrate(rest)
      await refreshServerOwnedFields()
      return
    }

    loading.value = true
    try {
      const res = await apiFetch('/users/me')
      if (!res?.ok) return
      const data = await res.json()
      _hydrate(data)
      profileCache.set(CACHE_KEY, _snapshot())
    } finally { loading.value = false }
  }

  /**
   * Revalida contra el servidor los datos del perfil que cambian desde fuera.
   *
   * La cuenta se activa pulsando el enlace del correo, que puede abrirse en
   * otra pestaña, y el idioma puede cambiarse desde otro dispositivo o fijarlo
   * el dueño de la organización: esta pestaña no recibe ninguna notificación,
   * así que cada carga de perfil lo comprueba.
   */
  async function refreshServerOwnedFields() {
    try {
      const res = await apiFetch('/users/me')
      if (!res?.ok) return
      const data = await res.json()
      profile.emailVerified = data.emailVerified ?? null
      hydrateLanguage(data)
    } catch {
      // Sin respuesta no se sabe si el correo está confirmado: se mantiene el
      // valor anterior (null si venía de caché) y no se acusa a nadie.
    }
  }

  /**
   * Actualiza el nombre y apellido del usuario vía PUT /users/me.
   * Actualiza la caché y el estado reactivo sin re-fetch.
   * @param {string} first_name - Nuevo nombre
   * @param {string} last_name - Nuevo apellido
   * @returns {Promise<boolean>} True si se actualizó correctamente
   */
  async function updateProfile(first_name, last_name) {
    const res = await apiFetch('/users/me', {
      method: 'PUT',
      body: JSON.stringify({ first_name, last_name }),
    })
    if (!res?.ok) {
      toast.show(await apiError(res, i18n.global.t('profile.updateFailed')), 'error')
      return false
    }
    profile.first_name = first_name
    profile.last_name = last_name
    profileCache.set(CACHE_KEY, _snapshot())
    toast.show(i18n.global.t('profile.updated'), 'success')
    return true
  }

  /**
   * Guarda el idioma que elige el usuario vía PUT /users/me/language.
   *
   * @param {string|null} language - Código del idioma, o `null` para volver a
   *   seguir el de la organización o el de la plataforma.
   * @param {string} failureMessage - Texto del aviso si el servidor no
   *   responde; si responde con un error, se enseña el suyo, ya traducido.
   * @returns {Promise<boolean>} `true` si se guardó; la interfaz ya está en el
   *   idioma efectivo que devolvió el servidor.
   */
  async function updateLanguage(language, failureMessage) {
    const res = await apiFetch('/users/me/language', {
      method: 'PUT',
      body: JSON.stringify({ language }),
    })
    if (!res?.ok) {
      toast.show(await apiError(res, failureMessage), 'error')
      return false
    }
    hydrateLanguage(await res.json())
    return true
  }

  /**
   * Cambia la contraseña del usuario vía PUT /users/change-password.
   * @param {string} currentPassword - Contraseña actual (el servidor la reverifica)
   * @param {string} newPassword - Nueva contraseña (mín. 8 caracteres)
   * @returns {Promise<boolean>} True si se cambió correctamente
   */
  async function changePassword(currentPassword, newPassword) {
    const res = await apiFetch('/users/change-password', {
      method: 'PUT',
      body: JSON.stringify({ currentPassword, newPassword }),
    })
    if (!res?.ok) {
      toast.show(await apiError(res, i18n.global.t('profile.passwordChangeFailed')), 'error')
      return false
    }
    toast.show(i18n.global.t('profile.passwordChanged'), 'success')
    return true
  }

  /** Limpia el estado (Q6: logout SPA sin recarga dura). También vacía la
   * caché de sessionStorage (`profile:me`, TTL 5min) — sin esto, un usuario
   * nuevo en la misma pestaña vería el nombre/email del anterior hasta que
   * expirase por su cuenta. */
  function $reset() {
    Object.assign(profile, { first_name: '', last_name: '', email: '', username: '', role: '', created_at: '', emailVerified: null, mustChangePassword: false, language: null, effectiveLanguage: null })
    loading.value = false
    profileCache.clear()
  }

  return { profile, loading, loadProfile, refreshServerOwnedFields, updateProfile, updateLanguage, changePassword, $reset }
})
