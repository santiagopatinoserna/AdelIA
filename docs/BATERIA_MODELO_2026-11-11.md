# Batería de conversación con el modelo real (11-nov-2026): revisión

Fuente: `~/dev/adelia-design/shots/battery/battery-20261111-0115.json` (producción, invitada QA,
tope 2 $). 57 de 110 turnos antes del tope: 41 cumplen, 16 no. Mediana 101,5 palabras; primera
palabra en 7,0 s de mediana y 20,2 s de p95; 1,93 $.

Sin modelo, con la decisión del clasificador grabada, la batería daba 95/95 (hoy 110/110 con las
conversaciones de control). La diferencia no era el clasificador: era lo que la batería sin modelo
no imitaba. Su búsqueda falsa siempre encontraba evidencia o nada, nunca *solo su historial*, y su
modelo falso escribía «Texto de prueba [ev_1].», así que el hilo nunca leía una respuesta real.

## 1. Los 16 fallos

Las 11 conversaciones están en `apps/api/scripts/conversation_regressions.json`, sin modelo: la
decisión real del clasificador en cada turno en que se le preguntó (o `down` si cayó al
respaldo), si hubo evidencia e historial, y la respuesta real del modelo como historial del turno
siguiente. Con `main` dan 20/32; con este cambio, 32/32
(`test_the_sixteen_turns_that_failed_with_the_real_model_pass_without_it`).

| Turno | Falla | Causa raíz | Tipo | Arreglo |
|---|---|---|---|---|
| guarderia-real-9nov-1 T2 | doctor | La búsqueda trajo la guía de movimiento (Gezond Leven), sin señales de alarma; el modelo no puede escribir el apartado sin fuente | recuperación | No (ver 1.1) |
| guarderia-real-9nov-1 T3 | doctor, refusal_once | Igual que T2; y repite el párrafo de rechazo entero en una respuesta mixta | recuperación + código | `refused_note` |
| guarderia-botones T3 | refusal_once | Sin evidencia, su historial «fundamentaba» el turno: se pagó al modelo para rechazar otra vez | código | `decide` |
| fiebre-con-cifra-noche T1 | doctor | «tiene 38,5 y esta muy llorona» no encuentra evidencia (no dice fiebre); con historial, el modelo rechaza sin la ronda de preguntas | recuperación + código | `decide` (ronda) |
| fiebre-con-cifra-noche T3 | refusal_once | Párrafo de rechazo entero para «agua fría» en un tema ya rechazado | código | `refused_note` |
| complementaria T3 | refusal_once | Ídem para «la carne, cuánta» | código | `refused_note` |
| no-gatea T1 | doctor | La única fuente (UNICEF) no trae señales de alarma | recuperación | No (ver 1.1) |
| colico-llanto T1 | doctor | «llora muchísimo y encoge las piernas» no encuentra «cólico»; con historial, rechazo sin ronda | recuperación + código | `decide` (ronda) |
| colico-llanto T3 | turn | El clasificador real dijo `correction` para «le puedo dar gotas para los gases», sin ninguna negación: al modelo se le dijo que sus respuestas anteriores estaban mal | clasificador real distinto | `with_kind` |
| colico-llanto T3 | kind | La expectativa `no_evidence` estaba mal: el corpus sí trata las gotas (no han demostrado funcionar) | expectativa | escenario corregido |
| vomitos-y-deshidratacion T2 | turn | «no tiene fiebre» se leyó como corrección porque «fiebre» salía en «Cuándo ir al médico»; sin su plan, el modelo repitió 330 palabras | código (hilo) | `_assumed` |
| piel-granitos T1 | doctor | Sin evidencia y con historial: rechazo sin ronda | recuperación + código | `decide` (ronda) |
| piel-granitos T2, T3 | refusal_once | El rechazo entero otra vez, pagando al modelo (T2 tardó 18,8 s) | código | `decide` |
| dientes T2 | kind | La expectativa `no_evidence` estaba mal: hay alivio sin fármacos (mordedor, masaje) y el modelo se abstiene del analgésico | expectativa | escenario corregido |
| estreñimiento T3 | refusal_once | «y si le doy zumo de pera» sin evidencia en un tema ya rechazado: el modelo repite el rechazo | código | `decide` |
| golpe-en-la-cabeza T1 | doctor | Solo un fragmento de prevención de caídas; la guía de la SEUP no pasa el corte con esas palabras (sí en T2, «chichón») | recuperación | No (ver 1.1) |

