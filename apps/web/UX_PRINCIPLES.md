# AdelIA: diseñar desde la preocupación de una madre

## Punto de partida

Diseñar primero para una persona con un bebé en brazos, poco tiempo y una mano libre. Santiago estima un 90 % de uso móvil. La pantalla principal sirve para preguntar y leer, no para vender ni exhibir cifras.

## Dos momentos de lectura

- **Ahora, con una mano libre.** Pregunta y envío en la primera pantalla. La respuesta empieza por lo que puede hacer o necesita saber, de forma breve y segura. Mantener la pregunta sencilla en negrita y los dos ejemplos contextuales visibles antes de responder. No exigir abrir el historial ni leer información del producto para empezar.
- **Después, cuando pueda leer.** Conservar el contexto del historial, los títulos completos de las fuentes y sus citas literales consultables junto a la respuesta. Poder ampliar los fragmentos sin perder la respuesta ni reiniciar la pregunta. Las fuentes y el contexto amplían la lectura; no sustituyen los avisos.
- **La seguridad no se aplaza.** Nunca plegar, recortar ni ocultar advertencias, condiciones clínicas, criterios de urgencia, límites de evidencia o la advertencia de que no sustituye al pediatra. No resumirlos en el navegador para hacer la pantalla más corta.

## Reglas de producto

1. **Partir de lo que observa.** Ejemplos: come menos, regurgita, una duda al leer un informe. No exigir diagnósticos, nombres de pruebas ni valores de laboratorio para empezar. Conservar las cifras en los documentos cuando sean necesarias para interpretar el caso.
2. **Una acción principal.** Una bienvenida corta, un campo y Preguntar. Dentro del campo vacío, un ejemplo concreto en gris que no repita ninguna sugerida. Sin instrucciones de teclado evidentes («Enter para enviar»): solo se muestra texto si algo impide enviar. El logo AdelIA siempre vuelve al inicio y lleva al lado una etiqueta Demo discreta. Una pregunta sencilla en negrita y dos ejemplos que relacionen el historial y las observaciones nuevas. El titular ya invita a preguntar: no repetir esa invitación en subtítulo ni encabezado de ejemplos. Precio y estadísticas no compiten con la pregunta.
3. **Cercanía sin engaño.** No abrir con «bebé ficticio». Mantener Demo junto a «Su historia hasta hoy», y explicar dentro que la historia se creó para probar AdelIA. Evitar etiquetas de software como «perfil de ejemplo». Nunca presentar un historial de ejemplo como el del visitante ni afirmar que se conoce a su bebé.
4. **Dos necesidades, capacidades comprobadas.** Describir lo que ocurre y comprender un informe. No dibujar un botón de adjuntar en la demo si esa ruta no admite archivos. No ampliar el tratamiento de documentos médicos reales sin revisar acceso, privacidad y seguridad.
5. **Calma visual.** Fondo neutro cálido, contraste suficiente, una sola columna de lectura y separación por espacio antes que por cajas. Sin estadísticas grandes, fases de carga inventadas ni animaciones que retrasen la tarea.
6. **Personalización demostrable.** Mostrar qué aporta el historial: edad, alimentación, revisiones e indicaciones del pediatra. Comprobar que las respuestas citan registros y evidencia, y que no inventan una evolución que los documentos no muestran. En la demo, ese contexto es el perfil de ejemplo, nunca el hijo del visitante. No confundir marcas de cita presentes con validación clínica completa.
7. **Lectura bajo control.** Al llegar la respuesta, retirar de la vista el campo y los ejemplos, y no repetir la pregunta ni la bienvenida. Conservar el texto escrito internamente. «Hacer otra pregunta» vuelve al campo y le da el foco mediante una acción explícita. Poner la apertura de la respuesta en letra mayor y mantener el cuerpo clínico completo visible. «Entenderlo mejor» abre únicamente las fuentes con título completo y fragmento literal expandible. No mover la pantalla automáticamente cuando termina una petición. Conservar avisos clínicos y decisiones de urgencia o abstención.
8. **Esperas honestas.** Indicar petición pendiente, no una fase del servidor que no se puede observar. Acotar la espera y ofrecer reintento de la pregunta original sin duplicar envíos.
9. **Los tres idiomas cuentan.** Modificar y comprobar es/en/fr, con trato coherente y tipografía propia del idioma.
10. **Explicar esta respuesta, no una promesa general.** Mostrar junto a sus fuentes si utiliza el historial y la evidencia citada. Distinguir las fuentes utilizadas del total de la biblioteca, con cifras consultadas a la API, nunca copiadas al texto. No insinuar búsqueda web en directo ni que cada respuesta utiliza todas las fuentes. No añadir esta explicación a una urgencia o abstención.
11. **Formato sin alterar el consejo.** Solicitar y renderizar Markdown sencillo: apertura directa, párrafos breves, listas cuando ayudan y énfasis moderado. Conservar afirmaciones, marcadores y avisos; no añadir estructura clínica ni resumir contenido en el navegador. Comprobar enlaces seguros, HTML inerte y lectura accesible con `answer-reading.spec.ts` y `test_answer_readability.py`.

