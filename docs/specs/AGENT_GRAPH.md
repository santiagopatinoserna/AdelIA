# AdelIA: grafo del agente (diseño, 2026-10-23)

Estado: propuesta para validar antes de construir. Sustituye el bucle actual de
`agent/orchestrator.py` (modelo + herramientas, 5 pasos) por un grafo explícito
en LangGraph donde cada decisión clínica es un nodo con contrato y test propio.

## Por qué un grafo

Hoy hay tres caminos distintos que hacen cosas parecidas sin compartir reglas:

| Superficie | Banderas rojas | Recuperación | Formato | Escribe datos |
|---|---|---|---|---|
| `/api/demo/ask` | sí | evidencia + experiencia | siempre plan | no |
| `/api/chat` | sí | evidencia | contrato chat | no |
| agente `/dashboard` | sí | herramientas del modelo | libre | perfil, briefing (con confirmación) |

Y el plan de acción se aplica a cualquier pregunta, aunque la madre solo quiera
un dato («¿cuándo toca la vacuna del rotavirus?») o solo quiera anotar algo
(«hoy ha tenido 37,8 y ha comido poco»). Un grafo decide primero **qué quiere**
y después **qué contrato** aplica.

## Principios que el grafo no puede violar

1. **Guardia antes que modelo.** Las banderas rojas se evalúan de forma determinista
   sobre el mensaje y también sobre cualquier dato que la madre registre
   (una temperatura anotada de 38,2 a los 2 meses es una urgencia, no un apunte).
2. **Una ronda como máximo por tema.** Si falta un dato esencial, el grafo pregunta
   una cosa (dos en el agente, en una sola tarjeta) y responde con lo que haya al
   siguiente turno. Nunca dos rondas en el mismo tema: la madre no tiene tiempo.
3. **Escribir solo con confirmación.** Registrar, guardar en perfil o generar un
   briefing pasa siempre por una tarjeta de confirmación (patrón ya existente).
4. **La experiencia no decide.** «Lo que cuentan otras madres» entra solo en el nodo
   plan, después de que la evidencia haya fijado `kind`.
5. **Un solo contrato de redacción** (`services/answer_contract.py`) con variantes
   por nodo; nunca texto libre del modelo sin contrato.
6. **Mismo grafo en las tres superficies.** La demo lo ejecuta sin cuenta
   (sin nodos de registro ni expediente); el chat y el agente con cuenta, completo.

## Estado compartido

```python
class AgentState(TypedDict):
    locale: str
    message: str
    history: list[dict]            # saneada, 12 turnos máx.
    facts: ProfileFacts            # edad, sexo, nombre; None en demo
    account: bool                  # False en la demo
    # Decisiones
    flag: RedFlag | None
    intent: Literal["plan", "question", "record", "track", "clarify", "other"]
    intent_confidence: float
    missing: list[str]             # datos esenciales que faltan (máx. 1 se pregunta)
    # Recuperación
    evidence: list[EvidenceMatch]
    experience: list[EvidenceMatch]
    kind: Literal["red_flag", "no_evidence", "evidence_only", "answer"]
    # Registro
    record: RecordDraft | None     # {tipo, valor, unidad, fecha, texto}
    pending_write: dict | None     # herramienta + args a confirmar
    # Salida
    answer: str
    citations: list[dict]
    cards: list[dict]
```

## Nodos y aristas

```
                ┌──────────┐
   mensaje ───▶ │  guard   │ bandera roja ──▶ [urgent] ──▶ END
                └────┬─────┘
                     │ sin bandera
                ┌────▼─────┐
                │  route   │  (reglas + clasificador con salida estructurada)
                └────┬─────┘
    ┌──────────┬─────┴──────┬───────────┬────────────┐
    ▼          ▼            ▼           ▼            ▼
 [clarify]  [retrieve]   [record]    [track]      [other]
  1 pregunta    │            │           │            │
    END    ┌────▼────┐   guard sobre   herramientas   redirigir
           │ decide  │   el dato       (percentil,    en 1 frase
           └────┬────┘      │           vacunas,       END
                │           ▼           expediente)
         ┌──────┴──────┐  tarjeta         │
         ▼             ▼  confirmar       ▼
      [plan]       [answer]    END     [compose]
    (concern)     (dato puntual)          END
         └──────┬──────┘
                ▼
           [compose] ──▶ END
```