Ningún fallo fue el modelo ignorando el contrato: sin señales de alarma en las fuentes, omitir
«Cuándo ir al médico» es lo que el contrato pide. El clasificador real decidió distinto que el
grabado en 1 de los 16 (colico T3).

### Arreglos (código y contrato)

- `agent/graph.decide`: su historial ya no se salta la ronda de preguntas de una preocupación
  observada sin evidencia; y en un tema ya rechazado, sin evidencia y con tarjeta para anotar
  (el agente), el código dice la línea corta y ofrece anotarlo, sin pagar al modelo. El chat no
  cambia. `ask_when_nothing_found` tampoco pregunta ya en un tema rechazado (la ronda va antes del
  rechazo, no después de dos respuestas).
- `agent/conversation`: una negación de algo que el plan solo listaba en «Vigila» o «Cuándo ir al
  médico» es un dato nuevo, no una corrección; una lectura («38,7 °C») cuenta como la fiebre que
  la respuesta daba por hecha. El clasificador ya no puede llamar corrección a un turno sin
  ninguna negación.
- `conversation.refused_note`: en un tema ya rechazado, el modelo recibe la línea corta
  («Sigo sin fuentes sobre esto…») para la parte sin fuente. Contrato: cambia la redacción de la
  abstención, no la abstención; esa parte sigue sin ninguna cifra ni pauta.
- Edad: el modelo que responde recibe «Edad del bebé hoy, según su perfil: N meses». Antes no la
  recibía y la sacaba del historial (ver patrón 1). Es un dato, no una regla nueva; hace que la
  regla que ya había («una fuente de otra edad no respalda nada») pueda cumplirse.
- Contrato del plan: «No olvides» solo lleva del historial lo que tiene que ver con lo que cuenta
  (patrón 2). No quita ninguna señal: ese apartado no lleva señales de alarma.

### 1.1 Lo que no es de código

Tres «doctor» (guardería T2/T3, no-gatea T1, golpe T1) y tres búsquedas vacías (38,5 sin la
palabra fiebre, el cólico descrito, los granitos) son de recuperación. Ya hay arreglos construidos
y apagados, pendientes de medirse en producción: `implicit_subject_expansion` (documenta
exactamente «Tiene 38,3 de fiebre» a 0,197-0,229), `lay_query_expansion` y
`warning_signs_retrieval` («Cuándo ir al médico» desde la biblioteca). No los he encendido: son
recuperación y la orden es no tocar umbrales. Y el corpus de adaptación a la guardería que cita
`conversation._HINT_NURSERY` no apareció en ninguna búsqueda de producción: conviene comprobar que
está cargado.

## 2. Las 57 respuestas, leídas por una madre y una enfermera

Puntuación por turno (1 cumple, 0 no), criterios en este orden: sigue el hilo, pregunta si falta
lo esencial, lo primero es qué hacer, breve, voz de madre, sin repetir ni contradecirse,
seguridad. Los turnos sin texto del modelo (tarjetas, urgencias, anotaciones) cuentan como
cumplidos si hacen lo que deben.

| Criterio | Cumplen |
|---|---|
| Sigue el hilo | 57/57 |
| Pregunta si falta lo esencial | 53/57 |
| Lo primero es qué hacer | 41/57 |
| Breve | 36/57 |
| Voz de madre | 37/57 |
| Sin repetir ni contradecirse | 42/57 |
| Seguridad | 43/57 |

