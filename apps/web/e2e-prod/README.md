# Comprobaciones de producción (prod smoke)

Lo que Hermes ejecuta después de un despliegue, en lugar de escribir scripts de Playwright al
vuelo. No forma parte de CI: `playwright.config.ts` de la raíz solo lee `e2e/`.

## Ejecutar

Desde la raíz del repo, con Node 22 en el `PATH`:

```sh
PW_CHANNEL=chrome pnpm --filter @adelia/web smoke:prod
```

- `PROD_SMOKE_URL`: la web a comprobar. Por defecto `https://adelia.godi.ai`.
- `PW_CHANNEL`: canal del navegador. Sin él, el Chromium de Playwright (instálalo una vez con
  `pnpm --filter @adelia/web exec playwright install chromium`). En el Mac de Santiago, `chrome`.
- `PROD_SMOKE_API_URL`: solo contra una pila local, el origen de la API para `/healthz` (en
  producción nginx lo sirve en el mismo dominio).
- `PROD_SMOKE_RUN_DIR`: carpeta de la ejecución. Por defecto
  `~/dev/adelia-design/shots/prod-smoke/<fecha_hora>`.

Salida: `summary.json` en la carpeta de la ejecución, impreso también al final por pantalla, con
cada comprobación (`ok`: `true`, `false` o `null` si no se ejecutó), su detalle, sus capturas y
las invitadas que abrió con si se borraron. El proceso sale con 1 si algo falla.

## Qué comprueba

1. Portada en es/en/fr: carga sin errores de página, línea de consentimiento con enlace a
   Privacidad, botón de grabar la consulta, ninguna petición a un endpoint que responda.
2. Invitada: el botón de grabar crea su espacio y abre la grabadora con el consentimiento; el
   panel muestra Lucía, «Hoy con Lucía», «Grabar la consulta» sin desplazarse y «Guardar mi
   cuenta»; la pregunta de ejemplo de «Primeros pasos» no nombra otra edad que la de Lucía.
3. Conversación sin modelo: dos preguntas urgentes, el campo pasa a «Pregunta más sobre esto»,
   la segunda petición lleva el historial, cuatro mensajes, y tras recargar «Seguir la
   conversación» devuelve el hilo.
4. Limpieza: borra la invitada en Ajustes y `/dashboard` ya no deja entrar.
5. `/healthz` y `/api/version` responden; las versiones van al detalle.
6. Banner de la analítica en la portada, a 390 px: aparece en es/en/fr, «Aceptar» y «Rechazar»
   son el mismo botón, no tapa la caja de pregunta, el dictado, «Preguntar» ni el botón de grabar;
   con «Rechazar» no sale ningún lote y se recuerda al recargar; con «Aceptar» salen lotes sin el
   texto de la pregunta escrita (nunca enviada). Las dos llamadas de la analítica se contestan 204
   dentro del navegador: producción no guarda ni la prueba del consentimiento ni los lotes.
7. Administración: una visita sin sesión va a iniciar sesión y una invitada recibe 404 en
   `/es/dashboard/admin`; ninguna de las dos obtiene cifras de `ADMIN_READS` (analítica y uso de
   la API). La invitada sale del botón de grabar, como en la 2, y se borra al terminar.

## Reglas

- Nunca hace responder a un modelo. Las únicas preguntas que envía están en
  `urgent-questions.json` y son banderas rojas, que el nodo `guard` responde en código
  (`apps/api/tests/test_prod_smoke_questions.py` lo comprueba en CI). Además, en el navegador,
  `browser.ts` aborta todo POST a `/api/demo/ask`, `/api/chat`, `/api/agent` y
  `/api/backend/chat`, y todo turno del agente con otro mensaje, una aclaración o una tarjeta.
- Nunca hay dos invitadas abiertas a la vez, y se borran siempre: la de las comprobaciones 2 a 4
  y la de la 7, una detrás de otra (un solo worker). Si una comprobación falla antes de borrarla,
  `afterAll` la borra con `DELETE /users/me`, y solo si la sesión sigue siendo esa misma
  invitada y la API dice que es invitada. Una invitada que quede sin borrar pone `ok: false`.
- Nunca pulsa «Grabar» (mandaría audio a la transcripción) ni abre una pregunta de ejemplo.

## Añadir una comprobación

Un archivo `NN-nombre.spec.ts` en esta carpeta, con el título empezando por su número (`"6 ..."`
o `"1.es ..."`): ese prefijo es el `id` del resumen. Usa `note()` para el detalle y `shot()` para
las capturas (`browser.ts`). Si abre una página que pueda preguntar, arma antes
`armModelGuard(context)`. Las piezas puras (qué se puede enviar, qué cuenta como fuga o como cifra
de administración) van en `kit.ts` y se fijan en CI en `e2e/prod-smoke-kit.spec.ts`.