### `guard`
Determinista, sin modelo (`clinical/red_flags.detect`). Entrada: mensaje y, si
`record` ya extrajo un valor, también ese valor normalizado. Salida `flag`.
Respuesta fija por código de bandera (`red_flag_reply`). Nunca se salta.
Después de las banderas, el ámbito de edad (`clinical/age_scope`, relevo 4.1): si el
mensaje nombra un niño de 3 años o más y ningún bebé, `kind = "no_evidence"` con una
frase de ámbito más el rechazo (`out_of_scope_age_reply`), sin pasar por la puerta de
gasto, el enrutado ni el embedding. Cubre B7, B12, B13 y B15 del golden.

### `thread` (2026-11-09)
Antes del guard, sin modelo (`agent/conversation.py`). Lee el historial que manda
la superficie y decide si el turno es tema nuevo, seguimiento o corrección («no es
enfermo», «no tiene fiebre», «es tema nuevo», otra edad). De ahí salen:
- la búsqueda: sus palabras en el tema, nunca las de AdelIA y sin lo que ella
  retira; en un tema de conducta, las palabras del corpus (adaptación, ansiedad por
  separación, desarrollo social). Un primer turno se busca tal cual (golden intacto);
- lo que ve el modelo que responde: el tema en un seguimiento, nada de otro tema,
  y en una corrección solo sus palabras y una nota de lo que retira;
- si el tema ya tuvo su ronda de preguntas y si ya se le dijo que no hay fuentes.
Su respuesta escrita a una tarjeta cuenta como respuesta y se lee bajo su pregunta.
Cuando las reglas no saben, la misma llamada de `route` (solo si las reglas de
intención se abstienen) recibe la cola del hilo y devuelve también `turn` y
`search_query`. Una preocupación de conducta pregunta antes de responder (cuánto
lleva en la guardería o desde cuándo, y si en casa mira, sonríe, responde a su
nombre y balbucea o dice palabras), sin pagar el enrutado. Sin evidencia: primero
una ronda para una preocupación observada (nunca un dato ni un fármaco); después,
el rechazo una sola vez por tema, sus propias palabras para la consulta y una
tarjeta para anotarlas en su historial.
Tras una derivación, el tema sigue derivado (2026-11-11): solo su «otra cosa» abre
otro, y `guard` lee sus palabras del tema con el mensaje nuevo, así que «le doy
apiretal mientras» o «puedo esperar a mañana?» reciben la derivación otra vez. Tras
la frase de redirección, un mensaje que nombra al bebé abre tema nuevo. Las reglas
leen sus abreviaturas («q», «xq», «tb», «la guarde»).
Con el modelo real (2026-11-11, `docs/BATERIA_MODELO_2026-11-11.md`): negar algo que el plan
solo listaba en «Vigila» o «Cuándo ir al médico» («no tiene fiebre» tras un plan de vómitos)
es un dato nuevo, no una corrección; una lectura («38,7 °C») cuenta como la fiebre que la
respuesta daba por hecha; y el clasificador no puede llamar corrección a un turno sin negación.
En un tema ya rechazado, el modelo recibe la línea corta para la parte que siga sin fuente.

### `route`
Dos capas, en este orden:
1. **Reglas** (sin modelo, gratis, testables): acción de tarjeta `confirm` → ejecutar
   escritura; mensaje con número + unidad y verbo en pasado («ha tenido 37,8»,
   «ha dormido 3 h») → candidato a `record`; pregunta sobre el propio niño
   («¿en qué percentil está?», «¿qué vacunas le tocan?») → `track`.
2. **Clasificador** (modelo pequeño, salida JSON estricta con `intent`,
   `confidence`, `missing`). Umbral: `confidence < 0.6` → `clarify`.
