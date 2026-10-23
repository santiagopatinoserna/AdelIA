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
2. **Una pregunta como máximo.** Si falta un dato esencial, el grafo pregunta una
   sola cosa y responde con lo que haya al siguiente turno. Nunca dos aclaraciones
   seguidas: la madre no tiene tiempo.
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

### `route`
Dos capas, en este orden:
1. **Reglas** (sin modelo, gratis, testables): acción de tarjeta `confirm` → ejecutar
   escritura; mensaje con número + unidad y verbo en pasado («ha tenido 37,8»,
   «ha dormido 3 h») → candidato a `record`; pregunta sobre el propio niño
   («¿en qué percentil está?», «¿qué vacunas le tocan?») → `track`.
2. **Clasificador** (modelo pequeño, salida JSON estricta con `intent`,
   `confidence`, `missing`). Umbral: `confidence < 0.6` → `clarify`.
Intenciones:
- `plan`: hay una preocupación y quiere saber qué hacer → plan de acción.
- `question`: quiere un dato o una explicación breve, sin acción
  («¿es normal que regurgite?», «¿a qué edad gatean?») → respuesta corta con fuente.
- `record`: cuenta algo del día para dejarlo anotado.
- `track`: pregunta por los datos de su hijo (expediente, curvas, vacunas, informes).
- `clarify`: falta la edad (sin perfil) o el dato que cambia la respuesta
  (fiebre sin cifra, «le pasa algo» sin síntoma).
- `other`: fuera de ámbito (adultos, mascotas, charla) → una frase de redirección.

### `clarify`
Una única pregunta concreta, de una línea, con los 2 o 3 valores más probables
como botones (p. ej. «¿Cuántos meses tiene?» con «0 a 3», «4 a 6», «7 a 12»).
El turno siguiente entra en `route` con la respuesta y `missing` vacío; si aún
falta algo, se responde con lo que hay y se dice qué cambiaría.

### `retrieve` y `decide`
Lo que hoy hace `routers/demo.py`: `retrieval_query` neutraliza el nombre, embed,
`retrieve_evidence` con corte 0.19 y margen 0.08, luego `retrieve_experience`
(mejor esfuerzo). `decide` fija `kind` solo con la evidencia.

### `plan`
Contrato actual de plan (Hoy / Vigila / Cuándo ir al médico / No olvides /
Lo que cuentan otras madres). Solo para `intent == "plan"`.

### `answer`
Contrato corto: una frase que responde, hasta 3 viñetas, cita en cada una,
sin encabezados de plan. Para `intent == "question"`. Mismas reglas de
abstención (`no_evidence`, `evidence_only`).

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
3. `clarify` con botones.
4. `record` con confirmación y diario. Solo con cuenta.
5. `track` migrado al grafo; retirar el bucle antiguo.

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
