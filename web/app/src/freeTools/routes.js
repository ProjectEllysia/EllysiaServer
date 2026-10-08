import { FREE_TOOLS, freeToolPath, freeToolSeoKey, freeToolViewFile } from './catalog'

/**
 * Vistas de las herramientas, cargadas bajo demanda: una por fichero de
 * `views/tools/<módulo>/`. El catálogo las localiza por nombre
 * (`freeToolViewFile`), así que añadir una herramienta no toca el router.
 */
const viewLoaders = import.meta.glob('../views/tools/*/*View.vue')

/**
 * Rutas de todas las herramientas del catálogo, listas para el router.
 *
 * Son públicas aunque la herramienta pida cuenta: la página se ve y se indexa, y
 * quien no ha entrado encuentra la invitación a hacerlo dentro de la propia
 * herramienta (`ToolShell`). Con `requiresAuth` en la ruta, el guard mandaría al
 * visitante al login antes de enseñarle qué es.
 *
 * `meta.surface` repite el interruptor del catálogo para que el guard del router
 * cierre la ruta con la misma regla que ya aplica al resto de superficies.
 *
 * @type {import('vue-router').RouteRecordRaw[]}
 * @throws {Error} Al cargar el módulo, si una entrada del catálogo no tiene su
 *   vista: es un olvido de quien la añadió y es mejor que se vea al arrancar.
 */
export const freeToolRoutes = FREE_TOOLS.map((tool) => {
  const loader = viewLoaders[`../views/tools/${freeToolViewFile(tool)}.vue`]
  if (!loader) throw new Error(`Falta la vista de la herramienta «${tool.id}»: views/tools/${freeToolViewFile(tool)}.vue`)
  return {
    path: freeToolPath(tool),
    name: `FreeTool${tool.id.charAt(0).toUpperCase()}${tool.id.slice(1)}`,
    component: loader,
    meta: { seo: freeToolSeoKey(tool), ...(tool.surface ? { surface: tool.surface } : {}) },
  }
})