En un seguimiento manda el turno: si su mensaje solo ya lo deciden las reglas, se
enruta solo; el primer mensaje del tema nunca lo convierte en anotación ni en el
bucle de herramientas (2026-11-11). Un tema de conducta, tras su ronda, va al plan
sin pagar el clasificador. Si el clasificador cae, el agente responde con fuentes
(plan, o respuesta corta para una pregunta sin síntoma, preocupación ni fármaco),
nunca con el bucle de herramientas.
Intenciones:
- `plan`: hay una preocupación y quiere saber qué hacer → plan de acción.
- `question`: quiere un dato o una explicación breve, sin acción
  («¿es normal que regurgite?», «¿a qué edad gatean?») → respuesta corta con fuente.
- `record`: cuenta algo del día para dejarlo anotado.
- `track`: pregunta por los datos de su hijo (expediente, curvas, vacunas, informes).
- `clarify`: falta la edad (sin perfil) o el dato que cambia la respuesta
  (fiebre sin cifra, «le pasa algo» sin síntoma).
- `other`: fuera de ámbito (adultos, mascotas, charla) → una frase de redirección
  (`out_of_scope_reply`, en el agente; en la demo y el chat sigue el plan).

### `clarify`
Una única pregunta concreta, de una línea, con los 2 o 3 valores más probables
como botones (p. ej. «¿Cuántos meses tiene?» con «0 a 3», «4 a 6», «7 a 12»).
El turno siguiente entra en `route` con la respuesta y `missing` vacío; si aún
falta algo, se responde con lo que hay y se dice qué cambiaría.

### `retrieve` y `decide`
Lo que hoy hace `routers/demo.py`: `retrieval_query` neutraliza el nombre, embed,
`retrieve_evidence` con corte 0.19 y margen 0.08, luego `retrieve_experience`
(mejor esfuerzo). `decide` fija `kind` solo con la evidencia.
Con cuenta (2026-11-11): cuando las reglas de intención se abstienen, la búsqueda (su historial
y las guías, a la vez) empieza mientras el clasificador decide, y se descarta si la decisión
pregunta, anota o cambia las palabras de la búsqueda. Sin evidencia, su historial ya no se
salta la ronda de una preocupación observada; en un tema ya rechazado, el agente responde la
línea corta y la tarjeta para anotar sin pagar al modelo. El modelo que responde recibe la edad
del perfil. Mientras espera, el panel lee `status` («searching», «writing» con cuántas fuentes).
Detrás de `implicit_subject_expansion` (apagado), una frase que no nombra a nadie
(«Tiene diarrea desde ayer») se busca también como «Mi bebé de N meses: …», con los
mismos cortes y la mejor distancia por fragmento (`agent/implicit_subject.py`).
Detrás de `development_signs_retrieval` (apagado, 2026-11-11), en el agente, un tema de
desarrollo (un hito que aún no llega: «no gatea», «no se sienta», «no anda») o de conducta
(`conversation.behaviour`, también tras «No es enfermo») busca además el tema con las palabras
del corpus para las señales de alarma del desarrollo, con los mismos cortes, y añade hasta dos
fragmentos detrás de los de su frase (`agent/development_signs.py`); el modelo los recibe y
`compose` deja la tarjeta de los que cita. Sin evidencia principal no añade nada: B2 sigue
rechazada (0,2164 a UNICEF con su vector grabado, fuera del corte 0,19).
El léxico de madre (`lay_query_expansion`, encendido en producción) lee también el golpe en la
cabeza y la caída del bebé (es/en/fr) con las palabras de la hoja de la SEUP («traumatismo
craneal, golpe en la cabeza»).

### `plan`
Contrato actual de plan (Hoy / Vigila / Cuándo ir al médico / No olvides /
Lo que cuentan otras madres). Solo para `intent == "plan"`.

### `answer`
Contrato corto: una frase que responde, hasta 3 viñetas, cita en cada una,
sin encabezados de plan. Para `intent == "question"`. Mismas reglas de
abstención (`no_evidence`, `evidence_only`).

