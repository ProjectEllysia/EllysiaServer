/**
 * Lo que la documentación técnica enseña de cada herramienta además de su
 * texto: su nombre, que es propio y no se traduce, y su icono.
 */
import themisIcon from '@/assets/images/themis/Themis-Turqoise-BgN.png'
import aegisIcon from '@/assets/images/aegis/Ellysia-Aegis-Blue-BgN.png'
import irisIcon from '@/assets/images/iris/Iris-Red-BgN.png'
import acheronIcon from '@/assets/images/acheron/Acheron-Purple-BgN.png'
import hygeiaIcon from '@/assets/images/hygeia/Hygeia-DarkGreen-BgN.png'

/** Nombre de cada herramienta, igual en todos los idiomas. */
export const TOOL_NAMES = { themis: 'Themis', aegis: 'Aegis', iris: 'Iris', acheron: 'Acheron', hygeia: 'Hygeia' }

/** Icono de cada herramienta, el mismo de su hub. */
export const TOOL_ICONS = { themis: themisIcon, aegis: aegisIcon, iris: irisIcon, acheron: acheronIcon, hygeia: hygeiaIcon }
