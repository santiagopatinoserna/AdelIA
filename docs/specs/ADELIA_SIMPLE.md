# AdelIA simple (decisión de Santiago, 2026-11-21)

«Lo simple siempre es lo que gana.» AdelIA empieza por hacer una cosa bien: guardar todo lo
del bebé desde que nace y contestar desde ahí.

## Qué hace

1. **Guardar.** Un solo campo: escribe o dicta («ha tomado 120 ml», «pesa 6,2»), adjunta un
   archivo (informe, cartilla, foto) o graba la consulta. Todo queda fechado y del niño.
2. **Historial.** Todo en una línea de tiempo, desde el nacimiento.
3. **Preguntar.** Cualquier pregunta se busca primero en lo suyo (lo anotado, sus documentos,
   sus grabaciones), con la tendencia: tomas por día, sueño, fiebres, pañales, curva de peso.

Lo demás (corpus de evidencia, plan, banderas rojas) sigue igual por debajo: las banderas rojas
van siempre antes que todo y «¿es normal?» sigue pasando por fuentes.

## Lugar seguro (2026-11-24)

Lo mínimo que promete: lo que entra no se pierde y se puede sacar.

| Garantía | Cómo | Prueba |
|---|---|---|
| Lo que sube lo recupera tal cual, aunque la lectura falle | `GET /documents/{id}/file`, fuera del muro de pago; enlace «Abrir el archivo original» | `test_document_original.py`, `e2e/document-original.spec.ts` |
| Una grabación no se pierde si la pestaña se recarga, se cierra o el móvil la mata | Cada segundo de audio también en el dispositivo (`lib/consulta-draft.ts`) hasta que la subida responde 2xx | `e2e/consulta-record.spec.ts` («interrupted recording») |
| Una transcripción fallida no se pierde en silencio | La página dice hasta cuándo se guarda el audio (`audio_until`) y, si ya se borró, lo dice | `test_document_original.py`, `e2e/document-original.spec.ts` |
| Subida a medias no deja nada huérfano; un reinicio no deja nada «procesando» | Compensación del blob y reconciliación al arrancar (ya existían) | `test_documents_upload.py`, `test_document_reconciliation.py` |

Límites, a propósito: el audio de la consulta no se descarga nunca; la DPIA lo guarda solo hasta
tener el texto (48 h; 7 días si falla). De la consulta queda la transcripción y el resumen.

Copias: el volcado diario de Postgres vive en el mismo servidor. Desde el 2026-11-24 hay además una
copia diaria fuera, cifrada con age antes de salir, en un repo privado de GitHub (base entera y
originales, nunca el audio de las consultas; 30 días): `scripts/adelia_backup.py`,
`docs/BACKUPS.md`. Probada de punta a punta contra GitHub con la base de pruebas (copia, descarga,
descifrado, restauración en una base temporal). Falta instalarla en el servidor: tarea de Santiago.

## Estado (2026-11-21)

| Pieza | Estado |
|---|---|
| Anotar desde el panel (`record`, tarjeta de confirmación) | Hecho, en producción |
| Subir archivos (OCR, extracción) y grabar consulta (Voxtral) | Hecho, cada uno en su página |
| Preguntar a lo anotado, con tendencia y gráfica (`agent/diary.py`) | Hecho en `claude/simple-core`, sin desplegar |
| Historial con lo anotado | A medias: `GET /observations/recent` sin commitear en `~/dev/AdelIA` (13-nov) |
| Datos del nacimiento | A medias: anotar con fecha pasada hecho en `claude/from-birth` («al nacer pesó 3,2 kg» queda el día que nació); faltan peso, talla y semanas al nacer en el onboarding, y talla y perímetro como tipos |
| Curvas OMS 0-24 meses | Hecho en `claude/from-birth`: las tablas de percentiles de la OMS, mes a mes, peso y longitud, niños y niñas (las de antes tenían 6 y 4 meses y algunos bordes eran ±2 DE) |
| Adjuntar y dictar desde el mismo campo | Falta: el campo solo tiene el micro del navegador |
| Menos superficie | Falta: genómica, ensayos, fármacos, códigos, cuestionario e importar siguen visibles |

## Orden

1. Historial: lo anotado, sus documentos y sus grabaciones en una sola lista, por niño.
2. Desde el nacimiento: peso, talla, perímetro y semanas al nacer en el onboarding; anotar con
   fecha pasada («al nacer pesó 3,2»); talla y perímetro como tipos; tablas OMS completas.
3. Un campo para todo: clip para archivos y micro con Voxtral en el campo del panel.
4. Quitar antes de añadir: el menú se queda en Guardar, Historial y Preguntar; lo demás, bajo
   «Más» o apagado.
5. Demo: Lucía con una semana de anotaciones, para que «¿cuánto ha comido?» se vea en la landing.
