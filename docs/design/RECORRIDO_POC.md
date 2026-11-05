# Recorrido de una madre nueva con cuenta (prueba de concepto)

Noche del 5 al 6 de noviembre de 2026, rama `night/cc-journey`. Recorrido hecho en Chrome real
(Playwright, canal `chrome`) a 390x844, en español y en francés, y una vez en español a 1280x800,
contra la API y la web locales (puertos 8092 y 3092) **sin ninguna clave de modelo** (Mistral,
OpenAI y Anthropic vacías) y sin clave de Resend.

Capturas: `~/dev/adelia-design/shots/journey/` (`antes/` con el estado de `origin/main`; en la raíz,
el estado con los arreglos). Nombre: `<idioma>-<ancho>-<paso>-<nombre>.png`.

Spec que recorre el viaje entero y queda en verde: `apps/web/e2e/poc-journey.spec.ts` (es y fr,
390 px). Solo simula dos cosas que necesitan un modelo: la respuesta del agente tras «Volver a
preguntar» y el informe listo para compartir (sembrado en la base de datos). El enlace mágico se
siembra en `verification_tokens` igual que lo haría el email (`e2e/utils/session.ts`,
`magicLinkPath`); es el único atajo del alta. El job `e2e` de CI no tiene MinIO: allí la subida se
rechaza y la spec siembra la fila que la API habría escrito (anotación `seeded` en el informe); en
local, con MinIO, la subida es real.

## Cómo leer las tablas

- **Estado**: «Bien», «Con fallos» (se puede seguir pero confunde) o «Roto» (no se puede seguir o
  engaña). Si se arregló esta noche, «Roto → bien».
- **Toques y tiempo**: toques desde la pantalla anterior; tiempo medido en local, sin red real ni
  modelo. No son tiempos de producción.
- **Arreglo**: lo hecho esta noche con su test, o «Documentado» si es de otra sesión o pide una
  decisión de producto.

## Español, 390x844