20 de 57 turnos perfectos; media 5,4 de 7. Por turno: guarderia-1 `1111111 1100010 1100000`;
guarderia-2 `1111111 1111111 1111111 1100010`; botones `1111111 1101011 1101001`; fiebre-sin-cifra
`1111111 1110110 1110100`; fiebre-noche `1001011 1110110 1110000`; menor-3-meses `1111111 1111111`;
sueño `1101011 1111101 1111101`; tomas `1101011 1111111 1111111`; complementaria
`1111011 1111111 1111001`; palabras `1111111 1100100 1110100`; gatea `1110110 1110111`; cólico
`1001011 1110100 1110110`; vómitos `1110111 1110101 1111111`; diarrea `1100011 1110101`; piel
`1001011 1001001 1101001`; dientes `1110111 1111011 1111111`; estreñimiento
`1110111 1110011 1101001`; vacunas `1111111 1111111`; golpe `1101010 1111111 1111111`;
anotar-fiebre `1111111 1111111 1110110`.

Lo que va bien: las urgencias (4/4, al instante, sin coste), las anotaciones, las preguntas con
botones, las vacunas por herramienta, y ninguna dosis en 57 turnos.

### Patrones, de más a menos grave

1. **La edad sale del historial, no del perfil** (7 turnos; en 4 cambia el consejo). «A su edad
   (ya pasó la revisión de los 4 meses) aún no se esperan palabras» a un niño de 18 meses que no
   dice ninguna (no-dice-palabras T2: a esa edad es un signo de alarma); «Con unos 4 meses… si
   llega a 38,3 llama» a uno de 8 (fiebre-sin-cifra T2) y de 9 y 10 (anotar-fiebre T3,
   fiebre-noche T2); «a su edad (más de 4 meses) suele haber cedido» a uno de 1 mes (cólico T2).
   En la batería se agrava porque la invitada trae el historial de Lucía con 4 meses y la batería
   le cambia la edad, pero en una cuenta real los documentos también envejecen. **Arreglado**: el
   modelo recibe la edad del perfil.
2. **«No olvides» con historial que no viene a cuento**: 18 de 21 planes recuerdan «repetir la
   analítica si sigue cansada o come peor» (fiebre, dientes, gateo, caída, estreñimiento) y 7 las
   regurgitaciones. **Arreglado** en el contrato.
3. **El rechazo, una y otra vez**: 20 de 44 respuestas escritas llevan el párrafo de rechazo, 9
   enteras (un rechazo entero tardó de 2,3 a 18,8 s). **Arreglado**: la ronda primero, la línea
   corta en el código o en el modelo después.
4. **Largo y repetido**: planes de 193 palabras de mediana, 11 de 23 por encima de 200; en un
   seguimiento («y si no le baja», «no tiene fiebre») vuelve el plan entero (75-88 % de las
   mismas viñetas). Parte era la falsa corrección (arreglada); el resto es el contrato del plan en
   cada turno del tema. **No arreglado**: acortar un plan es donde se pierden señales
   (night/brevity perdió una); está detrás de `plan_brevity`, pendiente de medir.
5. **Lo primero no es qué hacer**: la apertura habla de las fuentes («Las fuentes no explican…»,
   3 turnos) o pone el rechazo antes que «Hoy» (16 turnos con Q=0). Mejora con el 3; el resto, con
   `no_unasked_refusals` (apagado, medido el 6-nov).
6. **Sin «Cuándo ir al médico» cuando la fuente no lo trae** (3 planes) y un golpe en la cabeza
   que abre con «puede causar fractura de cráneo» y nada que hacer (golpe T1). Recuperación, ver
   1.1.
7. **Detalles de voz**: el género del bebé cambia entre turnos («Mantenlo» y luego «Mantenla»,
   fiebre-noche); «sumar al menos 30 minutos boca abajo si aún no gatea» a un niño de 14 meses (de
   nuevo la edad).

## 3. Velocidad

