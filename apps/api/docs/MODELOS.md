# Modelos: qué llama AdelIA, dónde se configura y cómo se cambia

**Fecha:** 14 de octubre de 2026
**Estado:** al escribir este documento no se cambió ningún modelo por defecto. Los nombres
pasaron de estar dentro de la lógica a `adelia/config.py`, y se añadieron dos ajustes
(`chat_reasoning_effort`, `briefing_reasoning_effort`) que por defecto no hacen nada.
**Nada de lo que la sección 6 llama "candidato" se ha medido.** No hay claves de API en el
entorno donde se escribió esto, así que ninguna afirmación sobre calidad, coste o latencia de
un modelo nuevo está comprobada aquí.
**Valores fijados por test:** `apps/api/tests/test_model_config.py` (`EXPECTED_DEFAULTS`).

## 1. La regla

Un modelo no se cambia porque exista uno más nuevo. Se cambia cuando la misma comprobación,
pasada antes y después, no empeora, y cuando el cambio legal que arrastre (si lo hay) está hecho
en el mismo cambio. Este producto responde a padres sobre un bebé. Un modelo que cita peor, que
contesta sin evidencia o que transcribe mal un fármaco no es una regresión de calidad: es un
fallo de seguridad.

## 2. Qué modelos llama el producto

Todos los nombres están en `adelia/config.py` y se pueden sobrescribir con la variable de
entorno indicada (el nombre del setting en mayúsculas). Ningún nombre de modelo debe aparecer
escrito en la lógica: `test_no_model_name_is_a_literal_in_logic` lo comprueba, y solo admite
`config.py` y la lista de ids compatibles con reasoning effort de `adelia/llm.py`. Los endpoints
(`https://api.mistral.ai/...`) siguen siendo constantes de cada worker; cambiar de proveedor no
es un cambio de nombre de modelo (sección 4.6).

| Uso | Por defecto | Setting / variable | Lo lee | De qué depende |
|---|---|---|---|---|
| OCR de PDF e imágenes | `mistral-ocr-latest` | `mistral_ocr_model` / `MISTRAL_OCR_MODEL` | `workers/ocr.py` | Residencia UE (4.3). Su texto alimenta extracción, chunking y embeddings. Es un alias que se mueve (4.7). |
| Embeddings | `mistral-embed` | `mistral_embed_model` / `MISTRAL_EMBED_MODEL` | `workers/embed.py` | Columnas `Vector(1024)`, índices HNSW, vectores guardados, `evidence_max_distance`. **No es un cambio de configuración, es una migración (4.1).** |
| Chat RAG y `/demo` | `mistral-medium-latest` | `mistral_chat_model` / `MISTRAL_CHAT_MODEL`, con `LLM_PROVIDER=mistral` | `services/chat_orchestrator.py` | Contrato de respuesta con citas `[ev_N]` y rechazo por código (4.2). Lee `chat_reasoning_effort` (4.5). |
| Chat RAG alternativo | `gpt-5.1` | `openai_chat_model` / `OPENAI_CHAT_MODEL`, con `LLM_PROVIDER=openai` | `services/chat_orchestrator.py` | Mueve el chat a un proveedor que `/privacidad` no nombra (4.6). |
| Agente de `/dashboard`, Anthropic | `claude-sonnet-5` | `agent_model` / `AGENT_MODEL` | `agent/provider.py` (`AnthropicProvider`) | Se usa si hay `ANTHROPIC_API_KEY`. Envía `thinking={"type": "disabled"}`. Proveedor no nombrado en `/privacidad` (4.6). |
| Agente de `/dashboard`, respaldo Mistral | el del chat | `mistral_chat_model` | `agent/provider.py` (`MistralProvider`) | Llamadas a herramientas. Lee `chat_reasoning_effort` (4.5). |
| Extracción de entidades | `mistral-medium-latest` | `mistral_extraction_model` / `MISTRAL_EXTRACTION_MODEL` | `workers/extract.py` | Temperatura 0, `json_object`, filtro de `raw_quote` literal. No lee ningún ajuste de reasoning effort. |
| Preguntas del briefing | `mistral-medium-latest` | `mistral_briefing_model` / `MISTRAL_BRIEFING_MODEL` | `services/qa_pre_baker.py` | `json_schema` estricto, filtro de citas, mínimo de ítems. Lee `briefing_reasoning_effort` (4.5). |
| Resumen de consulta | el del chat | `mistral_chat_model` | `workers/summarize.py` | HTTP directo. No lee ningún ajuste de reasoning effort. |
| Transcripción (activa) | `voxtral-mini-latest` | `mistral_stt_model` / `MISTRAL_STT_MODEL`, con `STT_PROVIDER=mistral` | `workers/transcribe.py` | Diarización `[Hablante N]`, DPIA, textos legales publicados. **Cambio técnico y legal (sección 5).** |
| Transcripción (cableada, inactiva) | `whisper-1` | `openai_stt_model`, `openai_stt_base_url`, con `STT_PROVIDER=openai` | `workers/transcribe.py` | Sin diarización. El endpoint UE exige un proyecto OpenAI con residencia europea. Disparador (a) de la DPIA (sección 5). |