### Seguimiento de un tema ya respondido (2026-11-11, apagado)
Detrás de `follow_up_brevity`, un seguimiento cuyo modelo ve en el hilo una respuesta
anterior del tema con fuentes (`conversation.answered`; nunca una corrección, una
respuesta a botones ni un tema nuevo) recibe el contrato `follow_up`: responde a lo que
pregunta ahora en pocas frases citadas, sin repetir el plan, y «Cuándo ir al médico» solo
si lo nuevo trae una señal que no tenía o cambia su urgencia; una señal nueva nunca se
recorta. La intención no cambia. Detrás de `answer_effort_question`, `answer_effort_plan`
y `answer_effort_follow_up` (sin valor, «medium» como siempre), el esfuerzo de
pensamiento de Claude por forma de respuesta; el del seguimiento manda sobre los otros.
Las banderas rojas, los rechazos del código y las preguntas con botones no llaman a
ningún modelo.

### `record`
1. Extracción estructurada (modelo, JSON): `tipo` ∈ {temperatura, toma, sueño,
   deposición, síntoma, medicación dada, vacuna puesta, nota}, `valor`, `unidad`,
   `fecha` (hoy por defecto), `texto` original.
2. `guard` sobre el valor (temperatura, edad).
3. Tarjeta de confirmación con la entrada tal y como se va a guardar.
4. Al confirmar: se añade a la entrada de diario del día (misma tabla que el
   diario de Telegram, `services/telegram_diary`), para que el seguimiento
   del niño tenga una sola fuente.
5. Respuesta de una línea: «Anotado: 37,8 °C a las 16:10.» y, si hay un dato
   anterior comparable, la comparación («ayer 37,2»).

### `track`
Las herramientas actuales (`percentil_crecimiento`, `proximas_vacunas`,
`buscar_en_expediente`, `evaluar_labs`) en un bucle acotado a 3 pasos.
Las de escritura (`generar_briefing`, `completar_perfil`) siguen pasando por
tarjeta de confirmación.

### `compose`
Poda y renumera citas (`services/citations.prune_and_renumber`), añade
descargo, emite los eventos SSE que ya consume el front (`token`, `card`,
`final`). El front no cambia de protocolo.
Un texto con el rechazo fijo sale solo con lo que cita: un rechazo entero, sin
ninguna tarjeta; una respuesta mixta, con su evidencia citada y las madres que
cita `[ex_N]` (2026-11-06, `docs/specs/RECHAZOS_Y_TARJETAS.md`).
Con cuenta (2026-11-11): si hubo fuentes y el modelo escribió solo el rechazo, o en un
tema ya rechazado solo la línea corta, sin ninguna cita, el turno acaba como el rechazo
del código: `no_evidence`, sus palabras para la consulta tras el texto del modelo (que no
se corta) y la tarjeta para anotarlas. En producción la búsqueda de un seguimiento
encontraba siempre las fichas del tema, así que ese camino del código no se daba nunca.

## Qué se reutiliza y qué es nuevo

| Reutilizado | Nuevo |
|---|---|
| `red_flags.detect`, `red_flag_reply` | `agent/graph.py` (StateGraph) |
| `retrieve_evidence`, `retrieve_experience` | `agent/route.py` (reglas + clasificador) |
| `answer_contract` (plan) | `answer_contract` variante `question` y `clarify` |
| `execute_tool`, tarjetas de confirmación | `agent/record.py` (extracción + guard + diario) |
| `telegram_diary` para el diario | evaluación de enrutado: 60 mensajes etiquetados |
| eventos SSE y front actuales | tests de grafo por nodo y de caminos completos |

Dependencia nueva: `langgraph` (sin LangChain completo; se usan solo
`StateGraph`, aristas condicionales y checkpoint en memoria por turno). Los
proveedores siguen siendo los nuestros (`agent/provider.py`), no los de
LangChain.

## Cómo se mide que funciona

- **Enrutado**: conjunto de 60 mensajes reales o realistas etiquetados
  (15 por intención principal) en `tests/data/routing_es.json`; exigido
  ≥ 90 % de acierto y 0 mensajes de bandera roja enrutados a otro sitio.
- **Golden clínico**: `clinical/golden.py` intacto (grupo A responde, B rechaza).
- **Registro**: 20 frases de diario → extracción correcta de tipo y valor; una
  temperatura de alarma pasa por `guard` y no se guarda sin aviso.
