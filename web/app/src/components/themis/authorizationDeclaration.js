/**
 * Versión vigente del texto de la declaración que se enseña al autorizar un
 * objetivo («declaro que soy titular de este sistema o que tengo autorización
 * escrita de su titular para analizarlo»).
 *
 * Viaja al servidor con cada autorización y queda guardada junto a ella, así que
 * prueba qué texto aceptó el usuario. Tiene que coincidir con
 * `AUTHORIZATION_DECLARATION_VERSION` de
 * `API/src/modules/features/themis/managers/authorized_target.py` (lo comprueba
 * `test_authorization_declaration_version_matches_the_spa.py`) y se cambia
 * cuando cambia el texto de `authorizeTarget.declaration` o la política de uso
 * aceptable que lo acompaña.
 */
export const AUTHORIZATION_DECLARATION_VERSION = '2026-10-07'
