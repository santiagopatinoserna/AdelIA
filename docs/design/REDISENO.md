# Rediseño de AdelIA para una madre con poco tiempo

Parte de `docs/design/AUDITORIA_UX.md` (3 de noviembre de 2026). Prototipos en
`docs/design/prototipos/`; capturas en `~/dev/adelia-design/shots/redesign/prototipos/`.

## Principios

1. **Primero la acción.** Cada pantalla empieza por lo que ella puede hacer ya. Lo que se lee
   con calma va después y, si son fuentes, plegado.
2. **Una idea por pantalla.** Cuando hay algo que decidir (anotar, contestar una pregunta), no
   se pinta nada que compita al lado.
3. **El pulgar manda.** Lo que se repite (otra pregunta, llamar, confirmar) queda abajo o a mano
   mientras se lee; nada de menos de 44 px; acciones principales de 52 px en móvil.
4. **Destacar sin alarmar.** El rojo de error se reserva para la urgencia de verdad. «Cuándo ir
   al médico» lleva un acento de arcilla suave; un recordatorio (vacuna pendiente) va en miel.
5. **El texto clínico no se toca.** Ni se recorta, ni se resume, ni se reordena. El diseño
   ayuda a recorrerlo: mapa del plan, citas atenuadas, títulos por tipo de respuesta.
6. **Quitar antes de añadir.** Cada elemento nuevo se paga quitando otro: el mapa del plan
   sustituye 1,6 pantallas de desplazamiento; el botón de llamada, el marcado a mano.
7. **Habla como una persona.** Frases cortas, el nombre del bebé, sin instrucciones de teclado,
   sin «ficticio», «perfil», «vault» ni «magic link».

## Dos direcciones

### A. Calma cálida (elegida)
Evolución de la marca actual: crema, pino, miel y arcilla; Fraunces solo para titulares y
Hanken Grotesk para todo lo demás; una columna; espacio antes que cajas.
`prototipos/direccion-a-calma.html`.

### B. Una mano, de noche (descartada)
Una sola familia tipográfica, oscuro por defecto, el campo anclado abajo como una hoja y una
tarjeta por apartado del plan. `prototipos/direccion-b-una-mano.html`.

### Por qué A
- **Teclado.** B ancla el campo abajo. La regla medida y fijada por las pruebas es la contraria:
  el campo termina antes de 380 px para que siga a la vista cuando el teclado ocupa media
  pantalla (`mother-first-page`, `reading-design`). En iOS una hoja fija con teclado salta.
- **Longitud.** Con una tarjeta por apartado y 18 px, el plan de 498 palabras pasa de 3,8 a unas
  4,8 pantallas. A gana espacio atenuando las citas y quitando cajas.
- **Calma.** B pinta la urgencia en color pleno y alarma más; A la destaca con arcilla y un botón.
- **Oscuro por defecto** ignora el uso de día; A sigue el esquema del sistema, ya verificado.
- **Coste.** B obliga a reescribir textos de la API y a quitar la vitrina de la portada con
  cuenta que fijan las pruebas; A cabe dentro del contrato y de la suite.

## Sistema visual (dirección A)

### Tipografía y escala
Dos familias, ya cargadas y optimizadas (Fraunces 37 KB variable de peso, Hanken variable).
Escala móvil, en `globals.css` como tokens `--text-*` de Tailwind:

| Token | Tamaño / interlínea | Familia y peso | Uso |
|---|---|---|---|
| `display` | 30 a 40 px fluido / 1,12 | Fraunces 520 | Titular de portada |
| `title` | 23 px / 1,25 | Fraunces 540 | Título de respuesta y de pantalla |
| `lead` | 19 px / 1,5 | Hanken 500 | Frase de apertura de la respuesta |
| `answer` | 17 px / 1,6 | Hanken 400 | Cuerpo de las respuestas (interlínea 27 px) |
| `ui` | 16 px / 1,4 | Hanken 560 | Botones, campos (16 px evita el zoom de iOS) |
| `small` | 14 px / 1,5 | Hanken 400 | Descargo, metadatos |
| `micro` | 12,5 px | Hanken 600 | Etiquetas; nunca por debajo de 12 px |

Las citas `[ev_N]` y `[N]` se quedan en el texto, literales, pero a 0,72 em y en `ink-faint`:
siguen siendo verificables y dejan de pesar como el texto.

### Color y contraste
Se conservan las dos capas (rampa de marca y roles) y los 72 pares ya verificados. Roles nuevos:

| Rol | Claro | Oscuro | Contraste medido |
|---|---|---|---|
| `doctor-tint` (fondo de «Cuándo ir al médico») | `#fbf1ed` | `#2a1a14` | `error-text` encima: 8,93 / 8,28 |
| `doctor-line` (filete) | `#b25a41` | `#b25a41` | sobre lienzo: 4,20 / 3,86 (≥ 3) |
| `today-line` (filete de «Hoy») | `#a36e1f` | `#a98334` | sobre lienzo: 3,87 / 5,21 |
| `cite` (marcadores) | `#646b64` | `#9dafa4` | sobre lienzo: 4,86 / 7,92 |
| Urgencia (botón de llamada) | `error` + `on-error` | igual | 6,88 / 4,90 |
| Recordatorio de «Hoy con» | `warning-text` | igual | sobre superficie: 6,71 / 9,38 |

`scripts/check-contrast.mjs` añade estos pares; `check-dark-tokens.mjs` vigila que los dos
bloques oscuros declaren lo mismo.

### Espaciado, radios y sombras
- Escala de 4 px (la de Tailwind): 4, 8, 12, 16, 24, 32, 48. Margen lateral de 20 px en móvil.
- Radios: 8 (citas, etiquetas), 14 (botones y campos), 20 (tarjetas), píldora para el mapa del
  plan. Sin radios nuevos.
- Sombras: `soft` en reposo y `lift` solo en lo que flota (el botón fijo de otra pregunta). En
  oscuro no hay sombra: la elevación sube de luminancia.

### Iconos
`lucide-react`, ya en el proyecto. 20 px en controles, trazo 2, siempre con texto al lado y
`aria-hidden`. Iconos nuevos: teléfono (llamar), termómetro, jeringa y marcador en «Hoy con».

### Movimiento
120 a 200 ms con `--ease-out-soft`, solo opacidad y desplazamiento. La entrada `ad-rise` baja de
0,7 a 0,32 s y 6 px. Nada se mueve al terminar una petición. `prefers-reduced-motion` lo apaga
todo (regla global ya existente).

## Jerarquía por pantalla

| Pantalla | Orden |
|---|---|
| Portada | Logo y Demo · titular · una frase · campo con micrófono abajo a la derecha · Preguntar (52 px) · 3 sugerencias · Lucía (plegada) · «nada se guarda» · Sobre AdelIA y precios (plegado) · pie |
| Espera | El campo y el botón con «Pensando…» · una línea de estado · las sugerencias se ocultan |
| Plan | Título «Tu plan» · apertura grande · mapa del plan (Hoy, Vigila, Cuándo ir al médico, No olvides, Otras madres) · apartados completos · descargo · fuentes plegadas · «Hacer otra pregunta» fijo abajo mientras se lee |
| Respuesta corta | «Tu respuesta» · frase grande · viñetas · descargo · fuentes plegadas · otra pregunta |
| Pregunta con botones | La pregunta · botones de 52 px a lo ancho · «No la he medido» como botón discreto |
| Solo madres | Título propio · frase fija · sección etiquetada · descargo · fuentes plegadas |
| Sin evidencia | «Sobre esto no tengo fuentes» · el rechazo · descargo · otra pregunta |
| Solo fuentes | «Las fuentes que encontré» · aviso · fuentes abiertas (son la respuesta) |
| Urgencia | Bloque de arcilla con el título, el aviso y «Llamar al 112» (si el texto fijo nombra un número) · el texto entero · descargo · fuentes abiertas |
| Inicio con cuenta | «¿Cómo está Nora?» · marca de edad · «Hoy con Nora» con iconos · primeros pasos · campo con ejemplo, micrófono y enviar · descargo · barra inferior. Sin botón Subir en la cabecera del móvil |
| Respuesta del agente y del chat | El mismo renderizado que la demo: apartados, citas atenuadas, fuentes plegadas, a todo el ancho |
| Anotar | Su frase · «¿Lo anoto así?» · la entrada en grande · Sí ancho y No · nada más hasta que conteste |
| Chat | Una cabecera · la respuesta como plan · al terminar no salta a las fuentes |
| Alta | «Entra con tu email» · campo · «Enviarme el enlace» |
| Historial | Aviso del día (si toca) · «Mis documentos» y el número · una fila de herramientas (Chat, Control reflujo, Resúmenes, Insights, Importar) · la lista. Subir y Consulta no se repiten: están en la barra |
| Subir | Título · una frase · «Elige un archivo» (52 px) · formatos. En el móvil sin zona de arrastre; desde sm, la zona y «o arrástralo aquí» |
| Consulta | Título · una frase · «¿Qué acaba de decir el médico?» · campo con el ejemplo y el micrófono dentro · «Generar preguntas» a lo ancho · respuesta como en el chat · «Grabar la consulta» como fila final |
| Grabar | El guion para el profesional · la fila entera del consentimiento como objetivo · nota legal · «Grabar» (52 px) |
| Ajustes | Título y email · una sección por ajuste bajo un filete, con su título · zona de peligro en su caja |

## Lo que no cambia
Contenido clínico, prompts, textos de la API, orden de los apartados, el descargo, la regla de
plegar solo fuentes y las decisiones de producto que fijan las pruebas existentes.
