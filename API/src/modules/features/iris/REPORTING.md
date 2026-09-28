# Iris — Canal de reporte

Cómo reporta un correo sospechoso un cliente de correo (un complemento de Outlook o de Gmail, una
extensión del navegador o un script) sin que el usuario tenga que copiar cabeceras ni guardar un
`.eml`. Este documento es el contrato para quien escribe ese cliente.

## 1. La credencial: un token de integración

El usuario crea un token en el panel (**Iris → Integraciones → Tokens de integración**) o con
`POST /iris/integration-tokens` (con su sesión). El token completo se enseña **una sola vez**:

```
irt_3f9c0a1b2c3d4e5f.Qm9sZXRpbiBkZSBzZWd1cmlkYWQgcGFyYSBJcmlz...
```

- Solo sirve para **reportar** y para **consultar cómo acabó lo reportado**. No abre una sesión:
  no lee el historial, no borra nada, no cambia nada de la cuenta.
- Caduca (por defecto a los 180 días; como mucho 365, `features.iris.reporting`).
- Se revoca desde el panel o con `DELETE /iris/integration-tokens/<id>`, y deja de valer al momento.
- En cada uso se comprueba que su dueño sigue teniendo permiso para crear análisis de Iris
  (`IRIS_CREATE`): si se lo quitan, todos sus tokens dejan de funcionar sin revocarlos.
- Un token inválido, revocado o caducado responde siempre lo mismo: `401` con
  `messageKey: "irisInvalidIntegrationToken"`. El cliente debe pedir al usuario un token nuevo.

Se manda en la cabecera estándar:

```
Authorization: Bearer irt_3f9c0a1b2c3d4e5f.Qm9s...
```

## 2. Reportar: `POST /iris/reports`

El mensaje se manda **entero**, no solo sus cabeceras: con el cuerpo, los enlaces y los adjuntos,
Iris aplica todas sus reglas. Dos formas equivalentes:

| Forma | `Content-Type` | Dónde va el mensaje |
|---|---|---|
| Tal cual | `message/rfc822` | El cuerpo de la petición es el `.eml` |
| Formulario | `multipart/form-data` | Campo `message`, fichero `.eml` o `.msg` de Outlook |

Cabecera opcional `X-Ellysia-Report-Channel` (o campo `channel` del formulario) con uno de
`outlook_addin`, `gmail_addon`, `browser_extension` o `api`. Cualquier otro valor cuenta como `api`.
Solo sirve para enseñar en el informe desde dónde llegó.

### Qué mensaje mandar: el original o un reenvío como adjunto

- **El original** (lo que da el cliente de correo al exportar el mensaje). Es lo mejor: llega con
  todas sus cabeceras de entrega.
- **Un mensaje que lleva el original adjunto** como `message/rfc822` (lo que hace «Reenviar como
  adjunto»). Iris detecta el adjunto, analiza el **original** y conserva quién lo reenvió y con qué
  asunto: el informe lo enseña como «correo reenviado como adjunto». Si el envoltorio resulta más
  sospechoso que el original, el veredicto sale del envoltorio y se dice.

Un reenvío **en línea** (el cuerpo del original pegado dentro del mensaje nuevo) pierde las
cabeceras originales: no lo hagas.

### Respuestas

| Código | Cuándo | Cuerpo |
|---|---|---|
| `201` | Aceptado; el análisis corre en segundo plano | `{"analysisId": 42, "status": "pending", "isDuplicate": false, "reportChannel": "outlook_addin"}` |
| `200` | Ese mismo mensaje ya estaba analizado: no se repite ni se cobra | el análisis que ya existía, con `"isDuplicate": true` |
| `400` | No llegó mensaje, no es `.eml`/`.msg`, pasa de `maxMessageBytes` o no tiene cabeceras suficientes | error con `error_description` en castellano |
| `401` | Token ausente, mal formado, desconocido, revocado o caducado | `messageKey: "irisInvalidIntegrationToken"` |
| `402` | El usuario agotó los análisis de su plan | error de cuota |
| `403` | El dueño del token ya no tiene permiso para crear análisis | |
| `429` | Más de 60 reportes por hora o 300 por día con el mismo token | |

## 3. Saber cómo acabó: `GET /iris/reports/<analysisId>`

Con el mismo token. Devuelve solo lo imprescindible para un aviso breve en el cliente
(«Gracias. Iris lo considera phishing»):

```json
{"analysisId": 42, "status": "finished", "verdict": "Phishing", "totalScore": 12.0,
 "finishedAt": "2026-09-28T10:00:03Z"}
```

`status` pasa por `pending` → `running` → `finished` (o `failed`/`cancelled`). Sondea cada pocos
segundos; un análisis suele tardar menos de diez. El informe completo se ve en el panel.

## 4. Ejemplos

### curl / script

```bash
curl -sS https://ellysia.example/iris/reports \
  -H "Authorization: Bearer $IRIS_TOKEN" \
  -H "X-Ellysia-Report-Channel: api" \
  -H "Content-Type: message/rfc822" \
  --data-binary @sospechoso.eml
```

### Complemento de Gmail (Apps Script)

```javascript
function reportCurrentMessage(event) {
  const message = GmailApp.getMessageById(event.gmail.messageId);
  const response = UrlFetchApp.fetch('https://ellysia.example/iris/reports', {
    method: 'post',
    contentType: 'message/rfc822',
    payload: message.getRawContent(),
    headers: {
      Authorization: 'Bearer ' + PropertiesService.getUserProperties().getProperty('IRIS_TOKEN'),
      'X-Ellysia-Report-Channel': 'gmail_addon',
    },
    muteHttpExceptions: true,
  });
  return JSON.parse(response.getContentText());
}
```

### Complemento de Outlook (Office.js)

Office.js da el mensaje entero como `.eml` en base64 con `getAsFileAsync` (conjunto de requisitos
Mailbox 1.14 o posterior):

```javascript
Office.context.mailbox.item.getAsFileAsync((result) => {
  const eml = Uint8Array.from(atob(result.value), (character) => character.charCodeAt(0));
  fetch('https://ellysia.example/iris/reports', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'X-Ellysia-Report-Channel': 'outlook_addin',
      'Content-Type': 'message/rfc822',
    },
    body: eml,
  });
});
```

Un complemento de Outlook se ejecuta en una página web con su propio origen: añade ese origen a
`ALLOWED_ORIGINS` en `API/.env`, o el navegador bloqueará la petición (CORS). Una extensión del
navegador que llama desde su *service worker* con permiso sobre el dominio de Ellysia no lo
necesita.

## 5. Lo que el canal no hace

- No recibe correo por SMTP (no hay un buzón «phishing@» al que reenviar). Si se quiere ese
  flujo, un script que lea ese buzón y llame a `POST /iris/reports` lo cubre con este mismo contrato.
- No actúa sobre el buzón del usuario (mover, borrar): eso es la cuarentena, con su propio permiso.
