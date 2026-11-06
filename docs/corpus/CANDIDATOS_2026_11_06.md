# Fuentes candidatas del 6 de noviembre de 2026

Seis investigadores de Claude Code reunieron 787 fuentes y 2.062 fragmentos en
`~/dev/adelia-night/research/corpus-*` (gaps 76, it-pt-mundo 191, de-nl-nordic 147, en 104,
es 109, fr 160). Aquí quedan integradas como **candidatas**: 455 fuentes y 1.198 fragmentos en
12 ficheros, uno por dominio de `enrichment/data/`, en
`apps/api/adelia/enrichment/candidates/lote_2026_11_06/`. El arranque no lee esa carpeta: nada
de esto llega a producción hasta que el golden lo mida y alguien mueva un fichero.

AdelIA responde con fuente o se abstiene, y una fuente fuera de tema o una cifra mal traducida
en una urgencia es un riesgo para un bebé. Por eso se perdió más de lo que se ganó en volumen:
de 787 fuentes entran 455.

| paso | fuentes que salen | quedan |
|---|---|---|
| lotes de los investigadores | | 787 |
| términos de uso que prohíben adaptar, traducir o el uso comercial | 265 | 522 |
| duplicadas entre lotes (con data/: ninguna) | 10 | 512 |
| calendarios y programas de vacunación de otros países | 26 | 486 |
| revisión literal y de país: fuente entera de otro sistema de salud | 11 | 475 |
| se quedan con menos de 2 fragmentos válidos | 20 | **455** |

## 1. Cómo se hizo

1. **Unión y duplicados.** Contra `data/` (434 fuentes) y entre lotes: misma URL (sin esquema,
   `www` ni barra final), mismo título exacto, y misma organización con el mismo título sin el
   paréntesis final. Con `data/` no coincidió ninguna; entre lotes, 10 (se quedó la copia de
   corpus-gaps, escrita para esas preguntas).
2. **Términos de uso** (apartado 3): fuera todo lo que prohíbe adaptar o traducir o limita el
   uso a fines personales o no comerciales. AdelIA es de pago.
3. **Otro país**: fuera los calendarios y programas de vacunación que no son de España o
   Francia. El resto, en la revisión (paso 5).
4. **Descarga literal.** Para las 367 fuentes con algún fragmento urgente (alarmas,
   urgencias, fiebre, respiración, convulsiones, deshidratación, ictericia, sepsis,
   atragantamiento, anafilaxia, reanimación), la página se bajó con curl, una petición cada
   3 s por servidor, mirando antes `robots.txt`, y se sacó su texto (lxml para HTML, `pdftotext
   -layout` para PDF). 350 bajaron a la primera; las 14 de sip.it cortan la conexión a un
   agente que se identifica como robot y no se forzó con otro; las de SENEP y SENeo, igual, y se
   usó el `pdftotext` que el investigador de corpus-es había sacado del mismo PDF.
5. **Revisión literal y de país**, en 45 lotes de 11 fuentes, por subagentes con las
   instrucciones del verificador y el texto local (nunca WebFetch): cada cifra, edad, duración,
   «y»/«o» entre signos y nivel de urgencia de cada fragmento urgente contra el texto literal,
   con la frase exacta que lo prueba; y en todos los fragmentos, teléfonos y servicios de otro
   sistema de salud reescritos en palabras con el nivel de la fuente. Un programa comprobó
   después que cada cita aparece tal cual en el fichero descargado.
6. **Confirmación con el subagente verificador.** Cada fragmento urgente que la revisión
   corrigió, y cada uno con una cifra que el programa no encontró en la página, pasó otra vez
   por el verificador, con su texto original, el corregido y el extracto literal.
7. **Reglas del repositorio** (`tests/evidence_corpus_checks.py`, `test_evidence_files.py`,
   `golden.contains_dosage`, los controles de medicamentos): siete ediciones a mano y
   un cambio de dominio (apartado 6), y el reparto por dominio.

Herramientas y ficheros intermedios: `/tmp/cc-corpus-work/` (fuera del repositorio y temporal:
scripts en `tools/`, páginas descargadas en `pages/`, veredictos en `verdicts/` y `confirm/`).
Lo que hay que conservar de ellos está aquí y en los tests: las reglas de términos de uso
(apartado 3), el vocabulario de temas por dominio (fijado en
`tests/test_evidence_candidates_2026_11.py`) y las cifras.

## 2. Reverificación literal: cifras

| | fragmentos |
|---|---|
| urgentes revisados contra el texto literal | 686 |
| urgentes que coincidían | 456 |
| urgentes corregidos | 198 |
| urgentes descartados por no tener apoyo en la página | 5 |
| urgentes sin texto literal (página bloqueada o sin el texto), descartados | 27 |
| no urgentes, solo revisión de país: corregidos / descartados | 66 / 24 |
| citas literales copiadas por la revisión | 3.909 |
| citas encontradas tal cual en el texto descargado | 3.909 |

El verificador confirmó 219 fragmentos (198 corregidos y 21 con alguna cifra que el programa no
halló): 165 tal cual y 54 con una segunda corrección suya; ninguno descartado.

En los 647 fragmentos urgentes que quedan, el programa buscó cada cifra en el texto de su página
(con coma o punto decimal, o escrita con letras en los idiomas europeos del lote): 1.762 cifras, 1.730 halladas.
Las 32 restantes: 14 son el 112 que sustituye al 999, 911, 000 o 144 de la página, y las otras
18 son cifras que la página escribe de otra forma: con letras («sixty», «vinte e oito», «dos
kilos y medio», árabe), en otra unidad («2.500 g», «500ml» por 0,5 litros, «3pm» por las 15
horas) o con el calendario japonés (令和) y «9割» por 90 %; las 18 se comprobaron a mano en el
texto descargado y pasaron por el verificador.

