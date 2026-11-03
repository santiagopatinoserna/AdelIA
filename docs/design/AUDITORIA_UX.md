# Auditoría UX de AdelIA (3 de noviembre de 2026)

Estado auditado: `main` = `57c23dd` (mismo código que producción `b641f42` más documentación).
Para quién: una madre con el bebé llorando en brazos, una mano libre, a las 3 de la mañana.
Dos momentos: AHORA (qué hago ya, una pantalla) y CON CALMA (detalle y fuentes, plegado).

## Método

- Chrome real (canal `chrome` de Playwright, Google Chrome instalado) contra la API y la web
  locales, a 390x844 en claro y oscuro y a 1280x800 en claro, en es, en y fr. Movimiento
  reducido para que ninguna captura salga a media animación.
- Script reproducible: `apps/web/scripts/redesign/screens.shots.ts`
  (`SHOTS_PHASE=before pnpm exec playwright test -c scripts/redesign/shots.config.ts`).
  Capturas en `~/dev/adelia-design/shots/redesign/before/` (343 PNG, primera pantalla y página
  entera) y métricas en `before/metrics/*.json`.
- Respuestas: las urgencias y la pregunta con botones son las que devuelve la API local (código
  determinista). Los planes son salidas reales del contrato de plan guardadas en las sondas de
  octubre (`plan-probe-v2.json`: 498, 534 y 696 palabras en es, en y fr; 327 a 390 para la
  pregunta de regurgitación). La respuesta corta, «solo madres» y «sin evidencia» son datos de
  prueba con el texto fijo real del código. Nada de esto prueba que una respuesta médica sea
  correcta: mide lo que la pantalla hace con ella.
- Toques y segundos: modelo KLM simple, con las mismas constantes antes y después, sin contar
  la latencia de red ni del modelo (no depende del diseño):
  toque 1,1 s; decisión 1,2 s (una al empezar y una por toque); escribir con una mano 0,6 s por
  carácter; leer 0,3 s por palabra que hay que atravesar antes de la acción; 1 s por pantalla de
  desplazamiento. Es una estimación comparativa, no una medida con madres.

## Resumen de cifras (390x844, claro)

| Pantalla | Palabras en la 1.ª pantalla (es / en / fr) | Altura total | Dónde está lo que importa |
|---|---|---|---|
| Portada | 145 / 122 / 138 | 1,2 pantallas | Campo y botón dentro (botón acaba a 406 / 429 / 438 px) |
| Plan | 171 / 165 / 166 | 3,8 / 3,7 / 5,2 pantallas | «Cuándo ir al médico» a 1.324 / 1.347 / 1.567 px; «Hacer otra pregunta» a 2.759 / 2.747 / 4.021 px |
| Respuesta corta | 232 / 204 / 222 | 1,2 | La respuesta empieza a 132 px |
| Pregunta con botones | 132 / 112 / 123 | 1,2 | Primer botón tras 40 a 43 palabras |
| Solo madres | 201 / 188 / 153 | 1,2 a 1,3 | Bien |
| Sin evidencia | 176 / 151 / 167 | 1,2 | Titulada «Tu plan» / «Your plan» / «Ton plan» |
| Urgencia | 158 / 174 / 160 | 1,5 a 1,6 | «Llama al 112» tras 70 / 69 / 80 palabras, sin llamada en un toque |
| Inicio con cuenta | 143 / 146 / 156 | 1 | 18 controles en la primera pantalla |
| Chat con respuesta | 77 a 81 (vacío) | 1 | Salta al final: aterriza en la lista de fuentes |

## Por pantalla

### 1. Portada (es la demo; `/demo` redirige aquí)
- Sobra: la segunda frase de la entradilla, «busca donde él ha estudiado» (rara y en
  masculino); tres líneas de entradilla para algo que el titular ya dice. La palabra «Demo»
  aparece dos veces en la primera pantalla.
- Falta: el micrófono existe, pero es un icono en la esquina superior del campo, en la zona
  difícil del pulgar; para quien no puede escribir es la entrada más rápida y no se ve.
- Confunde: «Empezar» arriba a la derecha (¿empezar qué?); el botón «Preguntar» vacío parece
  secundario.
- Bien: campo, botón y una sugerencia dentro de la primera pantalla en los tres idiomas; sin
  desplazamiento lateral; el precio y las fuentes están plegados.
- Toques: sugerencia 1; pregunta propia 2 más escribir.

### 2. Historial de ejemplo (Lucía)
- Bien plegado y etiquetado como Demo. Abierto es largo, pero es el momento CON CALMA.

### 3. Espera
- El aviso «Consulta enviada. Esperando respuesta…» es gris y pequeño, y las tres sugerencias
  siguen a la vista (desactivadas) debajo: ruido mientras espera.