Extracción y briefing son ajustes propios aunque hoy valgan lo mismo que el del chat: fijar
`MISTRAL_CHAT_MODEL` para el chat no debe mover en silencio la extracción clínica ni el briefing.

## 3. Cómo se aprueba un cambio

1. **Clasificar el cambio.** Un nombre dentro del mismo proveedor (por ejemplo fijar un alias a un
   id): pasos 2 a 7. Cambia de proveedor: además la sección 4.6. Transcripción: además la
   sección 5, **antes** de fusionar. Embeddings: no se hace con este procedimiento, es una
   migración (4.1).
2. **Averiguar a qué apunta hoy el nombre actual.** Un alias `-latest` puede haberse movido sin
   ningún cambio en este repositorio (4.7). Con una clave de Mistral, `GET
   https://api.mistral.ai/v1/models` devuelve para cada modelo `aliases`, `deprecation`,
   `deprecation_replacement_model` y `capabilities`. Anotar en la PR el id real que sirve hoy el
   valor por defecto. Sin ese dato el "antes" no se puede reproducir.
3. **Medir antes**, con el valor por defecto vigente, y guardar los números (3.1).
4. **Cambiar el valor por defecto** en `config.py` y, en el mismo commit, el valor esperado en
   `EXPECTED_DEFAULTS` de `tests/test_model_config.py`. Ese diff es lo que deja el cambio visible.
5. **Medir después**, igual.
6. **Comparar y decidir.** Mínimo para el chat y el briefing, los umbrales de
   `adelia/clinical/golden.py` (auditoría 3.2): recall@4 en el grupo A de 0,8 o más, tasa de
   rechazo del grupo B igual a 1,0, cero citas huérfanas, grupo C (banderas rojas) en 1,0. Que
   no baje ninguna métrica respecto del "antes". Para OCR, extracción, briefing y transcripción
   hay que añadir las comprobaciones específicas de 3.1, porque el golden set no las cubre.
7. **Legal y publicado**, si aplica (sección 5 y 4.6), en el mismo cambio, no después.
8. **Marcha atrás.** Con los nombres en settings, volver al valor anterior es cambiar una
   variable de entorno. La excepción son los embeddings: una vez recalculados los vectores, volver
   atrás exige otra migración y otro recálculo.
9. Añadir una fila al registro (sección 7).

### 3.1 Qué hay hoy para medir, y qué no

El procedimiento original citaba `apps/api/tests/eval/`. Ese directorio no existe en este árbol
a fecha 14 de octubre de 2026. Esto es lo que sí hay:

| Superficie | Qué hay | Cómo se corre | Límite |
|---|---|---|---|
| Chat y recuperación | Golden set de 15 preguntas: `adelia/clinical/golden.py`, `tests/test_rag_golden.py`. Mide recall@4, rechazo, citas huérfanas y banderas rojas, y escribe `apps/api/golden_report.json`. | `uv --directory apps/api run pytest -q tests/test_rag_golden.py`, con `MISTRAL_API_KEY` y el corpus de evidencia cargado, o con `tests/fixtures/golden_query_embeddings.json`. | Los grupos A y B se saltan sin clave y sin ese fixture, y **el fixture no está grabado** (se graba con `uv run python -m tests.record_golden_embeddings`). El `golden_report.json` actual tiene `recall_at_4: null` y `skipped_reason`. Un salto es "desconocido", no un aprobado: **un cambio de modelo no se aprueba con una corrida saltada.** |
| Umbral de evidencia | `scripts/calibrate_answer_threshold.py`, método en `apps/api/docs/CALIBRACION_UMBRAL_EVIDENCIA.md`. | Ver ese documento. | Obligatorio tras cualquier cambio de embeddings (4.1). |
| Transcripción | `docs/stt-provider-benchmark.md` con `tests/fixtures/consulta-dos-voces.wav`; el comando está al final de ese documento. | Con `MISTRAL_API_KEY`. | 13 segundos de voz sintética, un idioma. El propio documento dice que es indicativo. Lo que mira: nombre del fármaco, posología, hablantes separados. |
| OCR | `tests/test_ocr.py` (en vivo). | Salta sin clave. | Comprueba que salen "Glucose" y "95" de un PDF. No es un arnés de exactitud. |
| Extracción | `tests/test_extract.py`, `tests/test_clinical_extraction.py` (en vivo). | Saltan sin clave. | Comprobaciones puntuales, no una métrica de recall. |
| Briefing | `tests/test_qa_pre_baker.py` (en vivo). | Salta sin clave. | Una comprobación, no una métrica. |
| Agente | Tests con dobles (`tests/test_agent_*.py`). | Siempre. | No hay evaluación en vivo del agente ni de sus herramientas. |

Conclusión honesta: hoy no existe un arnés que mida con números la generación del chat, el
briefing, el OCR ni la extracción. Para esas superficies, quien apruebe tiene que añadir la
medida o aceptar una comparación manual a sabiendas. Este documento no baja ese listón. Cuando
exista `tests/eval/` u otro arnés, actualizar esta tabla.

## 4. De qué depende cada modelo

### 4.1 Embeddings y las columnas de 1024 dimensiones

Dependen de `mistral-embed`:

- `chunks.embedding` y `evidence_chunks.embedding` son `Vector(1024)` (migraciones `0001` y
  `0005`, `adelia/models.py`), con índices HNSW de coseno (`chunks_embedding_hnsw_idx` y el de
  `evidence_chunks`).
- Todos los vectores ya guardados: los del corpus de evidencia y los de cada familia.
- `evidence_max_distance = 0.19` y `patient_max_distance = 0.45`. Son distancias de coseno
  medidas con este modelo (`CALIBRACION_UMBRAL_EVIDENCIA.md`); otro modelo tiene otra geometría y
  esos números dejan de significar nada.
- Los vectores de consulta de `tests/fixtures/golden_query_embeddings.json`, cuando se graben.

La dimensión está declarada en **un solo sitio**: `EMBEDDING_MODEL_DIMENSIONS` en
`adelia/config.py`. Tres cosas la protegen:

1. `Settings` se niega a arrancar si `MISTRAL_EMBED_MODEL` no es una clave de esa tabla. Una
   variable de entorno cambiada por error falla al arrancar, no empieza a escribir vectores de
   otro espacio.
2. `test_configured_embedding_model_matches_the_vector_columns` compara la dimensión declarada con
   la de las dos columnas reales. No se puede registrar un modelo de otra dimensión sin la
   migración que lo hace almacenable.
3. pgvector rechaza insertar un vector de dimensión distinta de la columna.

**Misma dimensión no significa compatible.** Otro modelo que también devuelva 1024 números es otro
espacio vectorial. Mezclarlo con los vectores existentes no da ningún error y degrada la
recuperación en silencio. Por eso registrar el modelo en la tabla no basta.

Cambiar el modelo de embeddings es esto, en orden:

1. Registrar el modelo y su dimensión en `EMBEDDING_MODEL_DIMENSIONS`.
2. Una migración nueva de Alembic. Una columna con datos no cambia de dimensión con un `ALTER`:
   en la práctica se recrea la columna y los índices HNSW, y se vuelve a calcular cada vector.
3. `Vector(N)` en `adelia/models.py` (ambas tablas).
4. Recalcular los embeddings de todos los `chunks` y de todos los `evidence_chunks`. Durante el
   recálculo la recuperación mezcla dos espacios: hacerlo en una ventana, o con una columna
   paralela que se intercambia al terminar.
5. Volver a correr `scripts/calibrate_answer_threshold.py`, actualizar `evidence_max_distance`
   (y su comentario en `config.py`) y `CALIBRACION_UMBRAL_EVIDENCIA.md`.
