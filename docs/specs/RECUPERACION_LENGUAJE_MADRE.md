# Recuperación con las palabras de la madre (diagnóstico, 2026-11-05)

Estado: diagnóstico hecho leyendo código y corpus; arreglo detrás de
`lay_query_expansion` (apagado). Sin clave de embeddings en local, ninguna distancia
de este documento está medida: lo que hay que medir lo mide `apps/api/scripts/eval_lay_language.py`.

## Qué se midió en producción

30 preguntas reales en la demo (`~/dev/adelia-design/shots/prod-domains-eval.json`,
corte 0,19, margen 0,08, 434 fuentes). Siete fallan aunque el corpus cubre el tema:

| # | Pregunta | Resultado en producción |
|---|---|---|
| P1 | Lleva 4 días sin hacer caca y toma pecho, ¿es normal? | `no_evidence`, 0 fuentes |
| P2 | Tiene el culito muy rojo del pañal | `no_evidence`, 0 fuentes |
| P3 | Le han salido granitos en las manos y en la boca | `no_evidence`, 0 fuentes |
| P4 | Tiene un ojo con legañas amarillas | `no_evidence`, 0 fuentes |
| P5 | ¿Cuándo se le cae el cordón umbilical y cómo lo cuido? | `answer` sin ninguna cita: el modelo devolvió el rechazo |
| P6 | ¿A qué edad suelen empezar a gatear? | `answer` con la guía de UNICEF, sin la edad |
| P7 | Tiene tos de perro por la noche | `answer` con «Cómo manejar la tos», ninguna fuente de laringitis |

## Cómo busca hoy (código)

- Demo (`routers/demo.py` → `agent/graph.py`, nodo `retrieve`): `retrieval_query` quita el
  nombre de Lucía; `corpus_query` traduce solo fr/en (las siete son es, no cambia nada);
  un embedding; `retrieve_evidence` con `specialties=["pediatrics"]`, `top_k=4`,
  `max_distance=0.19`, `relative_margin=0.08`. No pasa `query_text`.
- Chat y agente (`chat_orchestrator.retrieve_for_account`): lo mismo, más `query_text` para
  la búsqueda por texto.

## Filtros, uno por uno

- **Edad**: la recuperación no filtra por edad. La edad (5 meses en la demo) solo entra en
  el guard y en `age_scope`; ninguna de las siete nombra un niño de 3 años o más.
- **Especialidad**: todas las fuentes de los siete temas llevan `pediatrics`.
- **Idioma**: todos los fragmentos están en español (`language: es`), también los de
  NHS, ameli o mpedia, que están resumidos en español.
- **Banderas rojas**: ninguna de las siete dispara el guard (lo fija
  `tests/test_eval_lay_language.py`).
- **Margen relativo**: solo actúa contra la mejor distancia de la propia pregunta. En P1 a
  P4 nada pasó el 0,19, así que el margen no tuvo nada que recortar. En P6 y P7 pudo dejar
  fuera la fuente buena si la lateral quedó delante; sin distancias no se sabe.
- **Búsqueda por texto** (migración 0021): en la demo no corre (no hay `query_text`) y
  `retrieval_hybrid_enabled` vale False. Y aunque corriera, por diseño reordena lo que el
  vector ya admitió, no admite nada (`evidence_retrieval.retrieve_evidence`, «reorder,
  cannot admit»). Para P1 a P4, con cero supervivientes, añadir términos a la búsqueda por
  texto no rescataría nada. El arreglo tiene que actuar sobre la consulta vectorial.

## Pregunta por pregunta: ¿están el tema y las palabras en el corpus?

