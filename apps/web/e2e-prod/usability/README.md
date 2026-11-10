# Batería de usabilidad

Lo que una madre con el bebé en brazos y el móvil en una mano se encuentra, medido en producción
sin que responda ningún modelo. Va aparte de las comprobaciones de producción (`../README.md`):
otra configuración, otra carpeta de resultados, y ni CI ni `smoke:prod` la ejecutan.

## Ejecutar

Desde la raíz del repo, con Node 22 en el `PATH`:

```sh
PW_CHANNEL=chrome pnpm --filter @adelia/web usability:prod
```

- `PROD_SMOKE_URL`: la web a medir. Por defecto `https://adelia.godi.ai`.
- `PW_CHANNEL`: como en las comprobaciones de producción (`chrome` en el Mac de Santiago).
- `USABILITY_RUN_DIR`: carpeta de la ejecución. Por defecto
  `~/dev/adelia-design/shots/usability/<fecha_hora>`.

Salida, en la carpeta de la ejecución: `report.html` (problemas ordenados por lo que más molesta,
recorridos, rendimiento, primeras pantallas, tarjeta de aclaración, axe, cada comprobación y las
capturas), `summary.json` (lo mismo que el de las comprobaciones de producción más `problems`) y
`data.jsonl` (cada cifra y cada problema, una línea). Unos 20 minutos.

## Qué mide

En 360, 390 y 430 px y una tablet (768), claro y oscuro, es/en/fr:

- `00`: abre la invitada de la batería con el botón de grabar de la portada (Lucía, sin hilo).
- `10` y `11`: la portada de una primera visita (con el banner de cookies) y el panel de la invitada
  sin preguntar. Presupuesto de la primera pantalla (bloques, toques y palabras dentro de la
  primera pantalla, `budgets.json`), controles tapados por otro elemento (banner, barra inferior,
  botón fijo), desplazamiento lateral, zonas táctiles de 44 px en todo lo que se pulsa (también
  dentro de «Más») y el teclado abierto: el viewport pierde `KEYBOARD_HEIGHT` y el campo, y en el
  panel el botón de enviar, tienen que verse enteros y sin nada encima.
- `20`: dos banderas rojas en el panel de la invitada (el código responde antes de cualquier
  modelo); el 112 tiene que estar en pantalla al llegar cada respuesta.
- `21`: el hilo tras recargar: «Seguir la conversación» en la primera pantalla, el 112 visible al
  seguir, presupuesto, solapes, zonas táctiles y teclado.
- `30`: un plan y una tarjeta de aclaración de dos preguntas, **simulados dentro del navegador**
  (`fixtures.json`, `kit.stubTurnFor`): ninguna de esas preguntas sale del navegador. El plan abre
  con su frase y «Hoy» en la primera pantalla, el salto a «Cuándo ir al médico» está ahí y lleva a
  un apartado abierto, el descargo se ve. La tarjeta: botones de 44 px a todo el ancho, la primera
  pregunta entera en pantalla, «O escríbemelo» a la vista, nada en el cuarto superior de un móvil,
  y dos toques mandan un solo turno con las dos respuestas. axe sobre el plan a 390.
- `40`: axe (serio o crítico) en portada, panel, ajustes, privacidad y una urgencia real, a 390.
- `45`: rendimiento con CPU x4 y 4G lenta, caché fría, mediana de tres cargas: LCP de portada y
  panel, tiempo hasta que el campo acepta lo que escribe (React lo ha hidratado) y JavaScript
  descargado por página, contra `kit.PERF_LIMITS`.
- `50`: borra la invitada de la batería.
- `60`: el recorrido entero con una invitada propia: portada, urgencia escrita en la portada (abre
  su espacio), seguir el hilo, recargar y seguir, la grabadora (sin pulsar «Grabar»), «Más», cerrar
  Telegram si aparece, Ajustes y borrar. Cuenta toques y tiempo de cada paso.

## Orden de los problemas

`kit.ISSUE_KINDS`, de lo que más le cuesta a lo que menos: un aviso, «Cuándo ir al médico» o la
urgencia que no se ven; un recorrido que no se puede terminar; un control tapado; el teclado sobre
el campo; la tarjeta que no se usa con un pulgar; una respuesta que no empieza por lo que hay que
hacer; zonas táctiles pequeñas; desplazamiento lateral; el banner tapando algo secundario; lentitud;
errores de la página; axe; peso de JavaScript; y una primera pantalla que ha crecido. Dentro de
cada tipo, el que pasa en más sitios primero.

## Reglas

Las de las comprobaciones de producción (`../README.md`): `X-AdelIA-QA: 1` en toda petición, el
guardia del modelo armado en cada contexto, nunca dos invitadas a la vez y siempre borradas
(`50`, el recorrido, y `teardown.ts` si algo se rompió antes), nunca «Grabar» ni una pregunta de
ejemplo. Además, el plan y la tarjeta se contestan en el navegador: `stubTurnFor` solo reconoce los
mensajes de `fixtures.json` y deja pasar lo demás al guardia, que solo admite las dos banderas rojas.
`apps/api/tests/test_usability_fixtures.py` fija que la tarjeta y los títulos del plan son los del
contrato y que esos mensajes no son banderas rojas.

## Cambiar un presupuesto o un límite

`budgets.json` y `kit.PERF_LIMITS` salen de la ejecución en producción del 2026-11-10. Que una
primera pantalla crezca es un fallo hasta que alguien decide que el cambio lo vale y sube el
número en el mismo commit que el cambio, diciendo por qué. Para regenerarlos desde una ejecución:
el máximo por clave de las líneas `first-screen` de `data.jsonl` (claro y oscuro miden lo mismo).
