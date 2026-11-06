# La puerta clínica del despliegue (golden set A, B y C)

Desde el 6 de noviembre de 2026 los grupos A (recall de fuentes) y B (rechazos) del golden set
(`adelia/clinical/golden.py`, auditoría 3.1 y 3.2) corren en cada despliegue que toca la API,
en el servidor, con la base de datos y las claves de producción, antes de sustituir el
contenedor que sirve a las madres. Un fallo, o un golden que no pudo correr, para el despliegue
y la versión anterior sigue sirviendo.

## Por qué

`scripts/deploy-prod.sh` ejecutaba el golden en el Mac. Allí no hay base de datos de evidencia
ni clave de modelo, así que A y B se saltaban siempre («la base de datos de evidencia no
responde») y el despliegue seguía con un aviso. El 5 de noviembre se desplegó tres veces así,
mientras otra sesión añadía cientos de fuentes al corpus: justo lo que puede romper A o B.

## Cómo funciona

Tres scripts, uno por máquina:

| Dónde | Script | Qué hace |
|---|---|---|
| Mac | `scripts/deploy-prod.sh` | Grupo C en local (no necesita clave ni base de datos, falla rápido). Tras el rsync, si el despliegue incluye `api`, llama por ssh al gate del servidor y solo con un 0 hace `up -d`. |
| Servidor | `scripts/prod-golden-gate.sh` | Construye la imagen nueva y su etapa `golden`, copia el corpus de producción a una base de datos efímera, ejecuta el golden en un contenedor desechable de la imagen nueva y borra la copia. |
| Contenedor | `apps/api/scripts/golden_gate.sh` | Migra la copia a la cabeza nueva, carga el corpus de la versión nueva como lo haría el arranque y ejecuta `tests/test_rag_golden.py` con `ADELIA_GOLDEN_DEPLOY=1`. |

Orden en el servidor:

1. `docker compose ... build api api-golden`. La etapa `golden` de `apps/api/Dockerfile` es la
   imagen de producción más `tests/` y las herramientas de desarrollo (pytest), sobre las mismas
   capas: se mide el código que va a servir. La última etapa (`runtime`) sigue siendo la imagen
   por defecto, sin tests, para `up -d` y para Fly.
2. Base de datos efímera `adelia_golden_gate` en el mismo Postgres: el esquema entero y datos
   solo de `alembic_version` y de las tablas `evidence*`. Ningún dato de una familia sale de la
   base de datos viva.
3. `docker compose ... run --rm --no-deps -e POSTGRES_DB=adelia_golden_gate api-golden`: mismo
   entorno y misma red que el servicio `api` (overlay `infra/docker-compose.golden.yml`, con
   `extends`), sin puertos publicados y sin tocar postgres ni minio.
4. Se borra la base de datos efímera pase lo que pase (trap EXIT).

## Por qué una copia y no la base de datos viva

- Las migraciones de alembic corren al arrancar el contenedor (`CMD` del Dockerfile). Contra la
  base viva, el golden mediría el código nuevo con el esquema viejo; migrarla antes dejaría a la
  versión anterior sirviendo sobre un esquema para el que no está escrita si luego el golden
  falla. En la copia se migra sin riesgo.
- Las fuentes nuevas del corpus se cargan al arrancar (`load_startup_corpora` en
  `adelia/main.py`). Contra la base viva, el golden mediría el corpus de la versión ANTERIOR,
  que es justo lo que no queremos con el crawler añadiendo fuentes. En la copia se cargan antes
  de medir. Coste: los fragmentos nuevos se embeben dos veces (en la copia y al arrancar).
- El camino de respuesta del golden solo lee, pero la copia hace imposible que un test escriba
  en la base viva. `golden_gate.sh` se niega a migrar una base cuyo nombre no termine en
  `_golden_gate`, y el copiado se niega si el nombre efímero coincide con el vivo.

## Qué cambia en el test con `ADELIA_GOLDEN_DEPLOY=1`

Solo dentro del contenedor del despliegue:

- Si A y B no pueden correr (sin corpus, sin clave, sin grabación), el test falla con «grupos A y
  B NO EJECUTADOS en el despliegue: motivo», en vez de saltarse.
- La generación usa el proveedor configurado en producción (`LLM_PROVIDER`), no el Mistral que
  `conftest.py` fija para la suite, y el modelo de enrutado es el real.

Fuera del despliegue (CI, Mac) todo sigue igual: A y B se saltan con aviso.

En todos los casos las 33 preguntas de A y B corren con concurrencia 4 (`GOLDEN_CONCURRENCY`),
con un techo de 300 s para el test. Medido el 6 de noviembre contra el corpus de desarrollo: 23
llamadas al modelo generativo (17 de A, las 6 de B cercanas que recuperan algo); A6 es una
bandera roja y el resto de B se niega sin modelo. El informe imprime las llamadas y los segundos.

## Códigos de salida

| Código | Significado | Despliegue |
|---|---|---|
| 0 | El golden pasó | `up -d` |
| 1 | Corrió y falló (recall@4, rechazos, huérfanas, citas, banderas rojas) | Para |
| 2 | No pudo correr (imagen, copia, migración, carga del corpus, error de una respuesta, A y B saltados, sin informe) | Para |
| ssh caído | Se trata como 2 | Para |

`golden_gate.sh` distingue 1 de 2 por la línea `"skipped_reason": null,` de
`golden_report.json`, que `tests/test_rag_golden.py` fija con un test.

## Qué se ve en la salida del despliegue

Cada línea del servidor sale con el prefijo `[deploy]   `: el build, `corpus copied: N chunks`,
la migración, el resumen del golden (recall@4, tasa de rechazo, citas huérfanas, llamadas al
modelo y duración, preguntas que fallan), `golden_report.json` entero y
`golden gate: PASSED|FAILED|NOT RUN (duración del gate: Ns, build y copia incluidos)`.

## Excepciones

- `./scripts/deploy-prod.sh web`: no ejecuta A y B (no cambia nada de lo que miden). El grupo C
  sigue corriendo en el Mac.
- `--skip-golden`: salta las dos mitades, con aviso. Solo para un incendio; anota por qué.

## Cómo probarlo sin producción

`apps/api/tests/test_deploy_prod_script.py` ejecuta los tres scripts con `ssh`, `docker` y el
venv falsos en el PATH: el gate va antes de `up -d`, un fallo no llama a `up -d` y sale distinto
de cero, «no ejecutado» también para, `--skip-golden` sigue funcionando y un despliegue solo de
web no ejecuta A y B.
