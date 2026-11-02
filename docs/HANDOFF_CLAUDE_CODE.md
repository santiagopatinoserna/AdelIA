# Relevo a Claude Code (AdelIA)

Estado al 2 de noviembre de 2026, escrito por Hermes al pasar el trabajo a Claude Code.
Leer entero antes de tocar nada. El diseño del agente está en `docs/specs/AGENT_GRAPH.md`.

## 1. Cómo queremos AdelIA (visión de producto)

- La usuaria es una madre con el bebé llorando y sin tiempo para leer ni escribir. Primera
  pantalla y primera respuesta: qué hacer ahora. Lo largo va después, plegado. El 90 % del uso
  es móvil: verificar todo cambio visible en Chrome real a 390x844, claro y oscuro, es/en/fr.
- Tres fuentes, siempre separadas y etiquetadas: evidencia pediátrica (decide si se responde),
  lo que cuentan otras madres (tier `experience`, nunca dosis, síntomas, alarmas ni urgencias)
  y el historial del propio niño.
- Forma de la respuesta según intención (grafo): plan si hay preocupación (Hoy / Vigila /
  Cuándo ir al médico / No olvides / Lo que cuentan otras madres), respuesta corta si quiere
  un dato, una pregunta con botones si falta algo esencial, tarjeta de confirmación si anota.
- Contrato clínico innegociable: banderas rojas deterministas antes de cualquier modelo,
  también sobre lo anotado; sin dosis en urgencias; fuente o abstención; avisos y descargo
  nunca plegados; no truncar la salida del modelo. Acortar perdiendo una señal es retroceso.
- Voz de madre preocupada: frases cortas, nombre del bebé, sin «ficticio» ni «perfil», sin
  instrucciones de teclado, sin rayas largas ni jerga de folleto. Minimalismo: quitar antes
  de añadir.
- Datos reales solo en Mistral UE. OpenAI solo en la demo pública (`demo_llm_provider`).
- El corpus crece midiendo, no contando: una fuente entra si mejora el golden sin falsos
  positivos nuevos en el grupo B (`adelia/clinical/golden.py`).

Pendiente: Santiago aún no aprobó copiar este bloque a `CLAUDE.md`; pídeselo.

## 2. Producción hoy