12. **Llegar a lo importante sin recortar nada.** Un plan abre con su mapa (Hoy, Vigila, Cuándo ir al médico, No olvides): un toque lleva a cada apartado y todos siguen abiertos debajo. «Hacer otra pregunta» queda bajo el pulgar mientras se lee (fijo dentro de la respuesta, nunca sobre el pie). Los marcadores `[ev_N]` y `[N]` se quedan en el texto, literales, a 0,72 em y en el color `cite`.
13. **Destacar sin alarmar.** El rojo de error es solo para la urgencia. «Cuándo ir al médico» lleva un filete de arcilla sobre un tinte suave; «Hoy», un filete miel; una vacuna pendiente en «Hoy con» es un recordatorio en el color de aviso. La urgencia abre con un bloque: título, aviso y «Llamar al 112» en un toque; el número sale del marco fijo de la API, nunca de un modelo, y el texto de la respuesta sigue entero debajo.
14. **El título dice qué es la respuesta.** «Tu plan», «Tu respuesta», «Lo que cuentan otras madres», «Esto no puede esperar», «Sobre esto no tengo fuentes» (sin evidencia) y «Las fuentes que encontré» (solo fuentes, con las fuentes abiertas porque son la respuesta).
15. **Una sola forma de leer una respuesta.** La demo, el agente de `/dashboard` y el chat pintan el texto con `AnswerContent`: Markdown, apartados del plan, mapa, marcadores atenuados, a todo el ancho. Al enviar una pregunta en el chat, la pregunta sube arriba y la respuesta se lee desde su primera línea; el texto que llega no arrastra la vista hasta las fuentes.
16. **Con cuenta, su bebé primero.** El saludo usa el nombre del hijo activo («¿Cómo está Nora?») y nunca el del perfil propio («Mi perfil»). «Hoy con Nora» es el bloque principal, con un icono por línea. Mientras una tarjeta del turno espera respuesta (anotar, aclarar), en el móvil no se pinta ninguna sugerencia debajo; la entrada a anotar se lee en grande y «Sí» ocupa dos tercios de la fila.
17. **Una mano.** Acción principal de una pantalla a 52 px (`ad-btn-lg`); el micrófono, dentro del campo y abajo a la derecha; el campo de la portada sigue por encima de 380 px para que el teclado no lo tape.

Sistema visual, prototipos y razones: `docs/design/REDISENO.md`. Auditoría y cifras de partida: `docs/design/AUDITORIA_UX.md`.

## Puerta de aceptación de cada cambio

- Typecheck y build correctos.
- Playwright: `mobile-method.spec.ts`, `landing-mobile`, `pricing`, `demo`, `reading-design`, `ux-v2` y `demo-profile-cache`. Backend: `test_demo_parent_language.py`, `test_demo.py` y `test_demo_retrieval_query.py`.
- Chrome real a 375, 390 y 430 px, más escritorio. Claro y oscuro. Sin desplazamiento lateral. Campo y envío en primera pantalla. Controles de al menos 44 px, texto de entrada de al menos 16 px y foco visible.
- Suite en Chrome real: `pnpm exec playwright test -c scripts/redesign/e2e-chrome.config.ts`. Capturas antes y después de cada pantalla, es/en/fr, 390x844 claro y oscuro y 1280: `SHOTS_PHASE=after pnpm exec playwright test -c scripts/redesign/shots.config.ts`. Contraste de cada par de tokens en los dos esquemas: `node scripts/check-contrast.mjs`.
- Recorrer teclado, espera, error, reintento, respuesta, fuente expandida, otros ejemplos y precios. Inspeccionar las capturas, no solo el código.
- Etiquetar pruebas locales simuladas como tales. Tras un despliegue autorizado, repetir con respuestas reales y las sugeridas exactas de los tres idiomas.
- Separar corrección visual, rendimiento y seguridad clínica. Un test de interfaz verde no prueba que una respuesta médica sea correcta. Medir rapidez con muestras comparables y no prometer tiempos de producción desde un fixture local.

Las pruebas automatizadas protegen estas reglas observables; no garantizan por sí solas confianza, usabilidad para todas las familias ni exactitud clínica. La validación con madres y la revisión clínica siguen siendo trabajos distintos.
