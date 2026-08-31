# Calibración del umbral de evidencia

**Fecha de la medición:** 31 de agosto de 2026
**Corpus medido:** el de producción (118 fuentes, 258 fragmentos, `mistral-embed`
1024d), cargado también en el stack de dev (`adelia-dev-postgres-1`, puerto 5434).
**Reproducible con:** `apps/api/scripts/calibrate_answer_threshold.py`

## Por qué hubo que medir

`chat_orchestrator` pasaba `max_distance=0.45` a `retrieve_evidence`. Ese número
está por encima del diámetro del propio corpus: la distancia coseno máxima entre
dos fragmentos cualesquiera es **0,3386**.

```
33.153 pares  min 0,0129  p50 0,1773  p90 0,2567  p99 0,3008  max 0,3386
```

Es decir, el corte no podía rechazar nada, porque no existe ningún par de
fragmentos del corpus tan lejano como el corte. Toda pregunta, del tema que
fuese, recibía cuatro fragmentos rotulados "Clinical evidence". La promesa
central del producto ("si no hay evidencia, lo digo") no estaba en el código.

`retrieve_relevant_chunks`, en la otra mitad del dual-RAG, ni siquiera tenía
parámetro de distancia: devolvía los `top_k` fragmentos más cercanos del
expediente de la usuaria fueran los que fueran.

## Qué población mide esto, y por qué importa

La primera versión de esta calibración midió la población FUERA contra los
fragmentos pediátricos, mientras `retrieve_evidence` buscaba sobre los 258
fragmentos de la tabla, las 14 sondas adultas incluidas. La tabla decía "0/14
coladas a 0,20" y el código dejaba pasar 12 de 14 (distancia mínima 0,1324),
porque el vecino más cercano de una sonda adulta era otra fuente adulta de la
misma tabla. Una medición que no interroga la misma población que el código no
mide el código.

Hay dos formas de cerrar esa brecha: sacar las 8 fuentes adultas del índice, o
hacer que el código busque solo lo pediátrico. Se eligió la segunda, porque
además arregla una rama rota: `es.specialties ?| array[:spec_list]` construía
un array DEL parámetro, así que asyncpg recibía una lista donde esperaba un
`str` y reventaba con `DataError`. Toda llamada que pasara `specialties`
fallaba, en silencio, porque los dos sitios que la usan capturan la excepción y
devuelven vacío: la recuperación por especialidad de `briefing_orchestrator`
llevaba desde siempre devolviendo `""` y `[]`.

Ahora `chat_orchestrator._retrieve_evidence_for_query` y
`briefing_orchestrator._retrieve_specialty_evidence` pasan
`specialties=["pediatrics"]`, y este documento mide exactamente ese índice: las
**110 fuentes con la etiqueta** (las 108 de los tres ficheros de bebés más GINA
asma y el calendario vacunal del CDC). Las 8 fuentes adultas siguen en la tabla
pero ya no se buscan.

Medido en dev con las 14 sondas adultas, corte 0,20:

| | Sondas adultas que alcanzan otra fuente | Distancia mínima |
|---|---|---|
| Sin filtro (lo que hacía el código) | 12/14 | 0,1324 |
| Con `specialties=["pediatrics"]` | 1/14 | 0,1989 |

Y ninguno de los 244 fragmentos pediátricos pierde su evidencia con el filtro
puesto (0 de 244 se quedan sin ningún resultado).

Si algún día se retira el filtro, las consultas de
`scripts/calibrate_answer_threshold.py` tienen que ensancharse con él, o esta
tabla vuelve a describir otra cosa distinta del código.

## Método

Hacen falta dos poblaciones de "distancia del mejor fragmento": preguntas que el
corpus cubre y preguntas que no. El corpus ya contiene las dos, porque
`evidence_seed.json` arrastra diez fuentes generalistas de adulto junto a las 108
pediátricas de los tres ficheros del corpus de bebés.

- **Población DENTRO (240 sondas).** Cada fragmento pediátrico usado como
  consulta, contra el índice pediátrico, exigiendo que el mejor fragmento venga
  de *otra* fuente. Cubre los cinco temas del corpus: reflujo, alimentación
  complementaria 6-24 meses, adaptación a guardería, lactancia y hierro.
- **Población FUERA (14 sondas).** Cada fragmento adulto y ajeno usado como
  consulta, contra el mismo índice pediátrico: fibrilación auricular (ESC 2024,
  CHA₂DS₂-VASc), hipertensión (ACC/AHA 2017), colesterol (ACC/AHA 2018), cribado
  de cáncer de mama (NICE), cribado de cáncer colorrectal (USPSTF 2021),
  endometriosis (ESHRE 2022), diagnóstico de diabetes del adulto (ADA 2024) y el
  formato de traspaso SBAR (AHRQ).

Las dos fuentes pediátricas del seed (GINA asma, calendario vacunal CDC) no son
sondas de ninguna de las dos poblaciones, pero **sí forman parte del índice que
se busca**, que es lo que las hace importar: la sonda que sigue colándose a 0,20
es la de cribado colorrectal alcanzando el calendario vacunal del CDC.

## Resultado

