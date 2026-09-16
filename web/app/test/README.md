# Suites del SPA

Se ejecutan con `node` a secas, sin framework. Salen con código distinto de cero si algo falla,
para poder usarse en CI:

```bash
npm test                # las nueve suites, lo que corre el CI
npm run test:acheron    # solo la de Acheron
```

## Qué queda aquí de Acheron, y qué se fue

La criptografía de la bóveda **ya no vive en este repositorio**. Está en `core-web/` de
[`AcheronCore`](https://github.com/ProjectEllysia/AcheronCore), junto al motor Java y al catálogo,
y la SPA la consume como `@projectellysia/acheron-core-web` con versión fijada.

Con ella se fueron sus suites, que son las que verificaban el formato de cifrado:

| Suite | Dónde está ahora (en `AcheronCore`) |
|---|---|
| interoperabilidad con el motor Java | `core-web/test/acheron.interop.test.mjs` |
| CRUD de storables | `core-web/test/acheron.crud.test.mjs` |
| concurrencia optimista | `core-web/test/acheron.sync.test.mjs` |
| contratos del motor | `core-web/test/acheron.contract.test.mjs` |
| vectores de interoperabilidad | `vectors/`, compartidos con el motor Java |

Aquí se queda `acheron.schema.test.mjs`, que comprueba lo único que sigue siendo de la SPA: que
`src/components/acheron/storableLabels.js` describa exactamente los campos que declara el esquema, en ambos
sentidos. Un campo sin etiqueta pinta un `undefined` en el formulario; una etiqueta sin campo es
código muerto.

El esquema llega del paquete, que lo genera desde `schema/schema.json` de `AcheronCore` y lo
verifica en su propia suite. Por eso no hay copia del contrato en esta carpeta.

La API sí conserva la suya, en `API/tests/unit/acheron-schema.json`: es un consumidor
independiente que no pasa por el paquete de JavaScript, así que necesita verificar su propio
registro contra el contrato por su cuenta.