6. Volver a grabar `golden_query_embeddings.json` y pasar el golden set antes y después.

### 4.2 Banderas rojas, contrato de respuesta y rechazo

`clinical/red_flags.py` decide en código y nunca llama al modelo generativo. Ningún cambio de
modelo ni de reasoning effort puede alterarlo, y el grupo C del golden set (5 de 5) tiene que
seguir en 1,0. `services/answer_contract.py` exige citas `[ev_N]` y `no_evidence_reply()` contesta
por código cuando no hay evidencia. Un modelo que cite peor rompe la promesa del producto ("si no
hay evidencia, lo digo"): por eso `orphan_citations` y la tasa de rechazo del grupo B son criterio
de aprobación, no un detalle.

### 4.3 OCR y residencia UE

`/privacidad` (clave `privacy.whereBody` en `apps/web/messages/{es,en,fr}.json`) dice que Mistral
AI (Francia) procesa documentos, texto y audio (OCR, embeddings, chat y transcripción), "siempre
dentro de la UE". El OCR va a `https://api.mistral.ai/v1/ocr` (`MISTRAL_OCR_URL` en
`workers/ocr.py`). La ficha del modelo Mistral Medium 3.5 en docs.mistral.ai no declara
residencia de datos por modelo. Antes de pasar OCR o cualquier otro modelo Mistral a un id nuevo,
confirmar por escrito (DPA y condiciones de Mistral) que esa afirmación cubre ese id. El
catálogo de Mistral incluye también modelos de terceros (por ejemplo Z.ai GLM 5.3): no dar por
supuesto que su alojamiento esté cubierto.

Un cambio de OCR además cambia el texto de entrada de la extracción y de los embeddings, así que
no se puede evaluar solo.

### 4.4 Diarización

Los bloques `[Hablante N]` salen de `diarize=true` en la API de transcripción por lotes de
Voxtral (`_format_diarized` en `workers/transcribe.py`). `whisper-1` no diariza. Según la
documentación de Mistral, el modelo en tiempo real tampoco admite `diarize`. Lo que consume ese
formato: el resumen de consulta, la extracción de entidades y la distinción entre lo que dijo el
profesional y lo que preguntó la familia.

### 4.5 Reasoning effort (la costura)

Dos ajustes, ambos `none` | `high` | sin definir:

| Ajuste | Lo leen |
|---|---|
| `chat_reasoning_effort` / `CHAT_REASONING_EFFORT` | El stream del chat RAG (`_stream_mistral_tokens`, que también sirve a `/demo`) y el `MistralProvider` del agente. |
| `briefing_reasoning_effort` / `BRIEFING_REASONING_EFFORT` | `qa_pre_baker._llm_structured_call`. |

No los leen la extracción ni el resumen de consulta, ni el agente cuando usa Anthropic.

**Sin definir (el valor por defecto) la petición no lleva el campo.** Se llama al SDK con
exactamente los argumentos de antes; los tests `test_*_request_is_unchanged_when_effort_is_unset`
lo fijan para el chat, el agente y el briefing.

**Cuándo se envía.** Solo si está definido y el modelo está en `adelia.llm.REASONING_EFFORT_MODELS`:
hoy `mistral-medium-3-5`, `mistral-small-latest` y `mistral-large-4-0`, los ids que la página
"Reasoning" de docs.mistral.ai documenta como compatibles (leída el 14 de octubre de 2026). En
cualquier otro modelo se ignora y se registra un aviso, para que una errata de configuración no
convierta cada turno de chat en un error. **El valor por defecto `mistral-medium-latest` no está
en la lista**, porque Mistral no dice a qué apunta ese alias. Usar la costura exige fijar de forma
deliberada `MISTRAL_CHAT_MODEL=mistral-medium-3-5` (o `MISTRAL_BRIEFING_MODEL`), y eso es un
cambio de modelo con su propio procedimiento (sección 3). Añadir un id a la lista es un cambio de
código con su evaluación.