- **Una sola aclaración**: test de dos turnos que prueba que el segundo turno
  responde aunque siga faltando algo.
- **Front**: Playwright con respuestas simuladas para los tres formatos
  (plan, respuesta corta, pregunta con botones) a 390 px.
- **Conversación** (2026-11-10): `scripts/conversation_battery.py`, unas 30 conversaciones
  de 2 a 5 turnos (`scripts/conversation_scenarios.json`) con lo esperado por turno. Sin
  modelo (CI) dice cuántos turnos cumplen; los defectos conocidos llevan `gap` con su
  motivo y el test obliga a quitar la marca cuando se arreglan. Con `--with-model
  --budget-usd N`, en el contenedor de la API, cada turno pasa por `run_turn` con una
  invitada QA que se borra al terminar, y el gasto cuenta bajo la etiqueta `qa`.
  `--classifier-down` repite la batería con el clasificador caído. El 2026-11-11 se
  arreglaron sus 13 defectos (82/95 → 95/95) y se añadieron 6 conversaciones de
  control escritas antes de mirar el arreglo (etiqueta `control_sobreajuste`).
  Con el modelo real (11-nov, tope 2 $, 57 de 110 turnos): 16 fallos, sus conversaciones
  reproducidas sin modelo en `scripts/conversation_regressions.json` (20/32 en `main`, 32/32
  después). `--resume <informe>` corre solo lo que falta; `--from`, `--tag`, `--only` eligen.
  Esas 11 con el modelo tras el despliegue (11-nov, 04:08): 26/32; de los 6 fallos, 3 de
  código (`scripts/conversation_regressions_2.json`, 7/9 en `main`, 9/9 después) y 3 de
  búsqueda (la ficha estaba en el corpus y no salió). El informe con modelo guarda los
  ajustes con que corrió y, aparte, palabras y primera palabra de los seguimientos de un
  tema ya respondido; los comandos para comparar los ajustes apagados y encendidos están
  en el docstring de la batería.
  Los 3 fallos de búsqueda (golpe T1, no-gatea T1, guardería T2 y T3) están en
  `scripts/conversation_regressions_3.json`, con dos formas más de contar el golpe: sin modelo,
  `search_adds` comprueba lo que la búsqueda añade a sus palabras; con el modelo, `found`, las
  fuentes que recibe el modelo que responde (comandos en el docstring de la batería).

## Orden de construcción (cada paso desplegable por separado)

1. `route` con reglas + clasificador y su evaluación de 60 mensajes. Sin cambiar
   nada visible: solo registrar la intención en logs y medir.
   **Hecho** (rama `night/graph`): `agent/route.py`, `tests/data/routing_{es,en,fr}.json`
   (72 mensajes es + 8 banderas rojas), `scripts/eval_routing.py` para la matriz de
   confusión. La demo y el chat llaman a `spawn_route_log` tras `guard` y escriben
   una línea `route intent=... via=... conf=...`; la respuesta no cambia. Reglas solas:
   96 % en es (69/72 deciden, 0 errores); el modelo (`mistral_routing_model`,
   `mistral-small-latest`) solo entra cuando abstienen, con plazo de 2 s.
2. Grafo con `guard → route → retrieve → decide → plan | answer → compose` en
   la demo. Visible: las preguntas de dato dejan de recibir un plan.
   **Hecho y desplegado (23-oct, 272e23d)**: `agent/graph.py`; variante `question` del
   contrato (`chat_system_prompt(shape="question")`: una frase y hasta 3 viñetas citadas,
   sin encabezados, sin recortar señales de alarma); la demo devuelve `intent` y titula
   «Tu respuesta». LangSmith queda apagado al importar el grafo.
3. `clarify` con botones.
   **Hecho y desplegado (23-oct, fa2f9a8 + 87e26d1)**: fiebre contada sin cifra → «¿Cuánto
   ha marcado el termómetro?» con 3 tramos y «No la he medido»; edad por tramos (el guard
   recibe la edad más baja del tramo). `absorb` mete la respuesta en el mensaje antes del
   guard; nunca dos aclaraciones seguidas. El proxy de la demo no reenviaba la respuesta
   (arreglado en 87e26d1, con un e2e sin mocks).