Lo que más se corrigió, por este orden: un «o» donde la página dice «y» (o al revés) entre
signos de urgencia; un nivel de urgencia suavizado («consulta» donde la página dice
emergencias, «en el día» donde dice ya); una frase que la página no dice; una edad aplicada a
otra cosa («bebé» donde la página habla del recién nacido). Ejemplos que importaban:

- Helsenorge, fiebre: las manchas que no desaparecen al presionar pedían médico solo con
  somnolencia, vómitos «o» rigidez de nuca; la página pide médico ya por las manchas solas.
- Sundhed.dk, fiebre: el fragmento no decía «urgente» para la fiebre en menores de 3 meses.
- Kind en Gezin, convulsión febril: médico solo tras la primera; la página, ante cualquiera.
- NHS, accidentes: faltaba «si se sospecha que ha tragado una pila de botón», que obliga igual a
  ir a urgencias; y en cortes, «si el sangrado es grave, llama a emergencias».
- Comunidad de Madrid, golpe en la cabeza: subía el umbral de ir al hospital.
- Bambino Gesù, fiebre del recién nacido: «bebé» extendía a 0-24 meses el envío a urgencias.
- ameli, regurgitaciones: «malestar» traducía «malaise» (episodio en que se pone azul o pálido).

## 3. Términos de uso

Regla aplicada, la misma para todas: **fuera** si los términos (los que anotó cada `report.md`
o, donde dudaban, los leídos literalmente) llevan licencia NC o ND, limitan el uso a fines
personales, privados, educativos o no comerciales, o piden permiso para adaptar, traducir o
para el uso comercial. **Dentro**, con la advertencia de abajo, si solo reservan los derechos o
piden permiso para reproducir el texto: AdelIA no lo reproduce, lo resume en español con
título, organización y enlace, como las 434 fuentes de `data/`.

Leídos literalmente el 2026-11-06 porque los informes no coincidían:
- **Canadian Paediatric Society** (65 fuentes en en y fr): «You may not change or adapt the
  content in any way without the written consent», uso comercial con permiso, y «does not allow
  our material to be posted on other websites» (Copyright Policy de Caring for Kids, abril de
  2020).
- **Naître et grandir** (42): uso solo no comercial y el contenido «ne peut être modifié,
  adapté, résumé ou transformé».
- **gov.br** (Ministério da Saúde de Brasil): todo el portal está bajo «Creative Commons
  Atribuição-SemDerivações 3.0».

Quedan dentro con derechos reservados o sin cláusula localizada (conviene que alguien con
criterio legal lo revise antes de vender): NHS (OGL v3.0, permite uso comercial), HSE
(reutilización libre citando), CDC/NIAID/NIMH (dominio público), bfu (uso con cita), BfR y
EAACI (CC BY 4.0), 1177 (permite extractos citando), AAP, ameli, ONE, HUG, SEICAP, SEPEAP,
SEGHNP, Comunidad de Madrid (reutilización citando), MinSalud Colombia, IMSS, SBP, SIP,
Bambino Gesù, SPP, ISS, Kind en Gezin, Helsenorge, sundhed.dk y el resto de la tabla de
organizaciones.

**Aviso sobre el corpus que ya está en producción** (no se ha tocado, no era la tarea): con esta
misma regla, `data/` tiene 107 fuentes de AEPap / Familia y Salud (CC BY-NC-ND 3.0), 13 de
mpedia.fr (sus condiciones prohíben extraer contenido y la minería de textos, también para IA),
3 de Santé publique France (sin uso comercial), 2 de UNICEF (uso personal y educativo) y 1 de la
Canadian Paediatric Society. Es una decisión de Santiago.

## 4. Lo que solo vale en otro país

- Fuera, enteras: 26 calendarios o programas de vacunación (Alemania, Suiza, Países Bajos,
  Flandes, Dinamarca, Suecia, Noruega, Finlandia, Italia, Portugal, Brasil, Japón, Bélgica) y,
  en la revisión, 11 páginas que solo describen un programa o servicio de otro país (cribados
  neonatales neerlandés, flamenco y portugués; revisiones del niño sano británica, polaca y
  noruega; cribado visual belga; la tabla británica de exclusión de guarderías de la UKHSA,
  porque para Francia está la del HCSP; una página del Eltern-Kind-Pass austriaco).
- Reescritos: los teléfonos de emergencias de otro país (999, 911, 000, 144, 113, 192, el 112
  «de Suecia») pasan a «llama a emergencias», o a «emergencias (112)» cuando el revisor lo dejó
  así, que vale en España y Francia; las líneas y servicios de otro sistema (NHS 111, 1177,
  SNS 24, Healthline, Info-Santé, legevakt, helsestasjon, BVC, consultatiebureau, health
  visitor, GP, U1-U9) pasan a su equivalente en palabras con el mismo nivel («pide consejo
  médico urgente el mismo día», «su pediatra», «la enfermera de pediatría», «las revisiones del
  niño sano»). Se quitaron también normas, leyes y prestaciones de otro país (ley laboral
  brasileña, norma suiza de sillas, sello británico de huevos que permite darlos crudos,
  vitamina D hasta los 4 años de Países Bajos, leche desnatada desde el año en Finlandia).
- Se quedan: 112, 061, el Instituto Nacional de Toxicología y las líneas autonómicas con su
  comunidad nombrada (España), y 15, 18, 112, 114 y los centros antiveneno (Francia).
- El test nuevo `check_no_foreign_service` lo fija sobre lo que el fragmento dice después de
  «Tema:». La atribución inicial nombra al editor («1177 Vårdguiden», «SNS 24») como cualquier
  otra fuente, y eso no es una instrucción de llamar.

## 5. Formato: idioma, licencia y temas