**La forma de la respuesta cambia.** Con `high`, `message.content` llega como una lista de trozos
(pensamiento y texto) y en streaming `delta.content` cambia de forma a mitad de respuesta. Sin
protección, esa lista iría al flujo de tokens, o la traza de razonamiento llegaría a un padre. Todas
las lecturas pasan por `adelia.llm.content_text`, que se queda solo con los trozos de tipo `text`;
con una cadena (el caso de hoy) devuelve la misma cadena. Lo cubren `test_chat_never_streams_the_thinking_trace`,
`test_agent_never_surfaces_the_thinking_trace` y `test_briefing_parses_the_json_out_of_the_text_chunk`.

**Qué documenta Mistral y qué no** (página "Reasoning", 14 de octubre de 2026):

- `high`: la respuesta incluye una cadena de pensamiento completa antes de la respuesta final, con
  más consumo de tokens. `none`: piensa lo mínimo y no devuelve la traza.
- No indica el comportamiento cuando se omite el parámetro. Por eso "sin definir" y `none` no son
  lo mismo y el valor por defecto es sin definir.
- No indica cómo se combina con llamadas a herramientas, ni con `response_format` de tipo
  `json_schema` estricto. Hacen falta dos pruebas antes de activarlo: el agente con sus
  herramientas (para `chat_reasoning_effort`) y el briefing con su esquema (para
  `briefing_reasoning_effort`).
- No hay medida de latencia ni de coste. **La hipótesis de uso (`none` en un turno de chat casual,
  `high` al generar el briefing de un médico) no está medida.**

### 4.6 Cambiar de proveedor

El texto de `/privacidad` (`privacy.whereBody`) nombra cuatro encargados: Mistral AI, Stripe,
Resend y Telegram, y dice: "Ningún dato va más allá de estos cuatro". Con `LLM_PROVIDER=openai`
el contexto del chat, y con `ANTHROPIC_API_KEY` el del agente, salen hacia un proveedor que ese
texto no nombra. Qué proveedor sirve de verdad el chat y el agente en una instalación se decide
solo por variables de entorno, así que este repositorio no lo dice: quien apruebe un cambio debe
comprobarlo en esa instalación, y si es OpenAI o Anthropic, el texto publicado, el contrato del
art. 28 RGPD y la DPIA tienen que reflejarlo. El mismo texto promete avisar a las familias si
cambia el proveedor de transcripción.

### 4.7 Los alias `-latest` se mueven

Un nombre como `mistral-ocr-latest` no es un modelo, es un puntero que mantiene el proveedor.

- Según el changelog de Mistral, `mistral-ocr-latest` apuntaba a OCR 4 el 23 de junio de 2026 y
  apunta a OCR 4.1 (`mistral-ocr-4-1`) desde el 16 de julio de 2026. El modelo de OCR por defecto
  cambió sin ningún diff en este repositorio.
- La ficha de Mistral Medium 3.5 no dice si `mistral-medium-latest` apunta a él. Una incidencia
  de pydantic-ai (nº 5285) afirma que sí en la API pública; no es documentación de Mistral y no
  está comprobado aquí.
- La página de transcripción por lotes de Mistral indica que `voxtral-mini-latest` llama a Voxtral
  Mini Transcribe 2 (`voxtral-mini-2602`). La DPIA nombra literalmente `voxtral-mini-latest`.

La primera acción útil, que no cambia ningún comportamiento, es el paso 2 de la sección 3 para cada
nombre de la tabla de la sección 2 (empezando por `mistral-medium-latest`, `mistral-ocr-latest` y
`voxtral-mini-latest`), y anotar el resultado en el registro. Para cualquier modelo que
toque salud, preferir un id fijado a un alias: así el número del informe de evaluación corresponde
al modelo que se ejecutó.

## 5. Transcripción: un cambio técnico y legal a la vez

`STT_PROVIDER`, el proveedor y el modelo de transcripción están nombrados en la DPIA de "Grabar
consulta" (`docs/legal/dpia-grabacion-consulta.md`). **Por eso cambiar el modelo de transcripción
es un cambio legal y no solo técnico: la información de privacidad se actualiza en el mismo
cambio.** La DPIA no es un documento aparte del código: describe este tratamiento con nombres
concretos. Lo que dice, y lo que implica para un cambio:

- La fila "Encargado del tratamiento (STT)" y el §1.2 paso 7 nombran el proveedor (Mistral AI,
  Francia/UE, La Plateforme, `audio/transcriptions`), el modelo (`voxtral-mini-latest`) y la
  diarización. Nombran también la variable `STT_PROVIDER` (`mistral` | `openai`, por defecto
  `mistral`) y dejan OpenAI (`whisper-1`, endpoint UE, sin diarización) cableado e inactivo.
- El ámbito de la DPIA dice: "No cubre streaming cero-retención, STT on-device, ni certificación
  HDS".
- La aprobación del 19 de agosto de 2026 cubre "el tratamiento tal y como está desplegado": Mistral
  Voxtral con diarización y residencia UE.
- El §6 lista cuatro disparadores de revisión. Dos tocan la transcripción: (a) activar el
  fallback OpenAI Whisper por defecto, y (b) escalar a streaming cero-retención u otro cambio de
  arquitectura de STT.

Por eso cambiar `STT_PROVIDER` o `mistral_stt_model` no es solo una decisión técnica:

| Cambio | Qué dice la DPIA | Qué más cambia |
|---|---|---|
| `STT_PROVIDER=openai` | Disparador (a). Además exige confirmar que el proyecto OpenAI está en región europea antes del cambio. | Pierde `[Hablante N]`. Cambia el encargado: `/privacidad` promete avisar. |
| Voxtral en tiempo real (`voxtral-mini-transcribe-realtime-2602`) | Disparador (b), y el ámbito de la DPIA lo deja fuera. | Sin diarización (sección 4.4). Cambia el flujo de datos, ver más abajo. Cambian el frontend y el backend, hoy "subir el audio y procesarlo". |
| Otro id de Voxtral por lotes (por ejemplo `voxtral-mini-2602`) | No es uno de los cuatro disparadores escritos. Pero el id literal está en la DPIA y la aprobación cubre el despliegue "tal y como está". | Hay que actualizar esos textos. Si basta con actualizar y volver a firmar, o hace falta reevaluar, lo decide quien firma la DPIA. |

**El cambio en el flujo de datos con streaming** (análisis de este documento, no texto de la
DPIA): hoy el audio solo sale del dispositivo al pulsar "Terminar y guardar", y el botón "El
profesional se opone" descarta la grabación en local sin subir nada (DPIA §1.2 paso 4; `/profesionales`
dice que la app descarta el audio al instante). Con transcripción en vivo el audio viaja al
proveedor mientras se captura, así que cuando el profesional se opone ya se han enviado los
segundos anteriores. Esa garantía, tal como está escrita, dejaría de cumplirse. La página de
Mistral sobre tiempo real tampoco declara retención ni residencia.

**En el mismo cambio, no después**, hay que actualizar:

1. `docs/legal/dpia-grabacion-consulta.md`: la tabla de encargado, el §1.2 paso 7, el párrafo de
   decisión del §6 y el cierre del §6.1 (nueva fecha y firma).
2. `docs/stt-provider-benchmark.md`: repetir la prueba con el modelo nuevo. Ese documento dice que
   un cambio de encargado es disparador de revisión de la DPIA.
3. El texto publicado: `apps/web/messages/{es,en,fr}.json`, claves `professionals.whereBody` y
   `privacy.whereBody`, y la fecha `privacy.updated`.
4. El párrafo de `STT_PROVIDER` en el `README.md` (sección "Data controller (GDPR)").

Quien instala por su cuenta (self-host) elige su propio encargado y debe reflejarlo en su
información de privacidad. El README ya lo dice.

## 6. Candidatos: todos pendientes de evaluación

**Ninguno de estos modelos se ha medido en AdelIA. Esta tabla no afirma que ninguno sea mejor, más
barato ni más rápido que el actual.** Los datos salen de la documentación de Mistral leída el 14 de
octubre de 2026 mediante un resumen automático de cada página; los ids, las fechas y los precios
hay que comprobarlos en la fuente antes de usarlos. Lo que no pude comprobar se marca como tal.