4. `record` con confirmación. Solo con cuenta.
   **Hecho**: tabla `observations` (0023, decisión 2, no el diario de Telegram);
   `agent/record.py` lee por reglas las 12 líneas `record` del conjunto (el modelo solo
   para lo que no leen; si falla, nota), guard sobre el valor, tarjeta con la entrada tal
   cual, validación de nuevo al confirmar, y respuesta de una línea con la anterior
   («La anterior: ayer, 37,2 °C»). Borrado y exportación RGPD la incluyen.
5. `track` migrado al grafo; retirar el bucle antiguo.
   **Hecho**: `run_agent_turn` retirado; `agent/orchestrator.run_turn` ejecuta el grafo y el
   bucle de herramientas es el nodo `track` (3 pasos). El chat (`answer_question_streaming`)
   ejecuta el mismo grafo sin botones ni tarjetas. Lo que el router no sabe colocar (o el
   respaldo cuando el modelo cae) va al bucle de herramientas en el agente, como siempre, y
   al plan en las demás superficies. Briefings, perfil, ensayos e interacciones van a
   `track` por regla.

### Medición del clasificador en producción (23-oct, solo lectura)

Con la clave de producción, `mistral-small-latest` respondió 429 (rate limited) a todas las
llamadas, también espaciadas 2 s; la cuenta no tiene acceso a `mistral-large-latest`.
En producción hoy el enrutado lo deciden las reglas y, cuando se abstienen, el respaldo.

| Clasificador | Acierto es (72) | p50 | p95 | > 2 s |
|---|---|---|---|---|
| Reglas solas | 69/72 (95,8 %), 3 abstenciones | 0 s | 0 s | 0 |
| `ministral-8b-latest` (Mistral) | 59/72 (81,9 %) | 0,44 s | 0,91 s | 1/72 |
| `gpt-5.1` (proveedor de la demo) | 67/72 (93,1 %) | 1,31 s | 11,65 s | 12/72 |

En en y fr (12 cada uno) las reglas aciertan 12/12. Las 3 abstenciones en español las
acierta `gpt-5.1` (3/3) y `ministral-8b` (2/3).

## Decisiones tomadas (23-oct, Santiago delegó la decisión técnica)

1. **Clasificador**: reglas primero; cuando no deciden, modelo pequeño de Mistral
   (UE) con cuentas reales y el proveedor de la demo en la demo. Salida JSON
   estricta validada con Pydantic; si el JSON no valida, `intent = "plan"`
   (el camino con más salvaguardas), nunca `other`.
2. **Registro**: tabla propia `observations` (perfil, tipo, valor numérico,
   unidad, texto, fecha y hora, origen) desde el principio, para curvas y
   comparaciones; el diario de Telegram sigue siendo texto y no cambia.
3. **Sin evidencia pero con experiencias**: se responde solo con «Lo que cuentan
   otras madres», precedido de una frase fija: «No he encontrado guías ni
   estudios sobre esto. Otras madres cuentan:». `kind` pasa a ser
   `experience_only`, nunca `answer`; sin apartado de médico; el descargo se
   mantiene. Solo si `guard` no ha saltado y el tema no es clínico (la
   experiencia nunca llega a dosis, síntomas ni urgencias por construcción
   del corpus).
   Implementado en la demo (`routers/demo.py`, `experience_only_contract`): la
   frase inicial la pone el código, el modelo solo escribe las viñetas [ex_N]
   y el código descarta la salida entera (y rechaza como antes) si trae otro
   apartado o una cita que no sea [ex_N]. Medido en producción (23-oct,
   corte 0.19 / margen 0.08, 20 experiencias): ninguna pregunta del grupo B
   del golden set llegaría a `experience_only`; las que tienen experiencias
   (B5, B8, B9) tienen también evidencia y siguen el camino de siempre, y
   la más cercana sin evidencia (B4, horóscopo) queda a 0.1959, fuera del
   corte. El chat (`chat_orchestrator`, el camino que mide el golden set)
   no consulta la capa de experiencias.