| # | Fuentes del tema | ¿Su palabra está en el fragmento? | Causa probable |
|---|---|---|---|
| P1 | «Cómo saber si su bebé está estreñido o hace popó lo suficiente» (AAP), «Constipation in children» (NHS), «Las cacas del recién nacido sano» (AEPap) | Sí: «Tema: cuántas veces hace caca un bebé con pecho» | Frase corta frente a un fragmento largo que se nombra por «estreñimiento» |
| P2 | «Nappy rash» (NHS), «Cuidados del área del pañal» (AEPap) | Sí: NHS dice «culito»; los dos dicen «dermatitis del pañal» | Ella no nombra la dermatitis |
| P3 | «Síndrome boca mano pie» (AEPap), «Enfermedad de manos, pies y boca» (AAP), «Hand, foot and mouth disease» (NHS) | No: dicen ampollas, llagas, erupción; nunca «granitos» | Vocabulario distinto y sin el nombre de la enfermedad |
| P4 | «Conjuntivitis» (AEPap), «Obstrucción del conducto lagrimal», «Lagrimeo en el lactante» (AEPap), «Conjunctivitis» (NHS) | Sí: «legañas» aparece en Conjuntivitis y Lagrimal | Ella no nombra la conjuntivitis |
| P5 | «Cuidados del cordón umbilical» (AEPap), «Cuidado del cordón umbilical en recién nacidos» (AAP), «Síntomas del cordón umbilical» (AAP) | Sí, ya usa «cordón umbilical» | No es vocabulario: la recuperación no vino vacía (kind `answer`) y el modelo rechazó. Fragmento lateral o el modelo; medir |
| P6 | «WHO Motor Development Study» (Tema: a qué edad se sientan, gatean...), «Bebé de 8-12 meses» (EnFamilia) | Sí: «gatear», «gatean», «gateo» | No es vocabulario: orden, margen o el modelo; medir |
| P7 | «Laringitis aguda» (EnFamilia), «Laringitis» (AEPap), «Laringitis, información para padres» (SEUP), «Croup» (NHS) | Casi: «perro» y «perruna» están, pero el fragmento se nombra por «laringitis» y «crup» | Ella no nombra la laringitis |

Lo que se ve: en P1, P2 y P4 la palabra de la madre ya está en el fragmento y aun así no
pasa el corte. Cada fragmento empieza «Título (organización). Tema: <nombre clínico>.
Hallazgo: ...», y la hipótesis es que su embedding lo domina el nombre clínico, que la
pregunta coloquial no trae. No es universal («costras amarillas en la cabeza» y «está un
poco amarillo» sí encontraron costra láctea e ictericia), por eso hay que medir antes de
encender nada.

## Arreglo

`apps/api/adelia/agent/lay_terms.py`: un léxico determinista (expresiones regulares sobre
el texto sin tildes ni mayúsculas) de palabras de madre a los términos que usa el corpus,
20 entradas: estreñimiento, deposiciones, dermatitis del pañal, mano-pie-boca, exantema,
conjuntivitis, lagrimeo, mocos, crup, hernia umbilical, cordón umbilical, regurgitación,
dentición, otitis, estrabismo, plagiocefalia, costra láctea, infección de orina, hernia
inguinal y dermatitis atópica. Patrones en es y, para cuando la traducción falla, en fr y en.

Con `lay_query_expansion` encendido, el nodo `retrieve` (demo) y `retrieve_for_account`
(chat y agente) embeben, en la misma llamada, su frase y su frase más los términos en una
segunda línea. Cada una se busca con los mismos cortes; `merge_by_best_distance` se queda
con la mejor distancia de cada fragmento, ancla el margen a la mejor de las dos y deja una
cita por fuente. Consecuencias:

- no se mueve ningún umbral y no puede salir nada por encima del 0,19;
- lo que encontraba su frase solo se pierde si la búsqueda ampliada encuentra algo bastante
  más cerca y el margen deja fuera lo lejano (lo que el margen hace hoy), o si trae cuatro
  fuentes mejores y la de antes queda quinta;
- otras madres (`experience`) se siguen buscando solo con su frase;
- en el chat el léxico lee el mismo texto que se embebe para el corpus, que incluye la cola
  de los dos últimos turnos; el camino temporal (curvas de laboratorio) no cambia;
- apagado, no se lee el léxico y las llamadas son las de antes (tests en
  `test_agent_graph.py` y `test_chat_orchestrator.py`);
- con la búsqueda híbrida también encendida, la fusión ordena por distancia y pierde el
  orden fusionado; hoy las dos están apagadas.