### 4. Plan (el problema más visible)
- Sobra: 25 a 30 marcadores de cita crudos (`[ev_1][ev_3][ev_4]`) con el mismo peso que el
  texto; en una frase de 20 palabras ocupan media línea.
- Falta: una forma de llegar a «Cuándo ir al médico» sin recorrer 1,6 a 1,9 pantallas; una
  forma de hacer otra pregunta sin bajar hasta el final (3,3 a 4,8 pantallas).
- Confunde: «Cuándo ir al médico» va en un bloque rojo de error entero: alarma aunque la
  mayoría de sus líneas sean «en consulta programada». El título «Tu plan» (20 px) pesa menos
  que la frase de apertura (18 px medio).
- Bien: el texto del modelo se ve entero, sin recortes; solo las fuentes van plegadas; el
  descargo va tras la respuesta.

### 5. Respuesta corta
- Bien: una frase grande y tres viñetas, 1,2 pantallas. Mismos marcadores crudos.

### 6. Pregunta con botones
- Bien: una pregunta, cuatro botones de 44 px. Los botones van alineados a la izquierda y
  parecen campos; el «No la he medido» es un enlace de texto pequeño.

### 7. Solo experiencias de madres
- Bien: título propio, frase fija, sección gris etiquetada. La etiqueta «Experiencias de otras
  familias, no evidencia médica» aparece dos veces (sección y fuentes): correcto por seguridad.

### 8. Sin evidencia
- Error: se titula «Tu plan» / «Ton plan» sobre una respuesta que no es un plan (problema 5.1
  del relevo). Lo mismo para `evidence_only`, cuyas fuentes además quedan plegadas cuando son
  lo único que hay.
- En fr el descargo de la API trata de «vous» y la interfaz de «tu» (texto de la API, fuera de
  este trabajo; anotado).

### 9. Urgencia
- Sobra: «Esto no puede esperar» (título), la caja «No puedo valorar a tu bebé a distancia» y
  «Esto no puede esperar a una respuesta mía» dicen lo mismo tres veces antes de la acción.
- Falta: la acción en un toque. «Llama al 112» está en el tercer párrafo, tras 70 a 80
  palabras; para llamar hay que salir, abrir el teléfono y marcar.
- Confunde: el rojo de error en título y caja grita; la urgencia debe destacar sin alarmar.

### 10. Inicio con cuenta («Hoy con Nora»)
- Sobra: el botón Subir de la cabecera (verde, el más fuerte de la pantalla) repite la pestaña
  «Subir» de la barra inferior; el saludo «Hola 👋 ¿En qué te ayudo con la salud de tu bebé?» es
  genérico aunque sabemos que se llama Nora; el marcador de texto del campo es una instrucción
  («Escribe o pulsa el micro…»).
- Falta: jerarquía. «Hoy con Nora», lo más útil de la pantalla, va en el nivel tipográfico más
  débil (mono, 11 px, mayúsculas).
- Confunde: la línea de vacunas va en rojo de error con nombres técnicos
  («Hexavalente DTPa-VPI-Hib-HB, 1.ª dosis…»): alarma por un recordatorio.
- 143 a 156 palabras y 18 controles en la primera pantalla.

### 11. Anotar (tarjeta de confirmación)
- Error: una burbuja vacía del asistente aparece antes de la tarjeta.
- Sobra: la sugerencia «Diario por Telegram» se pinta justo debajo de «¿Lo anoto así?» y
  compite con la decisión.
- Bien: la tarjeta muestra la entrada tal y como se guarda; Sí y No de 44 px.
- Toques: 3 (campo, enviar, Sí) más escribir «hoy ha tenido 37,8».

### 11c. Respuesta del agente con cuenta (descubierto en la auditoría)
- Error grave: el agente de `/dashboard` pinta el texto tal cual, sin Markdown: un plan llega
  como «## Hoy - **Sigue con tomas…** [2][ev_2]. - **Observa…»: sin apartados, sin viñetas,
  sin descargo visible junto a la respuesta. Es la superficie principal con cuenta.

### 12. Chat (`/dashboard/chat`)
- Sobra: dos cabeceras apiladas (la de la app y «Preguntar a AdelIA» con menú): 260 px.
- Confunde: al terminar, la vista salta al final y aterriza en la lista de fuentes, no en
  «Hoy»; el plan no se pinta como plan (sin apartados) y las fuentes van abiertas.
- El marcador del campo se corta en una línea.

### 13 a 17. Historial, Subir, Consulta, Grabar, Ajustes
- Historial: un menú (Chat, Subir, Control reflujo y cuatro más) que repite la barra inferior;
  «Mis documentos» queda bajo el pliegue.
