/**
 * Presentación de los tipos de storable: lo que se ve en pantalla y cómo se
 * comporta el formulario. Los textos no están aquí sino en los ficheros de
 * idioma; cada entrada lleva la clave de su rótulo (`labelKey`, y en el tipo
 * también `pluralKey` y `newLabelKey`). Es la otra mitad de `storableSchema.js`, y la que
 * NO viaja al paquete compartido — la extensión de navegador no pinta este
 * formulario y no necesita estas cadenas.
 *
 * Indexado por `kind`, y dentro por la clave del campo, para que la
 * correspondencia con el esquema sea comprobable. `storableTypes.js` compone
 * ambos ficheros y `acheron.schema.test.mjs` verifica que no se desincronizan:
 * un campo sin etiqueta pinta un `undefined`, y una etiqueta sin campo es
 * código muerto que nadie ve.
 *
 * Por campo, más de `labelKey`:
 *   - prefill:   en EDICIÓN se pre-rellena con el valor actual. Los secretos
 *                más sensibles (contraseña, PAN, CVV) van a false: se dejan en
 *                blanco y solo se reescriben si el usuario teclea algo.
 *                Ojo, NO equivale a `!secret` del esquema: `documentId`,
 *                `iban`, `swiftBic`, `accountNumber` y `licenseKey` son
 *                secretos y aun así se pre-rellenan. Son dos ejes distintos.
 *   - numeric:   teclado/inputmode numérico.
 *   - multiline: se pinta como textarea.
 *   - minLength: longitud mínima exigida cuando el campo lleva valor.
 *
 * `subtitleKey` no lo lee nadie hoy; se conserva tal cual estaba, pendiente de
 * decidir si la lista debe mostrar ese subtítulo o si sobra.
 */
export const STORABLE_LABELS = {
  account: {
    labelKey: 'acheron.types.account.label', pluralKey: 'acheron.types.account.plural', newLabelKey: 'acheron.types.account.newLabel',
    subtitleKey: 'username',
    fields: {
      username: { labelKey: 'acheron.fields.account.username' },
      domain: { labelKey: 'acheron.fields.account.domain' },
      password: { labelKey: 'acheron.fields.account.password', prefill: false },
    },
  },
  creditcard: {
    labelKey: 'acheron.types.creditcard.label', pluralKey: 'acheron.types.creditcard.plural', newLabelKey: 'acheron.types.creditcard.newLabel',
    subtitleKey: 'cardNumber',
    fields: {
      cardHolderName: { labelKey: 'acheron.fields.creditcard.cardHolderName' },
      cardNumber: { labelKey: 'acheron.fields.creditcard.cardNumber', prefill: false, numeric: true, minLength: 4 },
      expirationDate: { labelKey: 'acheron.fields.creditcard.expirationDate' },
      cvv: { labelKey: 'acheron.fields.creditcard.cvv', prefill: false, numeric: true },
      postalCode: { labelKey: 'acheron.fields.creditcard.postalCode' },
    },
  },
  securenote: {
    labelKey: 'acheron.types.securenote.label', pluralKey: 'acheron.types.securenote.plural', newLabelKey: 'acheron.types.securenote.newLabel',
    subtitleKey: 'content',
    fields: {
      content: { labelKey: 'acheron.fields.securenote.content', multiline: true },
    },
  },
  identity: {
    labelKey: 'acheron.types.identity.label', pluralKey: 'acheron.types.identity.plural', newLabelKey: 'acheron.types.identity.newLabel',
    subtitleKey: 'fullName',
    fields: {
      fullName: { labelKey: 'acheron.fields.identity.fullName' },
      email: { labelKey: 'acheron.fields.identity.email' },
      phone: { labelKey: 'acheron.fields.identity.phone' },
      address: { labelKey: 'acheron.fields.identity.address' },
      city: { labelKey: 'acheron.fields.identity.city' },
      country: { labelKey: 'acheron.fields.identity.country' },
      documentId: { labelKey: 'acheron.fields.identity.documentId' },
    },
  },
  bankaccount: {
    labelKey: 'acheron.types.bankaccount.label', pluralKey: 'acheron.types.bankaccount.plural', newLabelKey: 'acheron.types.bankaccount.newLabel',
    subtitleKey: 'bankName',
    fields: {
      bankName: { labelKey: 'acheron.fields.bankaccount.bankName' },
      holder: { labelKey: 'acheron.fields.bankaccount.holder' },
      iban: { labelKey: 'acheron.fields.bankaccount.iban' },
      swiftBic: { labelKey: 'acheron.fields.bankaccount.swiftBic' },
      accountNumber: { labelKey: 'acheron.fields.bankaccount.accountNumber' },
    },
  },
  wifi: {
    labelKey: 'acheron.types.wifi.label', pluralKey: 'acheron.types.wifi.plural', newLabelKey: 'acheron.types.wifi.newLabel',
    subtitleKey: 'ssid',
    fields: {
      ssid: { labelKey: 'acheron.fields.wifi.ssid' },
      password: { labelKey: 'acheron.fields.wifi.password', prefill: false },
      securityType: { labelKey: 'acheron.fields.wifi.securityType' },
    },
  },
  license: {
    labelKey: 'acheron.types.license.label', pluralKey: 'acheron.types.license.plural', newLabelKey: 'acheron.types.license.newLabel',
    subtitleKey: 'product',
    fields: {
      product: { labelKey: 'acheron.fields.license.product' },
      licenseKey: { labelKey: 'acheron.fields.license.licenseKey' },
      licensedTo: { labelKey: 'acheron.fields.license.licensedTo' },
      version: { labelKey: 'acheron.fields.license.version' },
    },
  },
}