Descartado: bajar el corte (el grupo B tiene preguntas que deben rechazarse a 0,13),
reescribir la pregunta con un modelo (no determinista, más gasto, otra llamada con datos de
salud) y ampliar el corpus (los temas ya están).

Reglas que fijan los tests (`tests/test_lay_terms.py`): cada término existe en el corpus
pediátrico; sin falsos amigos (cacahuete no es caca, el perro del vecino no es tos de perro,
caca roja en el pañal no es dermatitis, ombligo salido es hernia y no cordón, sacarse leche
no es regurgitar, cepillar los dientes no es dentición, labios de la vulva pegados no es
conjuntivitis); y ninguna pregunta del grupo B recibe términos.

## Grupo B del golden, una por una

| B | Pregunta (resumen) | Términos | Por qué |
|---|---|---|---|
| B1 | colegio bilingüe | ninguno | |
| B2 | ¿es normal que no gatee a los 9 meses? | ninguno | Por esta no hay entrada de gateo (ver abajo) |
| B3 | precio de guardería | ninguno | |
| B4 | horóscopo | ninguno | |
| B6 | dosis de cetirizina | ninguno | Alergia no tiene entrada |
| B7 | 13 años, regla e hierro | ninguno | Además la para `age_scope` |
| B8 | piel amarilla a los 4 meses | ninguno | Por esta «amarillo» no se traduce a ictericia |
| B9 | verdura y melatonina | ninguno | «Rechaza» no tiene entrada |
| B11 | simeticona para los gases | ninguno | Por esta los gases no se traducen a cólico |
| B12 | sueño a los 7 años | ninguno | |
| B13 | 10 ans, diarrhée | ninguno | Por esta no hay entradas francesas de diarrea |
| B14 | légumes y fluor | ninguno | Por esta «dents» en francés no tiene entrada |
| B15 | oreiller a los 3 años | ninguno | |
| B16 | labios de la vulva pegados | ninguno | «Pegados» solo cuenta junto a «ojo» |
| B17 | tongue-tie | ninguno | |

Como ninguna B recibe términos, con el ajuste encendido cada B hace exactamente la misma
búsqueda que hoy.

**Gateo y B2.** La pista pedía «gatear > gateo, desarrollo motor». No se puso: los fragmentos
ya dicen gatear, gatean y gateo (no hay hueco de vocabulario), y B2 es justo una pregunta de
gateo. Cualquier entrada que acercara P6 al corpus acercaría también B2. Además, la razón de
B2 en `golden.py` («hitos motores, fuera del corpus») ya no es cierta: el corpus tiene el
estudio de hitos motores de la OMS y «Bebé de 8-12 meses». Decidir si B2 pasa al grupo A, como
pasaron B5 y B10 el 3 de noviembre, es una decisión del golden y no de esta rama.

## Cómo medir antes de encender

Dentro del contenedor de la API de producción, solo lectura (cada sesión abre con
`SET TRANSACTION READ ONLY`, sin puerta de gasto, enrutado fijo y sin generación):

    python scripts/eval_lay_language.py --json /tmp/lay_language.json

Pasa cada sonda dos veces por el nodo `retrieve` del grafo, con el ajuste apagado y
encendido en memoria: las 7 de arriba, 23 coloquiales (es/fr/en; L22 y L23 son controles sin
palabras de madre) y los grupos A y B del golden. Imprime la mejor distancia sin corte de
cada texto buscado, las fuentes que pasan el corte y los términos añadidos; al final, por
modo, cuántas pasan el corte por grupo, cuántas A traen su fuente esperada y qué B pasa a
estar bajo el corte. Sale con 1 si alguna B entra con el ajuste encendido.

Criterio propuesto para encenderlo: P1 a P4 y P7 pasan el corte con una fuente del tema,
ninguna B nueva bajo el corte, ninguna A pierde su fuente esperada. P5 y P6 no dependen del
léxico.

## Lo que no se ha verificado

- Ninguna distancia: todo lo anterior sobre «por qué no pasa el corte» es hipótesis hasta que
  corra el script.
- Si en producción `retrieval_hybrid_enabled` está encendido (no se leyó el `.env`).
- P5: si el rechazo vino de un fragmento lateral o del modelo con el fragmento bueno delante.