- Subir: correcto; «¿Qué puedo subir?» mide menos de 44 px.
- Consulta: dos herramientas en la misma pantalla (grabar y dictar notas).
- Grabar: correcto; el consentimiento antes de grabar es la decisión correcta.
- Ajustes: largo pero claro.

### 18 y 19. Alta y onboarding
- Alta: «Enviar magic link» (anglicismo) y «El vault de salud de tu bebé, con IA basada en la
  ciencia» (palabras de folleto).
- Onboarding: correcto; la entradilla es larga (2 frases y una condición).

### Escritorio (1280)
- La portada es una columna de 680 px: bien. El inicio con cuenta acumula 26 controles en la
  cabecera y la primera pantalla, 14 de ellos de menos de 44 px.

## Toques y segundos hasta «qué hago ahora» (antes)

| Tarea | Toques | Escribir | Palabras antes de la acción | Desplazamiento | Estimación |
|---|---|---|---|---|---|
| «bebé de 5 meses que regurgita y llora» → primera acción de «Hoy» | 2 | 36 car. | 40 (es) / 66 (en) / 42 (fr) | 0 | 39 s / 45 s / 41 s |
| … → «Cuándo ir al médico» | 2 | 36 car. | toda la sección Hoy y Vigila | 1,2 a 1,5 pantallas | +25 s de lectura o desplazamiento |
| «2 meses con 38,2» → «Llama al 112» | 2 | 39 car. | 70 / 69 / 80 | 0 | 50 s / 51 s / 51 s, y después marcar a mano (≈ 6 toques más) |
| «anotar 37,8» (con cuenta) → anotado | 3 | 18 car. | 8 (la tarjeta) | 0 | 21 s |
| «¿a qué edad gatean?» → la respuesta | 2 | 19 car. | 15 | 0 | 22 s / 27 s / 30 s |

## Problemas priorizados por impacto

| # | Problema | Dónde | Impacto | Por qué |
|---|---|---|---|---|
| 1 | La urgencia no se puede ejecutar en un toque y la acción llega tras 70 a 80 palabras repetidas | Urgencia | Muy alto | Es el caso en que cada segundo cuenta |
| 2 | El agente con cuenta pinta Markdown crudo | Inicio con cuenta | Muy alto | La superficie principal de quien paga no muestra el plan ni sus apartados |
| 3 | Planes de 3,7 a 5,2 pantallas sin forma de saltar a «Cuándo ir al médico» ni de volver a preguntar | Plan, chat, agente | Alto | No se puede recortar el texto: la pantalla tiene que llevar a lo importante |
| 4 | Marcadores de cita crudos con el peso del texto | Todas las respuestas | Alto | 25 a 30 por plan; ensucian cada línea |
| 5 | «Tu plan» sobre respuestas que no son planes; fuentes de `evidence_only` plegadas | Sin evidencia, solo fuentes | Medio alto | Dice algo falso sobre la respuesta |
| 6 | «Cuándo ir al médico» y la vacuna pendiente en rojo de error | Plan, Hoy | Medio | Alarma sin motivo; resta fuerza a la urgencia real |
| 7 | «Hoy con Nora» en el nivel tipográfico más débil; saludo genérico; Subir duplicado | Inicio | Medio | Lo útil compite con lo accesorio |
| 8 | Chat: salta a las fuentes, doble cabecera, sin plan | Chat | Medio | Aterriza en lo que se lee CON CALMA |
| 9 | Burbuja vacía y tarjeta de Telegram junto a «¿Lo anoto así?» | Anotar | Medio bajo | Ruido en una decisión de un toque |
| 10 | Entradilla de 3 líneas con una frase rara; micrófono escondido | Portada | Medio bajo | La primera pantalla ya cumple; se puede aligerar |
| 11 | Historial como menú duplicado; «magic link» y «vault» | Historial, alta | Bajo | Pantallas de uso CON CALMA |

## Lo que ya funciona y no se toca

- El contrato clínico en pantalla: avisos, condiciones, «Cuándo ir al médico» y descargo nunca
  plegados; urgencias y rechazos sin plegar nada; solo las fuentes se pliegan.
- Primera pantalla de la portada con campo, botón y sugerencia en los tres idiomas.
- Zonas táctiles de 44 px en móvil, foco visible de dos tonos, modo oscuro propio con 72 pares
  AA verificados, `prefers-reduced-motion` global.
- Sin `setState` al montar en los providers del layout (`7adb21c`).

## Pruebas de referencia

Suite completa de Playwright antes de tocar nada: 335 pasan, 5 se saltan (sin clave de
Mistral) y 5 fallan con los trabajadores por defecto; esos 5 pasan en serie
(`--workers=1`): son inestabilidad por carga, no fallos de producto.