```
sources: 108 baby, 8 adult off-topic; searched index: 110 pediatric-tagged sources

IN  (best fragment, in corpus)         n= 240  min=0.0210  p50=0.0663  p95=0.1110  max=0.1715
OUT (best fragment, off corpus)        n=  14  min=0.1989  p50=0.2127  p95=0.2260  max=0.2309

Valley: [0.1715, 0.1989]  width 0.0274  midpoint 0.1852

    cut     in kept   off leaked
  0.140    238/240       0/14
  0.160    239/240       0/14
  0.180    240/240       0/14
  0.190    240/240       0/14
  0.200    240/240       1/14
  0.220    240/240      11/14
  0.240    240/240      14/14
  0.280    240/240      14/14
  0.320    240/240      14/14
  0.360    240/240      14/14
  0.400    240/240      14/14
  0.450    240/240      14/14
```

Variante más exigente de la población DENTRO, obligando a que el mejor fragmento
venga de otro *tema* (no solo de otra fuente): máximo **0,1821**, el peor caso es
una sonda de guardería (reflujo 0,1539; alimentación 0,1559; guardería 0,1821).

| Corte | Dentro conservadas | Fuera coladas |
|---|---|---|
| 0,18 | 240/240 | 0/14 |
| **0,19** | **240/240** | **0/14** |
| 0,20 | 240/240 | 1/14 |
| 0,22 | 240/240 | 11/14 |
| 0,45 (antiguo) | 240/240 | 14/14 |

## Corte elegido: 0,19

`settings.evidence_max_distance = 0.19`. Está dentro del valle
[0,1821 a 0,1989] medido contra el índice que el código busca, deja 0,0079 de
margen sobre la peor sonda dentro de corpus en la variante cross-tema y 0,0089
por debajo de la sonda fuera de corpus más cercana.

Estuvo en 0,20 unas horas, tomado de la primera medición, cuya población FUERA
se puntuaba contra las tres fuentes de bebés (mínimo 0,2094) en vez de contra el
índice completo (mínimo real 0,1989). Con esa cifra corregida, 0,20 quedaba
0,0011 **por encima** del valle y dejaba pasar 1 de las 14 sondas ajenas: el
texto de cribado colorrectal de la USPSTF alcanzando el calendario vacunal del
CDC a 0,1989. Sigue siendo variable de entorno (`EVIDENCE_MAX_DISTANCE`), así
que recalibrar no exige tocar código.

`tests/test_chat_orchestrator.py` fija estas dos cotas en una prueba que no
necesita corpus, para que la puerta de despliegue no sea ciega: por debajo de
0,1821 el corte empieza a rechazar preguntas que el corpus sí responde, y por
encima de 0,1989 vuelve a colarse contenido de adulto.

`settings.patient_max_distance = 0.45` para los fragmentos del expediente de la
usuaria. Es deliberadamente laxo y **no** está calibrado: producción tiene 0
documentos de paciente, así que no hay nada que medir todavía. Su función es
descartar ruido, no sostener la promesa clínica, porque el contrato de respuesta
prohíbe interpretar un fragmento del paciente sin una cita `[ev_N]`. Recalibrar
cuando existan documentos reales.

## Limitación conocida y cómo cerrarla

Las sondas son *fragmentos de documento* usados como consulta, no preguntas de
una madre. Una pregunta corta y coloquial ("¿es normal que regurgite después de
cada toma?") es léxicamente más pobre que un párrafo de guía clínica, así que su
distancia al mejor fragmento será algo mayor. Las dos poblaciones se desplazan
hacia arriba, pero no necesariamente lo mismo.

La medición definitiva ya está escrita: 40 preguntas de control, 20 dentro y 20
fuera, en `scripts/calibrate_answer_threshold.py --mode questions`. Solo necesita
una `MISTRAL_API_KEY` de dev, que hoy no existe en el servidor
(`~/.config/godi/adelia-mistral.env`, la ruta que documenta
`scripts/server-verify.sh`, no está creada).

```bash
ssh santiago@192.168.1.150 'cd /opt/adelia-dev/apps/api && \
  POSTGRES_HOST=localhost POSTGRES_PORT=5434 POSTGRES_USER=adelia \
  POSTGRES_PASSWORD=adelia_dev POSTGRES_DB=adelia AUTH_SECRET=ci-only-secret \
  MISTRAL_API_KEY=... uv run python scripts/calibrate_answer_threshold.py --mode questions'
```

Si esa ejecución muestra preguntas dentro de corpus por encima de 0,19, subir
`EVIDENCE_MAX_DISTANCE` al nuevo valle: es una variable de entorno, no hay que
tocar código. Si las dos poblaciones se solapan, un umbral de distancia no basta
y hace falta un segundo filtro (reranker o juez binario barato), como decía la
auditoría.

## Qué pasa cuando no queda nada

Calibrar el corte solo sirve si el rechazo es real. En
`chat_orchestrator.answer_question_streaming`, cuando tras aplicar los dos cortes
quedan **0 fragmentos de evidencia y 0 fragmentos del expediente**, no se llama al
modelo generativo: el código devuelve `answer_contract.no_evidence_reply(locale)`,
que dice que no hay evidencia y remite al pediatra. Una cláusula del prompt es una
petición al modelo; esto es una garantía.

## Reproducir la geometría del corpus

```sql
WITH p AS (
  SELECT a.embedding <=> b.embedding AS d
  FROM evidence_chunks a JOIN evidence_chunks b ON a.id < b.id
  WHERE a.embedding IS NOT NULL AND b.embedding IS NOT NULL
)
SELECT count(*), min(d),
       percentile_cont(0.50) WITHIN GROUP (ORDER BY d),
       percentile_cont(0.99) WITHIN GROUP (ORDER BY d),
       max(d)
FROM p;
```
