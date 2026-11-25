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

## Estado (2026-11-21)

| Pieza | Estado |
|---|---|
| Anotar desde el panel (`record`, tarjeta de confirmación) | Hecho, en producción |
| Subir archivos (OCR, extracción) y grabar consulta (Voxtral) | Hecho, cada uno en su página |
| Preguntar a lo anotado, con tendencia y gráfica (`agent/diary.py`) | Hecho en `claude/simple-core`, sin desplegar |
| Historial con lo anotado | A medias: `GET /observations/recent` sin commitear en `~/dev/AdelIA` (13-nov) |
| Datos del nacimiento | Falta: el perfil guarda fecha y sexo; `record` no admite fechas de más de 7 días |
| Curvas OMS 0-24 meses | Falta: la tabla tiene niños 0, 1, 2, 6, 12, 24 meses y niñas 0, 2, 12, 24 |
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