| # | Paso | Estado | Toques y tiempo | Problema | Impacto | Arreglo |
|---|---|---|---|---|---|---|
| 1 | Alta: email y enlace | Roto → bien | 2 toques; 4,6 s | Sin proveedor de email (Resend respondió 401) la pantalla decía «Revisa tu correo ✉️». `signIn({redirect:false})` no lanza en ese caso: devuelve `/api/auth/error?error=Configuration` y la acción lo daba por enviado. | Alto: espera un email que nunca sale y no puede entrar. | `signin/actions.ts`: una URL con `error` es fallo y muestra «No pudimos enviar el email». Test e2e `the sign-in form never says the link left when it did not`. |
| 2 | Enlace del email | Bien | 1 toque; 0,9 s | Cuenta creada en prueba gratuita sin tarjeta (`subscription_status` vacío, 30 días por `created_at`). | | Cubierto en la spec. |
| 3 | Onboarding (nombre, fecha, sexo) | Bien | 4 toques; 0,2 s | | | |
| 4 | Inicio | Con fallos → bien | 0 toques; 0,7 s | Dos chips: «Lucía» y «Mi perfil». La fila propia la crea `GET /enrichment/profiles` antes del onboarding; vacía, en español también en francés, y con la palabra «perfil» que la guía de voz evita. | Medio: duda de qué es «Mi perfil» y si ha creado dos cuentas. | `routers/users.py`: al completar el onboarding se retira la fila propia si no tiene documentos, entidades, informes ni anotaciones. Tests `test_onboarding_retires_the_empty_mi_perfil_row` y `..._keeps_an_own_profile_that_holds_documents`. |
| 4b | Inicio: «Hoy con Lucía» | Con fallos | | Lo primero que lee una madre nueva es, en color de aviso, «Sin anotar y ya tocaba: Hexavalente DTPa-VPI-Hib-HB, 1.ª dosis · Neumococo conjugada…». Suena a reproche y los nombres son de ficha técnica. | Medio. | Documentado: texto clínico del calendario vacunal, no lo toco de noche. |
| 4c | Inicio: «Primeros pasos» | Con fallos | | El ejemplo es «¿Es normal que con 13 meses solo quiera leche materna?» para una bebé de 4 meses. En el móvil la cabecera repite «Subir», que ya está en la barra inferior (regla 18). | Bajo. | Documentado. |
| 5 | Primera pregunta al agente, sin clave | Con fallos → bien | 2 toques; error en menos de 1 s | «Ups, algo falló. Inténtalo otra vez.» sin botón: había que volver a escribir. La guardia de banderas rojas sí funciona sin clave (corre antes que cualquier modelo). | Medio: no sabe si el problema es suyo ni qué hacer. | `agent-canvas.tsx`: si la API responde con error, «Ahora no puedo responderte. No es tu conexión: vuelve a intentarlo en unos minutos. Si algo te preocupa, llama a tu pediatra.» y «Volver a preguntar», que reenvía la misma pregunta una vez y saca el intento fallido del historial. Una confirmación no se reenvía (podría anotar dos veces). Spec, paso 4. |
| 5b | Debajo de la respuesta fallida | Con fallos | | La tarjeta «Diario por Telegram · Enlazar» aparece justo debajo del error (y bajo cada respuesta). | Bajo. | Documentado. |
| 6 | Misma pregunta en el chat, sin clave | Roto → bien | 3 toques (fila «Pregunta con citas»); error en menos de 1 s | «No pude procesar tu pregunta. Revisa tu conexión…»: culpa a su conexión, que funciona. | Medio: la manda a revisar un wifi que va bien. | `chat-page-client.tsx`: mismo mensaje honesto y «Volver a preguntar» en la misma conversación; el error de red de verdad sigue diciendo «revisa tu conexión». Spec, paso 5. |
| 6b | Chat de una cuenta sin documentos | Con fallos | | Abre con «Primero sube un documento. Para responder sobre tu bebé, AdelIA necesita al menos un documento», pero el chat responde con evidencia sin documentos. | Medio: parece que no puede preguntar todavía. | Documentado: decisión de producto. |
| 7 | Anotar «hoy ha tenido 37,8 a las 5» | Bien | 2 toques; tarjeta en 0,8 s | Leído por reglas (`agent/record.py`), sin modelo. «Temperatura: 37,8 °C, hoy a las 17:00», «Sí» a dos tercios. Pasada la medianoche, «a las 5» se guarda como ayer a las 17:00, que es lo razonable. | | Cubierto en la spec. |
| 8 | Confirmar | Bien | 1 toque; menos de 1 s | «Anotado: 37,8 °C, hoy a las 17:00.» | | |
| 9 | «Hoy con Lucía» | Bien | 1 toque (Inicio); 0,7 s | «Temperatura: hoy 37,8 °C.» | | Cubierto en la spec. |
| 10 | Subir un PDF | Con fallos | 3 toques; vuelve al Inicio en unos 2 s | Sin clave el OCR falla (esperado). El aviso de subida dice «Subido. Procesando OCR…» (jerga). | Bajo. | Documentado. |
| 11 | Historial | Con fallos → bien | 1 toque; 0,4 s | El nombre del archivo salía como «sa…» a 390 px: la pista de error ocupaba media fila. La pista dice «prueba una foto más clara» aunque el fallo sea del servidor y el archivo un PDF. Encima, «Sube el último informe…» justo después de subir uno; píldoras «Insights», «Control reflujo». | Medio: no reconoce cuál de sus documentos falló. | `document-card.tsx` y `status-badge.tsx`: la pista va en su propia línea y el nombre tiene el ancho. Spec, paso 9 (`scrollWidth <= clientWidth`). El resto, documentado. |
| 12 | Generar el informe para el especialista | Con fallos | 3 toques (Resúmenes, Crear, Generar); falla en unos 20 s sin clave | Falla con dignidad («No pudimos generar el resumen» y dos salidas). Textos con jerga: «Briefings», «Crear nuevo briefing», «soft-delete», «data nueva». | Medio. | Documentado: es tema de la sesión de briefing. |
| 13 | Compartir | Bien en la API; sin verificar en producción | 4 toques (Compartir, aviso de privacidad, Generar, Copiar) | El enlace es `{adelia_app_url}/s/<token>`, pero la web no tiene ruta `/s/`: en local abre 404 en la web y solo responde la API. En producción depende del proxy, que no he mirado (no toco producción). «Duración del link», «24 horas (default)». | Alto si el proxy no lo enruta: el pediatra recibe un 404. | Documentado. La spec comprueba el enlace contra la API, sin cuenta. Verificar en producción con un humano. |
| 14 | Ajustes | Con fallos | 1 toque; 0,8 s | El email parte la palabra; «formato FHIR (el estándar…)», «entidades, briefings, links compartidos». | Bajo. | Documentado. |
| 15 | Exportar datos | Bien | 1 toque; 0,2 s | JSON de 1 KB con el perfil de Lucía, el documento y la anotación 37,8. | | Cubierto en la spec. |
| 16 | Cerrar sesión | Roto → bien | antes: imposible; ahora 2 toques (Ajustes, Cerrar sesión); 0,6 s | No había ningún «Cerrar sesión» en la app: `signOut` solo se llamaba tras borrar la cuenta. | Alto: en un móvil compartido o perdido, el historial de su bebé quedaba abierto. | `account-settings-view.tsx`: apartado «Sesión» con «Cerrar sesión», vuelve a la portada en su idioma. Spec, paso 13. |
| 17 | Volver a entrar | Bien | 3 toques; 0,9 s | Directa a «¿Cómo está Lucía?», sin repetir el onboarding. | | Cubierto en la spec. |
| 18 | Borrar la cuenta | Bien | 3 toques y escribir el email; 0,3 s | Tras borrar iba a `/`, que elige idioma por el navegador. | Bajo. | Ahora vuelve a `/{idioma}`. La spec comprueba que la fila del usuario ya no existe. |

