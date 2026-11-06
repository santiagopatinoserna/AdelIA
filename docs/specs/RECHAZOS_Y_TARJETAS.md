# Rechazos limpios y rechazos que no tocan (2026-11-06)

Datos: `~/dev/adelia-design/shots/prod-b-under-cut.json`, `prod-domains-eval.json` y
`lay-language-eval.json` (producción, demo pública, Claude, léxico encendido).

## 1. Un rechazo nunca lleva tarjetas (hecho, en código)

En producción B8 (ictericia a los 4 meses) devolvía el rechazo con una cita de cólicos de la
capa de madres, y B17 (frenillo, en inglés) con mordedores, llanto y porteo. El modelo había
escrito el rechazo fijo; `kind` seguía siendo `answer`; `_cited_only` ya quitaba la evidencia
no citada, pero las experiencias se añadían siempre.

Regla nueva en `compose` (`agent/graph.py`), que sirve a la demo, al chat y al agente: si el
texto lleva el rechazo fijo (`golden.is_refusal`, en cualquiera de los tres idiomas), sale
solo con lo que el texto nombra.

- Rechazo entero: sin evidencia, sin madres y sin citas del historial.
- Respuesta mixta (B9, B11, B14): conserva la evidencia que cita `[ev_N]` y solo las
  experiencias que cita `[ex_N]`. B9 pierde los tres posts de sueño que no usaba.
- Un `[N]` del historial citado en un texto con rechazo se conserva (es un dato citado).
- `experience_only` no cambia: su `kind` no es `answer`.
- Las respuestas sin rechazo no cambian. Que un plan normal lleve experiencias que no cita
  sigue igual hoy; si se quiere la misma poda para todo plan, es otra decisión (afecta a la
  sección de madres, que lleva otra sesión).

## 2. «¿Cuándo se le cae el cordón umbilical y cómo lo cuido?» (diagnóstico, sin cambio)

La recuperación es buena: Cuidados del cordón umbilical (AEPap, 0,102), HealthyChildren
(0,105) y KidsDoc (0,118), con el léxico apagado y encendido. La respuesta fue el rechazo, con
`kind = answer` e `intent = question`.

Comprobado en código, nodo a nodo, y fijado en
`tests/test_agent_graph.py::test_the_umbilical_cord_refusal_is_the_model_not_the_code`:

- No hay filtro de edad en la recuperación (`retrieve` no recibe la edad).
- `decide` fija `answer` en cuanto hay evidencia. Ningún nodo sustituye una respuesta sin
  marcadores por el rechazo: `_cited_only` solo poda tarjetas, nunca el texto.
- La ruta corta (`answer`, forma `question`) no tiene control propio de abstención.
- Con un modelo simulado que responde citando, el grafo devuelve el texto tal cual y las tres
  tarjetas.

Luego el rechazo lo escribe el modelo. La causa más probable es la cláusula del contrato
(`answer_contract`, añadida el 2026-11-03 por B8): «Una fuente que trata una edad que no
incluye la del bebé (una guía de recién nacidos ante un bebé de 4 meses) no respalda nada
para este bebé», leída junto al historial de la demo («Lucía, 5 meses»). La pregunta dice
«se le cae», y el modelo la aplica a Lucía. En la misma medición, «Mi recién nacido está un
poco amarillo» citó las guías y luego rechazó «para Lucía» con la misma frase, y «¿Cuánto
peso es normal que pierda en la primera semana?» sí respondió, avisando de que Lucía tiene
5 meses. El modelo duda en la frontera de esa cláusula.

No he tocado ni el prompt clínico ni la demo. Propuestas para decidir:

1. Precisar la cláusula: si la pregunta es general sobre una etapa (el cordón, la primera
   semana), responder con la fuente y decir en una frase que el bebé del historial ya pasó
   esa etapa; si pregunta por lo que le pasa a este bebé ahora (B8), seguir rechazando.
   Exige medir el golden entero con Claude (B8 debe seguir rechazado) antes de desplegar.
2. En la demo, no sugerir ni medir preguntas de recién nacido contra un bebé de 5 meses, o
   medirlas sin historial. Es la vía más barata, pero no arregla a una madre real con un
   bebé de 5 meses que pregunte por su recién nacido.

Recomiendo la 1, con la medición del golden como puerta.

## 3. Léxico de palabras de madre (hecho)

Entradas nuevas en `agent/lay_terms.py`, todas con su término escrito en el corpus pediátrico
(lo fija `test_every_term_is_written_in_the_pediatric_corpus`) y ninguna para el grupo B:

| Entrada | Términos | Cuidado |
|---|---|---|
| despertares | despertares nocturnos, sueño del bebé | no lee «duerma» (B9) ni «sleep» solo (B12); «no se despierta» queda fuera |
| inapetencia | falta de apetito, inapetencia, rechazo del alimento | solo «no come» y el biberón; rechazar la verdura (B9, B14) no cuenta |
| vomitos | vómitos | cede ante regurgitación; sin francés (B13) |
| sudoracion | sudoración, sudor | «sudadera» no cuenta |
| respiracion_ruidosa | ronquido, respiración ruidosa | «está ronca» es afonía (L15), no ronquido |

Y «manchas» en boca-mano-pie, para L21 traducida («Tiene manchas en las manos y en la boca»).

Quedan fuera a propósito: gases (es la palabra de B11 traducida), llora mucho por las tardes
(fijado como falso amigo del ojo que llora, y el llanto inconsolable es terreno de banderas
rojas), rechazo del pecho (el corpus no lo escribe; las fichas de apetito son de niños
mayores). El léxico solo cambia la búsqueda: el guard ya ha corrido sobre su texto original.

`scripts/eval_lay_language.py` mide ahora también estas quejas (E1 a E12, con E9 y E10 como
controles), usa `embed_with_retry` y espera 2 segundos entre sondas. Falta ejecutarlo en
producción para ver las distancias reales: aquí no hay clave de embeddings.