`main` = `b641f42` = producción (build `20261102220819`, https://adelia.godi.ai). Incluye el
grafo completo (guard, route, clarify, plan, answer, record, track), experiencia de madres
(20 fuentes es), `experience_only`, dictado por voz en la demo, tarjeta «Hoy con <nombre>»,
tabla `observations`. QA en Chrome real tras el deploy: 5 de 6 casos bien.

Desplegar solo funciona desde la red de casa (servidor `santiago@192.168.1.150`). Santiago
tiene autorización vigente para desplegar; `scripts/deploy-prod.sh api web`.

## 3. Ramas listas o a medias (worktrees en `~/dev/adelia-night/wt-*`)

| Rama | Estado | Qué falta |
|---|---|---|
| `night/corpusdev` (`c7df480`) | 40 fuentes / 96 fragmentos de desarrollo 0-24 m. Medido: 9/10 preguntas hueco entran; 1 falso positivo nuevo en B: **B12** (niño de 7 años, sueño, tipo `age_band`). | Filtro de edad determinista (abajo) y luego integrar. |
| `night/corpus-digpiel` (`b3c6b8b`, WIP) | 40 fuentes / 85 fragmentos: cólicos, estreñimiento, heces, diarrea, APLV, dermatitis, costra láctea, pañal, ictericia, manchas, sol, picaduras. Sin verificar ni medir. | Pasar tests, medir, ajustar golden B (abajo). |
| `night/brevity2` (`00b91e6`) | Regla de brevedad solo en Hoy/Vigila/No olvides, opt-in. Medido: 406 → 251 y 237 palabras (-40 %); señales 23/24 y 24/24 (se perdió «pérdida de peso» en fr 3, tanda 1). | Reforzar que Vigila conserve todas las señales de la fuente, medir 2 tandas, activar solo con 24/24 en ambas. |
| `night/gaps` (`0e67723`) | Hecho: reloj fijo en `test_agent_turn` (fallaba después de medianoche). | `chat_sessions.profile_id` (migración 0024) para «No olvides» con varios hijos; tarjeta «Hoy» que siga el cambio de hijo sin setState al montar (ver `7adb21c` y la skill del bug de DOM duplicado); workers de Playwright que no cierran (pools pg). |
| `night/bilingual` (`660127f`) | Solo evaluación: traducir la consulta crea 2 falsos B al corte 0,19. | Nada; referencia. |
| `night/brevity` (`1f0eb62`) | Experimento antiguo descartado. | Borrar. |

## 4. Siguiente trabajo, en orden

1. **Filtro de edad** en el nodo `guard` de `adelia/agent/graph.py`, después de banderas rojas:
   si el mensaje nombra explícitamente un niño de 3 años o más («de 7 años», «7-year-old»,
   «10 ans») y no nombra una edad de 0-24 meses, responder con una frase de ámbito («AdelIA está
   pensada para bebés de 0 a 24 meses») más `no_evidence_reply(locale)` para que
   `golden.is_refusal` lo cuente como rechazo. Tests con B7, B12, B13 y con que ninguna pregunta
   del grupo A ni del dataset de enrutado se vea afectada. Después integrar `night/corpusdev`.
2. **Golden al crecer el corpus.** B5-B15 son near-misses elegidos porque el corpus no cubría
   su tema (cólicos, estreñimiento, flúor...). Al integrar digestivo y piel, la B que pase a
   estar respondida de verdad para 0-24 m se mueve a A con `expect_source`, y se añade otra B
   del mismo tipo que siga sin respuesta. Actualizar los recuentos en `tests/test_rag_golden.py`
   y regrabar `tests/fixtures/golden_query_embeddings.json` con
   `tests/record_golden_embeddings.py` dentro de `infra-api-1` (allí está la clave de Mistral).
3. **Más ámbitos**, un archivo `evidence_<ambito>.json` por rama, 30-40 fuentes oficiales
   (AEP EnFamilia y protocolos, AEPap Familia y Salud, SEUP, OMS, Sanidad, HealthyChildren,
   NHS/NICE, HAS/ameli/mpedia), resúmenes propios en español, sin dosis, con señales de alarma
   tal como las da la fuente. Pendientes: respiración y sueño (resfriado, bronquiolitis,
   laringitis, otitis, respiración normal y pausas, apnea, ronquido, muerte súbita, colecho),
   neonatal, accidentes y seguridad, ojos/oídos/boca, urología y neurología, salud mental
   materna. Modelo de archivo: `evidence_desarrollo_0_24m.json` de `night/corpusdev`.
4. **Experiencias por idioma**: `retrieve_experience` filtra por `language == locale`; añadir
   `experiences_fr.json` y `experiences_en.json` (12-20 fuentes públicas cada uno).
5. **Brevedad** (fila `night/brevity2`).
6. **Huecos** (fila `night/gaps`).

## 5. Problemas abiertos

- Producción: «Mon bébé de 4 mois régurgite après chaque tétée, ça m’inquiète» devuelve
  `no_evidence`, y la página titula «Ton plan» sobre una respuesta sin evidencia. Revisar la
  recuperación en francés y el título por `kind`.
- Banderas rojas: «ronca y a veces para de respirar» (18 meses) va al 112; probablemente
  debería ser consulta programada. Calibrar solo con fuentes (ámbito respiración y sueño).
- Clasificador: `mistral-small-latest` da 429 con la clave de producción; hoy deciden las
  reglas (96 % en es).
- DPIA sin OpenAI en la demo; rotar la clave de OpenAI que se pegó en un chat.

## 6. Herramientas (fuera del repo, `~/dev/adelia-night/`)

- `al-llegar-a-casa.sh`: deploy de `main` limpio y subido, QA en Chrome, mediciones.
- `home-prod-qa.cjs`: 6 preguntas reales en producción por camino del grafo, a 390 px.
- `eval_desarrollo_corpus.py` + `run_eval_desarrollo.sh`: medir un archivo candidato contra
  la recuperación de producción, solo lectura, limpia `/tmp`. Copiar y cambiar las preguntas
  para cada ámbito.
- `probe_plan_contract.py [--brevity]` + `compare_plan_probes.py --checklist`: generar 9
  respuestas reales con el contrato local y comprobar las 24 señales.
- Config Playwright con Chrome real: `~/.hermes-personal/cache/scratch/adelia-chrome.config.cjs`
  (lee `E2E_BASE_URL` y `ADELIA_WEB_DIR`).
- Python: `env -u PYTHONPATH -u VIRTUAL_ENV -u CONDA_PREFIX -u CONDA_DEFAULT_ENV -u PYTHONHOME`
  con `PYTHONPATH=$PWD` y `.venv/bin/python` desde `apps/api`; suite con `POSTGRES_PORT=5434`.
  Node en `/opt/homebrew/opt/node@22/bin`.
- Capturas y registros: `~/dev/adelia-design/shots/`.