| Candidato | Id | Qué documenta el proveedor | Qué se desconoce o cuesta | Estado |
|---|---|---|---|---|
| Mistral Medium 3.5, para chat y briefing | `mistral-medium-3-5` (lanzado el 28 de abril de 2026 según el changelog) | Ventana de 256k. `reasoning_effort` con `high` y `none`. La ficha muestra "$1.5" y "$7.5" por millón de tokens sin etiquetar cuál es entrada y cuál salida. | A qué apunta `mistral-medium-latest` hoy. Comportamiento sin el parámetro. Herramientas y `json_schema` con reasoning. Residencia UE por modelo (la ficha no la declara). Calidad en español pediátrico, rechazo y citas. `high` gasta más tokens y tiene una latencia no medida. | Pendiente de evaluación |
| Mistral Small 4, para el turno de chat casual | `mistral-small-latest` (v26.03 en el catálogo) | La página "Reasoning" lista `mistral-small-latest` con `reasoning_effort`. | Versión a la que apunta ese alias ahora. No se leyó precio. Calidad. | Pendiente de evaluación |
| Mistral Large 4, para el briefing | `mistral-large-4-0` (v26.10 en el catálogo) | La página "Reasoning" lo lista con `reasoning_effort`. | No se leyó ficha ni precio. Calidad. | Pendiente de evaluación |
| Voxtral Mini Transcribe 2, fijar el id | `voxtral-mini-2602` (4 de febrero de 2026) | Diarización, vocabulario de contexto de hasta 100 términos, marcas de tiempo por palabra, hasta 3 horas. Según la documentación, es lo que `voxtral-mini-latest` ya llama. | Hay que confirmarlo con el paso 2. El vocabulario de contexto podría ayudar con los nombres de fármacos, que es lo que mira el benchmark: no se ha probado. Cambio legal (sección 5). | Pendiente de evaluación |
| Voxtral Mini Transcribe Realtime, texto en vivo en el grabador | `voxtral-mini-transcribe-realtime-2602` (4 de febrero de 2026) | WebSocket (`wss://api.mistral.ai/v1/audio/transcriptions/realtime`), retardo objetivo configurable (`target_streaming_delay_ms`), método del SDK `client.audio.realtime.transcribe_stream`. No admite `diarize`. | Pierde `[Hablante N]`. Retención y residencia no declaradas en esa página. Disparador (b) de la DPIA y cambio en el kill switch (sección 5). Reescribe el grabador y el backend. Precio no leído. | Pendiente de evaluación, y bloqueado hasta revisar la DPIA |
| OCR 4.1, fijar el id | `mistral-ocr-4-1` (16 de julio de 2026, disponibilidad general el 31 de agosto de 2026) | Según el changelog, `mistral-ocr-latest` apunta a él desde el 16 de julio. OCR 4.0 (`mistral-ocr-4-0`) figura como deprecado con retirada el 30 de septiembre de 2026, ya pasada. | Confirmar con el paso 2 lo que sirve hoy. Nadie ha comparado OCR 4 y 4.1 sobre informes de laboratorio de este corpus. Un id fijado a 4.0 no debe usarse. | Pendiente de evaluación |
| Embeddings | `mistral-embed` (v23.12 en el catálogo) | Figura como activo. No encontré aviso de retirada en el changelog leído. | No hay candidato. Cualquier otro modelo es la migración de 4.1. | Sin candidato |
| Agente Anthropic | `claude-sonnet-5-5` (sucesor del `claude-sonnet-5` actual); `claude-opus-5-5`, `claude-haiku-5-5`, `claude-fable-5-1` | Ids tomados de la lista de modelos de Anthropic vigente al escribir esto. | Sin verificar contra la API desde este entorno. Hay que comprobar que `thinking={"type": "disabled"}` se sigue aceptando y que las herramientas del agente se comportan igual. No hay evaluación en vivo del agente (3.1). Anthropic no está nombrado en `/privacidad` (4.6). | Pendiente de evaluación |

Fuentes leídas: docs.mistral.ai (visión general de modelos, ficha de Mistral Medium 3.5, página
"Reasoning", transcripción en tiempo real, changelog), todas el 14 de octubre de 2026.

## 7. Registro de cambios de modelo

Añadir una fila por cada cambio aprobado, con el resultado de la medición antes y después.

| Fecha | Cambio | Medición antes y después | Aprobado por |
|---|---|---|---|
| 2026-10-14 | Ninguno. Los nombres de OCR, embeddings, extracción y briefing pasan a settings con sus valores de siempre. Se añaden `chat_reasoning_effort` y `briefing_reasoning_effort`, sin definir. | No aplica: ningún valor efectivo cambia, y los tests lo fijan. | No aplica |