- **Idioma del original.** `language` sigue siendo `es`, porque es el idioma del fragmento: el
  cargador lo copia a `evidence_chunks.language`, que elige la configuración de búsqueda léxica
  (migración 0021), y un resumen en español guardado como `en` se buscaría con raíces inglesas.
  El idioma de la página va en un campo nuevo, `original_language` (ISO 639-1), que el cargador
  ignora como ya ignora `topics` y `undated_reason`: sin cambio de esquema ni migración. Si algún
  día hace falta en la base, es una columna y una migración aparte.
- **`public_domain`.** `license` es `fair_use_snippet` en todas, como en `data/`: describe cómo
  usamos la página (paráfrasis breve citada), que es lo que guardamos. Las 17 páginas que sí son
  de dominio público (CDC 14, NICHD, NIAID, NIMH) lo conservan en `original_license: "public_domain"`.
- **Temas.** Los 219 temas de los investigadores se redujeron a un vocabulario por dominio
  (fijado por dominio en el test): sinónimos unidos (`lactancia_materna` en
  `lactancia`, `cacahuete` y `huevo` en `alergenos`, `vrs` en `bronquiolitis`...), etiquetas que
  solo nombraban una organización (`oms`, `francia`) fuera, y los temas nuevos dentro del dominio
  que les toca. Temas que no existían en `data/` (21): lactancia_tecnica,
  problemas_lactancia, extraccion_conservacion_leche, destete, biberon_formula, bebidas,
  suplementos, seguridad_alimentaria, lenguaje, vacunas, bano_higiene, molusco_contagioso,
  reflujo_regurgitacion, prematuros, ortopedia, espasmo_del_sollozo, pendientes_perforacion,
  puerperio, primeros_auxilios, rcp_lactante y exclusion_guarderia. Los dominios sin temas en
  `data/` (alimentación, guardería, reflujo, urgencias) los estrenan aquí. Cada fuente va al dominio
  que reúne más de sus temas; `signos_alarma` y `cuando_consultar` valen en todos.
- **Ficheros y tests.** `tests/test_evidence_candidates_2026_11.py` pasa a cada fichero las
  mismas reglas que a los de `data/` y tres nuevas: idioma original aparte, ningún servicio de
  otro sistema de salud y ninguna página repetida bajo otra URL. Fija el número de fuentes y los
  temas de cada dominio. Los ficheros viven en una subcarpeta propia porque
  `tests/test_harvest_europepmc.py` exige a todo `candidates/*.json` las reglas de los resúmenes
  de Europe PMC (licencia CC BY, inglés). Pasar uno a producción es un `git mv`:
  `adelia/enrichment/candidates/lote_2026_11_06/<dominio>.json` a
  `adelia/enrichment/data/evidence_<dominio>_2026_11.json`. El test lo sigue a `data/`, y allí
  empiezan a leerlo `test_evidence_files.py` y el resto. Comprobado moviendo los 12 a la vez:
  630 tests de corpus en verde.
- **Tamaño.** `check_size` (30 a 40 fuentes) es la regla de un dominio nuevo por rama; aquí hay
  un fichero por dominio, como se pidió, de 1 a 120 fuentes, y el test fija el número medido.

## 6. Ediciones a mano para las reglas del repositorio

- `golden.contains_dosage` marcaba como dosis «unas cucharadas de puré», «una cucharadita de
  aceite», «una cucharita ayuda si le cuesta beber» y «el protector se aplica... cada 2 horas»:
  pasan a «un poco de puré», «un poco de aceite», «darle el líquido con cuchara» y «se vuelve a
  poner pasadas 2 horas».
- Dos frases nombraban el antibiótico fuera de una advertencia (CDC, otitis grave; Comité de
  Lactancia de la AEP, mastitis): «las trate enseguida» y «la medicación que indique el médico».
- ONE: «infusiones» solo puede ir en la frase que las desaconseja; la frase dice ahora «no se
  recomiendan, porque refuerzan el gusto por lo dulce», que es lo que da a entender la página.
- SBP, dientes: «pasta de dientes con flúor» es el núcleo del fragmento; la fuente pasa al
  dominio de boca (`caries_fluor`), el único donde el corpus admite la palabra.

## 7. Lo que no se pudo verificar o queda para decidir

- **27 fragmentos urgentes sin texto literal**, descartados: sip.it (23, el servidor corta a los
  robots), el folleto de bronquiolitis de Navarra (3, PDF en imagen) y la lista de signos de
  anafilaxia de Nip allergies in the Bub (1).
- **Fragmentos no urgentes sin descarga** (de 119 fuentes): no se descargaron porque la tarea
  pedía la reverificación literal solo para lo urgente; llevan el veredicto del verificador de
  cada investigador (WebFetch) y la revisión de país.
- **Compresiones en el lactante**: NHS, HSE y SBP enseñan dos dedos; RCUK 2025 y AHA/AAP 2025,
  los dos pulgares abrazando el tórax. Cada fragmento conserva la de su fuente.
- **Diez fuentes anteriores a 2015** (Colombia 2013-2014, SEPEAP 2014, HCSP 2012, DGS 2012,
  APSI 2014, PNSIJ 2013): vigentes según sus investigadores; son las primeras a quitar si se
  aplica el corte de 2015.
- **116 fuentes sin año** (páginas vivas de ONE, Kind en Gezin, HUG...), con `undated_reason`.
- **Dominios pequeños**: guardería 1 fuente, reflujo 2, urgencias 6.
- **Calidad de traducción en árabe, japonés, coreano y polaco**: las cifras y el nivel de
  urgencia están contrastados con el texto literal; el matiz del idioma depende del modelo.
- La medición con el golden (apartado 9).

## 8. Preguntas candidatas del examen (propuesta aparte)

B19 (pendientes), B21 (pechitos hinchados), B24 (molusco) y B27 (bebida de avena) tienen ya
fuente real en estas candidatas:

| pregunta | fuente que la responde | dominio |
|---|---|---|
| B19 | «Ear Piercing Symptoms» (KidsDoc, AAP): esperar a que el niño pueda cuidar la perforación, lo habitual desde los 8 años; también AboutKidsHealth y HealthyChildren | `ojos_oidos_boca_uro_neuro` |
| B21 | «Newborn Appearance Questions» (Seattle Children's): hinchazón por los estrógenos de la madre, gotitas de leche normales, de 2 a 4 semanas, no exprimir | `neonatal` |
| B24 | «Molluscum contagiosum» (NHS), EnFamilia (AEP), HealthyChildren y CDC | `digestivo_piel` |
| B27 | «Cow's Milk and Milk Alternatives» (CDC): bebidas vegetales, avena incluida, sin azúcar y enriquecidas, nunca antes de los 12 meses; HealthyChildren y NHS | `alimentacion_bebes` |

El cambio de B a A no puede aplicarse hoy: `test_every_candidate_source_alternative_names_a_
real_corpus_title` exige que la fuente esperada esté en `data/`, y aquí solo es candidata. Va
como parche aparte, `docs/corpus/golden-B19-B21-B24-B27-a-A.patch`, para aplicar en el mismo
cambio que mueva esos ficheros a `data/` (detalle en el propio parche). No toca `GOLDEN_SET`.

Con el parche aplicado y los 12 ficheros movidos a `data/`, 851 tests de golden, candidatos,
léxico y sujeto implícito pasan; falla solo `test_groups_a_and_b_meet_the_deploy_gate`, el
fallo conocido del entorno local sin clave de Mistral.

Mientras tanto la comparación del gate no se confunde: en la previsualización de producción
esas cuatro B ya no pasaban (tenían tarjetas bajo el corte), así que con las candidatas no
cuentan como B perdidas.

## 9. Medición en el servidor

La puerta sin modelo necesita la clave de Mistral (embeddings), que solo está en el servidor.
Con los ficheros en `/opt/adelia` (los sube el rsync de un despliegue, o copiarlos a mano a la
misma ruta):

```bash
cd /opt/adelia && bash scripts/prod-golden-gate.sh \
  --candidates 'apps/api/adelia/enrichment/candidates/lote_2026_11_06/*.json'
```

Cómo leerlo: «candidatos: APTOS» si ninguna B pasa a llegar al modelo ni a responderse y
recall@4 con candidatos sigue sobre 0,8. Cualquier B en «B que pasan a llegar al modelo» es un
falso positivo nuevo y bloquea el fichero de su dominio. Los 12 ficheros pueden medirse también
de uno en uno cambiando el glob, para saber cuál mueve cada cosa.

## 10. Fuentes y fragmentos por dominio y por idioma original

| dominio | fuentes | fragmentos | ar | da | de | en | es | fi | fr | it | ja | ko | nl | no | pl | pt | sv |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `alimentacion_bebes` | 120 | 318 | 1 |  | 8 | 29 | 36 | 1 | 8 | 12 |  |  | 6 | 3 | 4 | 10 | 2 |
| `desarrollo_0_24m` | 54 | 133 | 1 | 1 |  | 18 | 9 |  | 10 | 8 |  |  | 3 | 1 | 1 | 2 |  |
| `digestivo_piel` | 55 | 143 | 4 | 1 |  | 5 | 14 |  | 5 | 6 |  | 2 | 2 | 1 | 2 | 9 | 4 |
| `guarderia_adaptacion` | 1 | 3 |  |  |  |  |  |  | 1 |  |  |  |  |  |  |  |  |
| `infecciones_fiebre` | 30 | 82 | 1 | 1 | 1 | 9 | 3 | 1 | 3 | 5 |  |  | 2 | 1 |  | 2 | 1 |
| `neonatal` | 35 | 100 | 1 |  | 1 | 3 | 13 |  | 2 | 5 |  |  | 1 | 1 |  | 7 | 1 |
| `ojos_oidos_boca_uro_neuro` | 10 | 23 |  |  |  | 4 | 1 |  |  | 2 |  |  |  |  |  | 3 |  |
| `pediatric_reflux` | 2 | 6 |  |  |  |  |  |  | 2 |  |  |  |  |  |  |  |  |
| `respiratorio_sueno` | 77 | 209 | 2 | 2 | 1 | 9 | 19 |  | 14 | 10 | 2 | 1 | 2 | 2 |  | 10 | 3 |
| `salud_madre_familia` | 18 | 50 |  |  |  | 2 | 5 |  | 2 | 3 |  |  | 2 | 1 |  | 1 | 2 |
| `seguridad` | 47 | 116 | 2 |  | 5 | 5 | 2 |  | 8 | 7 | 1 |  | 6 | 1 | 1 | 9 |  |
| `urgencias_lactante` | 6 | 15 |  |  |  | 5 |  |  |  |  |  |  | 1 |  |  |  |  |
| **total** | 455 | 1198 | 12 | 5 | 16 | 89 | 102 | 2 | 55 | 58 | 3 | 3 | 25 | 11 | 8 | 53 | 13 |

| idioma original | fuentes | fragmentos |
|---|---|---|
| español (`es`) | 102 | 286 |
| inglés (`en`) | 89 | 215 |
| italiano (`it`) | 58 | 134 |
| francés (`fr`) | 55 | 160 |
| portugués (`pt`) | 53 | 153 |
| neerlandés (`nl`) | 25 | 64 |
| alemán (`de`) | 16 | 34 |
| sueco (`sv`) | 13 | 37 |
| árabe (`ar`) | 12 | 32 |
| noruego (`no`) | 11 | 31 |
| polaco (`pl`) | 8 | 21 |
| danés (`da`) | 5 | 12 |
| coreano (`ko`) | 3 | 8 |
| japonés (`ja`) | 3 | 7 |
| finés (`fi`) | 2 | 4 |

## 11. Por organización

| organización | idioma | fuentes |
|---|---|---|
| NHS (National Health Service, Reino Unido) | en | 34 |
| Sociedade Brasileira de Pediatria (SBP) | pt | 29 |
| Ospedale Pediatrico Bambino Gesù | it | 26 |
| ONE (Office de la Naissance et de l'Enfance, Belgique) | fr | 24 |
| Assurance Maladie (ameli.fr) | fr | 17 |
| Health Service Executive (HSE) | en | 15 |
| American Academy of Pediatrics | es | 14 |
| CDC | en | 13 |
| Istituto Superiore di Sanità (ISS), EpiCentro | it | 13 |
| Kind en Gezin (Agentschap Opgroeien) | nl | 13 |
| Ministerio de Salud de Arabia Saudí (MOH) | ar | 12 |
| 1177 Vårdguiden (Inera) | sv | 11 |
| Helsenorge.no (Helsedirektoratet) | no | 10 |
| Hôpitaux universitaires de Genève (HUG) | fr | 10 |
| Sociedade Portuguesa de Pediatria (SPP) | pt | 10 |
| Società Italiana di Pediatria (SIP) | it | 10 |
| Sociedad Argentina de Pediatría (SAP) | es | 9 |
| Asociación Española de Pediatría | es | 8 |
| American Academy of Pediatrics | en | 7 |
| KidsHealth (Paediatric Society of New Zealand) | en | 7 |
| Sociedad Española de Inmunología Clínica, Alergología y Asma Pediátrica (SEICAP) | es | 7 |
| Azienda Ospedaliero Universitaria Meyer IRCCS | it | 6 |
| Consejería de Sanidad de la Comunidad de Madrid | es | 6 |
| Netzwerk Gesund ins Leben (Bundesanstalt für Landwirtschaft und Ernährung, BLE) | de | 6 |
| Beratungsstelle für Unfallverhütung (bfu, Schweiz) | de | 5 |
| Cochrane | es | 5 |
| Ministerio de Salud y Protección Social (Colombia) | es | 5 |
| Ministerio de Sanidad (España) | es | 5 |
| Sociedad Española de Pediatría Extrahospitalaria y Atención Primaria (SEPEAP) | es | 5 |
| Sundhed.dk, Patienthåndbogen | da | 5 |
| Chile Crece Contigo (Gobierno de Chile) | es | 4 |
| Direção-Geral da Saúde (DGS, Portugal) | pt | 4 |
| Ministerio de Salud de la Nación (Argentina) | es | 4 |
| Narodowe Centrum Edukacji Żywieniowej (NCEŻ), Narodowy Instytut Zdrowia Publicznego PZH - PIB | pl | 4 |
| Organización Panamericana de la Salud (OPS) | es | 4 |
| Serviço Nacional de Saúde (SNS 24) | pt | 4 |
| Stichting Voedingscentrum Nederland (Voedingscentrum) | nl | 4 |
| Korean Pediatric Society (대한소아청소년과학회) | ko | 3 |
| VeiligheidNL (kenniscentrum letselpreventie) | nl | 3 |
| Associação para a Promoção da Segurança Infantil (APSI) | pt | 2 |
| Berufsverband der Kinder- und Jugendärzt*innen (BVKJ, Kinder- und Jugendärzte im Netz) | de | 2 |
| Bundesinstitut für Risikobewertung (BfR) | de | 2 |
| Consejería de Sanidad de la Junta de Castilla y León | es | 2 |
| Consumer Affairs Agency (消費者庁, Japón) | ja | 2 |
| GroeiGids (GGD- en CJG-organisaties, Jeugdgezondheidszorg) | nl | 2 |
| Healthdirect Australia | en | 2 |
| Hospital Universitari i Politècnic La Fe (Valencia) | es | 2 |
| Ministerio de Salud de Chile (MINSAL) | es | 2 |
| Ministério da Saúde (Brasil) | pt | 2 |
| National Allergy Council (Nip allergies in the Bub; ASCIA y Allergy & Anaphylaxis Australia) | en | 2 |
| Nederlands Centrum Jeugdgezondheid (NCJ, JGZ-richtlijnen) | nl | 2 |
| Sociedad Española de Gastroenterología, Hepatología y Nutrición Pediátrica (SEGHNP) | es | 2 |
| Terveyskylä.fi (Suomen yliopistosairaalat) | fi | 2 |
| World Health Organization (WHO) | es | 2 |
| Associazione Culturale Pediatri (ACP) | it | 1 |
| British Society for Allergy and Clinical Immunology (BSACI) y British Dietetic Association (BDA) | en | 1 |
| CDC | es | 1 |
| Children and Families Agency (こども家庭庁, Japón) | ja | 1 |
| Cochrane | en | 1 |
| Consejería de Sanidad, Junta de Castilla y León | es | 1 |
| Consellería de Sanidade y Servicio Gallego de Salud (Sergas, Xunta de Galicia) | es | 1 |
| Croix-Rouge française | fr | 1 |
| Departamento de Salud de la Generalitat de Cataluña | es | 1 |
| Departamento de Salud del Gobierno Vasco | es | 1 |
| European Academy of Allergy and Clinical Immunology (EAACI) | en | 1 |
| Federazione Italiana Medici Pediatri (FIMP) | it | 1 |
| Grupo GEIDIS y Fundación IMAS (guía alojada por SENeo) | es | 1 |
| Główny Inspektorat Sanitarny (GIS, Polonia) | pl | 1 |
| Haut Conseil de la santé publique (HCSP) | fr | 1 |
| Haute Autorité de Santé (HAS) | fr | 1 |
| Healthy Eating Research (AND, AAP, AAPD y AHA) | es | 1 |
| Helsedirektoratet | no | 1 |
| Hospital General Universitario Gregorio Marañón (Madrid) | es | 1 |
| Hospital Infantil Universitario Niño Jesús (Madrid) | es | 1 |
| Hospital Universitari Vall d'Hebron | es | 1 |
| Hospital Universitario La Paz (Madrid) | es | 1 |
| Instituto Colombiano de Bienestar Familiar (ICBF) | es | 1 |
| Instituto de Salud Pública y Laboral de Navarra (Gobierno de Navarra) | es | 1 |
| Livsmedelsverket | sv | 1 |
| Luzerner Kantonsspital (LUKS, Kinderspital Zentralschweiz KidZ) | de | 1 |
| Ministerstwo Zdrowia (Polonia) | pl | 1 |
| Ministère de la Santé et des Services sociaux du Québec (MSSS) | fr | 1 |
| NICHD | en | 1 |
| Narodowy Fundusz Zdrowia (NFZ), portal pacjent.gov.pl | pl | 1 |
| National Institute of Allergy and Infectious Diseases (NIAID, NIH) | en | 1 |
| National Institute of Mental Health (NIMH) | es | 1 |
| Osakidetza-Servicio vasco de salud (Osakidetza) | es | 1 |
| Resuscitation Council UK | en | 1 |
| Rikshandboken i barnhälsovård (Inera) | sv | 1 |
| Royal College of Psychiatrists | en | 1 |
| Seattle Children's Hospital | en | 1 |
| Sociedad Española de Neurología Pediátrica (SENEP) | es | 1 |
| Sociedade Portuguesa de Neonatologia (SPN) | pt | 1 |
| Sociedade de Pediatria de São Paulo (SPSP) | pt | 1 |
| Società Italiana di Neonatologia (SIN) | it | 1 |
| Szczepienia.Info, Narodowy Instytut Zdrowia Publicznego PZH - PIB | pl | 1 |
| The Hospital for Sick Children (SickKids, AboutKidsHealth) | en | 1 |
| Vlaams Instituut Gezond Leven vzw | nl | 1 |

## 12. Fuera por términos de uso, por organización

| organización | fuentes | lote | términos |
|---|---|---|---|
| Canadian Paediatric Society | 66 | gaps 1, en 15, fr 50 | Copyright Policy de Caring for Kids (abril de 2020, leída literal el 2026-11-06): «You may not change or adapt the content in any way without the written consent», uso comercial con permiso y «does not allow our material to be posted on other websites» |
| Naître et grandir | 42 | fr 42 | «Reproduction et droits d'auteur» (leída literal el 2026-11-06): solo uso no comercial y el contenido «ne peut être modifié, adapté, résumé ou transformé» |
| RCH Melbourne | 18 | gaps 4, en 14 | términos del RCH, cláusula 5: solo uso personal; republicar o distribuir exige consentimiento escrito (corpus-gaps/report.md) |
| BIÖG kindergesundheit-info.de | 17 | de-nl-nordic 17 | CC BY-NC-ND 3.0 DE en las páginas marcadas; reproducir o reformular exige acuerdo previo con el BIÖG (corpus-de-nl-nordic/report.md §4) |
| Thuisarts.nl (NHG) | 16 | de-nl-nordic 16 | Disclaimer: «gebruiken voor jezelf en je naasten»; en otras webs «niet zomaar», con permiso previo del NHG (parts/terms_D.md) |
| gov.br (Ministério da Saúde) | 14 | it-pt-mundo 14 | pie de todo gov.br (leído literal el 2026-11-06): «Creative Commons Atribuição-SemDerivações 3.0», sin obras derivadas |
| gesundheit.gv.at | 12 | de-nl-nordic 12 | Impressum: cualquier uso, también parcial, «bedarf der vorhergehenden Genehmigung des BMASGPK» (parts/terms_C.md) |
| Sant Joan de Déu | 12 | es 12 | pie de las páginas: CC BY-NC-ND 3.0 España (corpus-es/report.md) |
| Santé publique France | 10 | gaps 3, fr 7 | Mentions légales de SPF: reproducir o traducir solo para investigación o estudio personal, nunca uso comercial; Manger Bouger: extracto corto sin modificar (corpus-fr/report.md, corpus-gaps/report.md) |
| INSPQ | 10 | fr 10 | «Crédits et utilisation»: reproducción solo para estudio privado o investigación; cualquier otro uso requiere autorización del Gobierno de Quebec (corpus-fr/report.md) |
| UNICEF | 9 | it-pt-mundo 4, es 5 | aviso legal de UNICEF: uso personal y educativo, citas mínimas; más requiere permiso escrito (corpus-es/report.md) |
| Secretaría de Salud (México) | 8 | es 8 | condiciones de gob.mx: uso personal y no comercial (corpus-es/report.md) |
| KDCA | 6 | it-pt-mundo 6 | KOGL tipo 4: sin uso comercial ni obras derivadas (corpus-it-pt-mundo/report.md) |
| ASCIA | 5 | gaps 2, en 3 | impresión solo para uso personal y no comercial; prohibido subirlo a otros sitios (corpus-en/report.md, corpus-gaps/report.md) |
| MedlinePlus A.D.A.M. | 4 | gaps 4 | el texto de la enciclopedia es © A.D.A.M. (Ebix): solo uso personal, prohibido duplicarlo; no es dominio público (corpus-gaps/report.md) |
| AEPap / Familia y Salud | 4 | gaps 4 | CC BY-NC-ND 3.0 España: sin uso comercial ni obra derivada (corpus-gaps/report.md) |
| Große schützen Kleine | 4 | de-nl-nordic 4 | descarga solo para uso «persönlich, privat und nicht-kommerziell»; reproducción comercial con autorización escrita (parts/terms_C.md) |
| BVS Ministério da Saúde NC | 3 | it-pt-mundo 3 | la publicación lleva CC BY-NC-SA 4.0 o CC BY-NC-ND 4.0 (sources_meta.json) |
| Nationale Stillkommission | 3 | de-nl-nordic 3 | uso privado, científico y no comercial sin permiso escrito (corpus-de-nl-nordic/report.md) |
| Fiocruz rBLH | 1 | it-pt-mundo 1 | sello by-nc: «para todos os fins não comerciais» (corpus-it-pt-mundo/report.md) |
| Junta de Andalucía | 1 | es 1 | la obra lleva CC BY-NC-ND 4.0 (corpus-es/report.md) |

## 13. Fuera por país (calendarios y programas de vacunación)

| fuente | organización | lote |
|---|---|---|
| ロタウイルスワクチン | Ministry of Health, Labour and Welfare (厚生労働省, Japón) | it-pt-mundo |
| B型肝炎ワクチン | Ministry of Health, Labour and Welfare (厚生労働省, Japón) | it-pt-mundo |
| 子どもの肺炎球菌ワクチン | Ministry of Health, Labour and Welfare (厚生労働省, Japón) | it-pt-mundo |
| 5種混合ワクチン | Ministry of Health, Labour and Welfare (厚生労働省, Japón) | it-pt-mundo |
| Calendário de Vacinação da SBP – Atualização 2026/2027 | Sociedade Brasileira de Pediatria (SBP) | it-pt-mundo |
| Calendário vacinal do bebê prematuro | Sociedade Brasileira de Pediatria (SBP) | it-pt-mundo |
| Calendario vaccinale del Piano nazionale di prevenzione vaccinale 2017-2018 | Istituto Superiore di Sanità (ISS), EpiCentro | it-pt-mundo |
| CALENDARIO VACCINALE PER LA VITA 5° EDIZIONE 2025 Razionale | Board del Calendario Vaccinale per la Vita (SItI, SIP, FIMP, | it-pt-mundo |
| Programa Nacional de Vacinação | Serviço Nacional de Saúde (SNS 24) | it-pt-mundo |
| Empfehlungen der Ständigen Impfkommission beim Robert Koch-Institut 2026 (Epidemiologische | Robert Koch-Institut (RKI), Ständige Impfkommission (STIKO) | de-nl-nordic |
| STIKO: Empfehlung zur Prophylaxe von RSV-Erkrankungen mit monoklonalen Antikörpern bei Neu | Robert Koch-Institut (RKI), Ständige Impfkommission (STIKO) | de-nl-nordic |
| Impfungen für Säuglinge und Kinder (Bundesamt für Gesundheit) | Bundesamt für Gesundheit (BAG, Schweiz) | de-nl-nordic |
| RSV-Impfung: Mein Baby schützen (Inselspital Bern) | Inselspital, Universitätsspital Bern (Kinderklinik) | de-nl-nordic |
| Vaccinatieschema (Rijksvaccinatieprogramma) | Rijksinstituut voor Volksgezondheid en Milieu (RIVM) | de-nl-nordic |
| Prik tegen RS-virus (Rijksvaccinatieprogramma) | Rijksinstituut voor Volksgezondheid en Milieu (RIVM) | de-nl-nordic |
| Rotavirusvaccinatie (Rijksvaccinatieprogramma) | Rijksinstituut voor Volksgezondheid en Milieu (RIVM) | de-nl-nordic |
| DKTP-Hib-HepB-vaccinatie (Rijksvaccinatieprogramma) | Rijksinstituut voor Volksgezondheid en Milieu (RIVM) | de-nl-nordic |
| BMR-vaccinatie (Rijksvaccinatieprogramma) | Rijksinstituut voor Volksgezondheid en Milieu (RIVM) | de-nl-nordic |
| Het basisvaccinatieschema (Kind en Gezin) | Kind en Gezin (Agentschap Opgroeien) | de-nl-nordic |
| Vaccinaties volgens leeftijd (Departement Zorg) | Departement Zorg (Vlaamse overheid) | de-nl-nordic |
| Barnvaccinationsprogrammet (Rikshandboken i barnhälsovård) | Rikshandboken i barnhälsovård (Inera) | de-nl-nordic |
| Barnvaccinationsprogram (Folkhälsomyndigheten) | Folkhälsomyndigheten | de-nl-nordic |
| Finnish national vaccination programme: which vaccines are recommended for different age g | Terveyden ja hyvinvoinnin laitos (THL) | de-nl-nordic |
| Når får barnet tilbud om de ulike vaksinene? (Helsenorge) | Folkehelseinstituttet (FHI) | de-nl-nordic |
| Det danske børnevaccinationsprogram (SSI) | Statens Serum Institut (SSI) | de-nl-nordic |
| Vaccination de l'enfant (ONE) | ONE (Office de la Naissance et de l'Enfance, Belgique) | fr |

## 14. Duplicados entre lotes

| fuente | lote | motivo |
|---|---|---|
| Colds, coughs and ear infections in children (NHS) | en | misma URL que la de corpus-gaps («Colds, coughs and ear infections in children (NHS)») |
| Food allergies in babies and young children (NHS) | en | misma URL que la de corpus-gaps («Food allergies in babies and young children (NHS)») |
| Drinks and cups for babies and young children (NHS) | en | misma URL que la de corpus-gaps («Drinks and cups for babies and young children (NHS)») |
| How to stop a child from choking (NHS) | en | misma URL que la de corpus-gaps («How to stop a child from choking (NHS)») |
| Choking Hazards (CDC) | en | misma URL que la de corpus-gaps («Choking Hazards (CDC, Infant and Toddler Nutrition)») |
| La introducción temprana de alimentos ayuda a prevenir la alergia alimentaria | es | misma URL que la de corpus-gaps («La introducción temprana de alimentos ayuda a prevenir la al») |
| Bronchiolite : que faire ? (ameli.fr) | fr | misma URL que la de corpus-gaps («Bronchiolite : que faire ? (ameli.fr)») |
| Rhinopharyngite de l'enfant : que faire et quand consulter ? (ameli.fr) | fr | misma URL que la de corpus-gaps («Rhinopharyngite de l'enfant : que faire et quand consulter ?») |
| Otite moyenne aiguë : que faire et quand consulter ? (ameli.fr) | fr | misma organización y título que https://www.ameli.fr/assure/sante/themes/otite-moyenne-aigue-enfant/bons-reflexes-que-fa |
| Corps étranger inhalé par fausse route (ameli.fr) | fr | misma URL que la de corpus-gaps («Corps étranger inhalé par fausse route (ameli.fr)») |

## 15. Fuentes que salieron en la revisión

| fuente | organización | idioma | motivo |
|---|---|---|---|
| How to recognise an allergic reaction (Nip allergies in the Bub) | National Allergy Council (Nip allergies in th | en | le quedan 1 fragmento(s) válidos |
| Public health exclusion periods in children and young people's settings (GOV.UK, | UK Health Security Agency (UKHSA) | en | tabla de exclusión de guarderías de la UKHSA: norma de salud pública británica; en España y Francia la fijan sus propias autoridades (HCSP para Francia, que sí  |
| Segurança na viagem com crianças | Sociedade Brasileira de Pediatria (SBP) | pt | le quedan 1 fragmento(s) válidos |
| Screening neonatale, una guida per i genitori | Azienda Ospedaliero Universitaria Meyer IRCCS | it | le quedan 1 fragmento(s) válidos |
| Indagine 2025: sicurezza in auto | Istituto Superiore di Sanità (ISS), EpiCentro | it | le quedan 1 fragmento(s) válidos |
| Le 5 cose da sapere sulla bronchiolite | Società Italiana di Pediatria (SIP) | it | le quedan 0 fragmento(s) válidos |
| Pubblicate le nuove Linee Guida italiane per la gestione della bronchiolite | Società Italiana di Pediatria (SIP) | it | le quedan 1 fragmento(s) válidos |
| Le 5 cose da sapere sulle coliche | Società Italiana di Pediatria (SIP) | it | le quedan 1 fragmento(s) válidos |
| Neonati e allattamento sicuro al seno, dai pediatri 5 consigli per le mamme e i  | Società Italiana di Pediatria (SIP) | it | le quedan 1 fragmento(s) válidos |
| 5 cose da chiedersi per sapere quando bisogna portare il bambino in Pronto Socco | Società Italiana di Pediatria (SIP) | it | le quedan 0 fragmento(s) válidos |
| Le 6 cose da sapere sulle convulsioni febbrili | Società Italiana di Pediatria (SIP) | it | le quedan 0 fragmento(s) válidos |
| L’inalazione di corpi estranei in età pediatrica….un’emergenza da prevenire, ric | Società Italiana di Pediatria (SIP) | it | le quedan 0 fragmento(s) válidos |
| Prevenire gli annegamenti, ecco poche e semplici regole da seguire | Società Italiana di Pediatria (SIP) | it | le quedan 0 fragmento(s) válidos |
| Mare e bambini: le regole per un’estate in sicurezza | Società Italiana di Pediatria (SIP) | it | le quedan 1 fragmento(s) válidos |
| Effetti sulla salute dell’allattamento al seno e sua durata | Società Italiana di Pediatria (SIP) | it | le quedan 1 fragmento(s) válidos |
| Botulismo: rischio raro ma serio | Società Italiana di Pediatria (SIP) | it | le quedan 0 fragmento(s) válidos |
| Noworodek i wcześniak | Narodowy Fundusz Zdrowia (NFZ), portal pacjen | pl | revisión: fuente entera fuera |
| Zaprowadź dziecko na bilans zdrowia | Narodowy Fundusz Zdrowia (NFZ), portal pacjen | pl | revisión: fuente entera fuera |
| O que é o Teste do Pezinho? | Instituto Nacional de Saúde Doutor Ricardo Jo | pt | revisión: fuente entera fuera |
| Vorsorgeuntersuchungen für Kinder und Jugendliche (Kinder- und Jugendärzte im Ne | Berufsverband der Kinder- und Jugendärzt*inne | de | le quedan 1 fragmento(s) válidos |
| Neugeborenengelbsucht (Ikterus neonatorum) (Eltern-Kind-Pass) | Eltern-Kind-Pass (elternkindpass.gv.at, BMASG | de | página del Eltern-Kind-Pass austriaco: programa de revisiones de otro país (también en la atribución de cada fragmento) |
| Hielprik (Pre- en neonatale screeningen, PNS) | Rijksinstituut voor Volksgezondheid en Milieu | nl | revisión: fuente entera fuera |
| Gehoortest baby (Pre- en neonatale screeningen, PNS) | Rijksinstituut voor Volksgezondheid en Milieu | nl | revisión: fuente entera fuera |
| Ziek? (Kind en Gezin) | Kind en Gezin (Agentschap Opgroeien) | nl | le quedan 1 fragmento(s) válidos |
| Bloedprik bij pasgeboren baby's (Departement Zorg) | Departement Zorg (Vlaamse overheid) | nl | revisión: fuente entera fuera |
| Helsestasjon for barn 0-5 år (Helsenorge) | Helsenorge.no (Helsedirektoratet) | no | revisión: fuente entera fuera |
| Vitamins for children (NHS) | NHS (National Health Service, Reino Unido) | en | le quedan 1 fragmento(s) válidos |
| Your baby's health and development reviews (NHS) | NHS (National Health Service, Reino Unido) | en | revisión: fuente entera fuera |
| Bronquiolitis aguda. Información para las familias | Servicio Navarro de Salud-Osasunbidea (Gobier | es | le quedan 0 fragmento(s) válidos |
| Tos ferina | Organización Panamericana de la Salud (OPS) | es | le quedan 1 fragmento(s) válidos |
| Dépistage visuel (ONE) | ONE (Office de la Naissance et de l'Enfance,  | fr | revisión: fuente entera fuera |