Con las 44 respuestas del modelo: **primera palabra = 1,6 s + 8,4 ms por cada token de
pensamiento** (r = 0,97). Mediana de pensamiento: unos 1.460 tokens en un plan (13,1 s hasta la
primera palabra) y 640 en una respuesta corta (6,5 s). Después escribe a unos 2,2 s cada 100
palabras. Todo lo que no es el modelo (enrutado, embedding, dos búsquedas, armar el mensaje) cabe
en esos 1,6 s fijos; un turno sin modelo tarda 0,012 s.

Lo que se ha cambiado, sin cambiar de modelo:

| Etapa | Antes | Ahora | Medido sin modelo |
|---|---|---|---|
| Clasificador y búsqueda (17 de 51 turnos enrutados; 2 llegaron al plazo de 2 s) | en serie | en paralelo: la búsqueda empieza con las reglas abstenidas y se descarta si la decisión pregunta, anota o reescribe la búsqueda | grafo real con latencias simuladas: 1,22 → 0,61 s (0,6 + 0,6), 1,61 → 1,01 s (1,0 + 0,6), 2,61 → 2,01 s (2,0 + 0,6) |
| Su historial y las guías | dos consultas en serie | a la vez (y las búsquedas de evidencia entre sí) | máximo en vez de suma; test que se bloquearía si fueran en serie |
| Rechazos pagados | 9 de 44 turnos pagaban al modelo para rechazar (2,3-18,8 s) | la ronda o la línea corta en código | en las regresiones, 6 de 28 llamadas al modelo desaparecen: 23,9 s de espera real pasan a ~0,01 s |
| La pantalla | «Pensando…» hasta 20 s | «Buscando en las fuentes…» y «He encontrado 3 fuentes. Escribiendo…» (es/en/fr), dos cosas que pasan en el servidor | Playwright en Chrome a 390x844, claro y oscuro |

La batería guarda ahora cuándo empezó la búsqueda y cuándo se llamó al modelo (`stages_s`), así
la próxima tanda da el desglose real por etapa.

### Propuestas que no he aplicado

- **Menos pensamiento en la respuesta corta.** El esfuerzo está fijo en `medium`
  (`_stream_anthropic_tokens`). Con 200 tokens de pensamiento en vez de 640, la fórmula da unos
  3,3 s en vez de 6,5 s en los 12 turnos de forma `question`. Riesgo: obediencia al contrato.
  Medirlo con `--tag` y la batería antes de activarlo.
- **Otro modelo para la respuesta corta**, por coste (tabla del repo, `usage_prices.json`): un
  turno corto mediano (3.700 tokens de entrada, 780 de salida) cuesta 0,030 $ con Opus 5.5,
  0,015 $ con Sonnet 5 y 0,0008 $ con Haiku 5.5. No tengo cifras de velocidad medidas de los otros
  dos con este contrato: la decisión se mide igual, con `--only`/`--tag` sobre los turnos cortos.
- **Caché del prompt de sistema**: 0 tokens leídos de caché en toda la batería; el contrato son
  unos 1.000-1.450 tokens por turno. Ahorra coste en tandas seguidas; en producción, con pocas
  usuarias en 5 minutos, poco.

## 4. Terminar la batería

`scripts/conversation_battery.py` admite ahora:

- `--resume <informe.json>`: con `--with-model`, corre solo los escenarios que el informe anterior
  no corrió enteros y conserva los demás (marcados `carried`); los totales cubren los dos y el
  tope cuenta solo el gasto nuevo. Con el informe del 11-nov son 22 escenarios y **53 turnos**,
  desde `anotar-sueño`; a 0,034 $ por turno, unos 1,8 $.
- `--from <id>`, `--tag <tema>` (repetible) y `--only <id>`, combinables.

```
docker exec -w /app infra-api-1 .venv/bin/python scripts/conversation_battery.py \
    --with-model --budget-usd 2.5 --resume /tmp/battery-20261111-0115.json \
    --out /tmp/battery-2.json
```

Un escenario a medias se repite desde su primer turno: su invitada se borró y sus primeras
respuestas son el historial de las siguientes. Para medir los arreglos de este cambio con el
modelo: `--scenarios scripts/conversation_regressions.json` (32 turnos, ~1,1 $).