## Francés, 390x844

Mismo recorrido y mismos resultados que en español, con estas diferencias:

| # | Paso | Estado | Problema | Impacto | Arreglo |
|---|---|---|---|---|---|
| F1 | Inicio | Roto → bien | Chip «Mi perfil» en español. | Medio. | El mismo arreglo del paso 4. |
| F2 | Bajo cada respuesta | Roto → bien | Tarjeta «Diario por Telegram · Enlaza Telegram y cada tarde te preguntaré… · Enlazar» en español: `agent/suggestions.py` recibía `locale` y lo ignoraba. | Medio: una madre francesa lee español en cada turno. | Textos de las tarjetas en es/en/fr (`_TEXT`); español si el idioma no existe. Test `test_suggestions_speak_her_language`. |
| F3 | Chat | Con fallos | La lista de conversaciones dice «Nueva conversación» (título por defecto en `models.py` y `chat_repo.py`, en español). | Bajo. | Documentado: lo correcto es titular con la primera pregunta. |
| F4 | «Hoy avec Lucie» y descargo | Con fallos | «dites-le-moi» y «Vérifiez avec votre médecin» tratan de vous; el resto de la app tutea. | Bajo. | Documentado: el descargo es texto clínico fijo. |
| F5 | Cerrar sesión | Sin reproducir | Una vez, React #418 (hidratación) al volver a la portada tras cerrar sesión. No se repitió en cargas en frío de `/fr` y `/fr/signin` ni en 3 pasadas francesas de la spec, que fallan ante cualquier error de página. | Bajo. | Documentado; la portada es de otra sesión. |

## Escritorio, 1280x800 (español)

Mismos resultados que a 390 en todos los pasos, sin errores de página. Dos diferencias:

| # | Paso | Estado | Problema | Impacto | Arreglo |
|---|---|---|---|---|---|
| D1 | Anotar | Con fallos | «¿Lo anoto así?» sale en el rail derecho, lejos de la frase que acaba de escribir, y con «Diario por Telegram» debajo. En el móvil, mientras espera una tarjeta del turno no se pinta ninguna sugerencia (regla 16); en escritorio sí. | Bajo-medio: hay que buscar el «Sí» al otro lado de la pantalla. | Documentado. |
| D2 | Cabecera | Con fallos | «Insights», «Resúmenes», «Control reflujo», «Importar» y «Modo Consulta» compiten con la pregunta. | Bajo. | Documentado. |

## Lo que no he podido verificar

- El email real del enlace mágico (no hay clave de Resend en local). El alta se probó con el
  enlace que llevaría ese email.
- Respuestas reales del agente y del chat, OCR del PDF y la generación del informe: necesitan
  claves. Sin clave degradan como describe la tabla.
- El enlace público `/s/<token>` en producción.
- Modo oscuro de los dos botones nuevos («Volver a preguntar», «Cerrar sesión»): usan
  `ad-btn-ghost`, el mismo estilo ya comprobado en Ajustes, pero no hice capturas en oscuro.
