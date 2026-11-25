# Copias de seguridad

AdelIA guarda la salud de bebés. Una copia que solo vive en el mismo servidor no es una copia:
un disco roto, un robo o un incendio se llevan los datos y la copia a la vez. Por eso hay dos:

| Copia | Dónde | Qué | Cuánto tiempo |
|---|---|---|---|
| Diaria local | volumen `pgbackups` del mismo servidor (`backup` en `infra/docker-compose.prod.yml`) | la base de datos | 14 días |
| Diaria fuera | repositorio **privado** de GitHub, una *release* por copia (`scripts/adelia_backup.py`) | la base de datos y los archivos originales, cifrados | 30 días |

## Qué lleva la copia de fuera

- `db.dump`: `pg_dump --format=custom` de la base entera (cuentas, perfiles, documentos y su
  texto, notas, conversaciones, consentimientos).
- `blobs.tar`: cada archivo original que una madre puede volver a abrir (PDF, fotos, audios que
  ella subió). Lo genera `apps/api/scripts/blob_archive.py` dentro del contenedor de la API, con
  la misma regla que `GET /documents/{id}/file`.
- **No** lleva el audio de las consultas ni las notas de voz de Telegram: la DPIA los borra a las
  48 h de tener el texto (7 días si falla), y una copia de 30 días los guardaría más tiempo del
  que dice la política de privacidad. De cada consulta queda la transcripción, dentro de `db.dump`.
- `manifest.json`: tamaños y sha256 de lo anterior, para comprobar al restaurar.

## Cifrado y clave

Todo se cifra con [age](https://age-encryption.org) en el servidor antes de salir. El servidor
solo tiene la clave **pública**: no puede leer sus propias copias, y GitHub solo guarda texto
cifrado. La clave **privada** está en el Mac de Santiago:

    ~/.config/adelia-backup/age-identity.txt

**Guarda una copia de ese archivo en el gestor de contraseñas.** Si el Mac y el servidor se
pierden a la vez y la clave no está en otro sitio, las copias no sirven para nada.

La clave pública (la que va en el servidor) sale de la privada:

    age-keygen -y ~/.config/adelia-backup/age-identity.txt

## Instalar en el servidor (una vez)

1. `sudo apt install age`
2. Token de GitHub de grano fino: <https://github.com/settings/personal-access-tokens/new>.
   *Repository access*: solo `adelia-backups`. *Permissions*: *Contents*, *Read and write*.
   Caducidad: un año (apúntalo; cuando caduque, las copias fallan y el monitor avisa).
3. El archivo de configuración, solo legible por root:

       sudo install -m 600 -o root -g root /opt/adelia/infra/backup/adelia-backup.env.example /etc/adelia-backup.env
       sudo nano /etc/adelia-backup.env    # repo, clave pública y token

4. Desplegar con `scripts/deploy-prod.sh`: así el servidor tiene `scripts/adelia_backup.py` y la
   imagen de la API tiene `scripts/blob_archive.py`.
5. El temporizador (cada día a las 03:30):

       sudo cp /opt/adelia/infra/backup/adelia-backup.service /opt/adelia/infra/backup/adelia-backup.timer /etc/systemd/system/
       sudo systemctl daemon-reload
       sudo systemctl enable --now adelia-backup.timer

6. La primera copia, ya, y su resultado:

       sudo systemctl start adelia-backup.service
       journalctl -u adelia-backup -n 20

## Comprobar que se puede restaurar (desde el Mac)

Una copia que nadie ha restaurado es una suposición. El simulacro baja la última copia, comprueba
cada sha256, la descifra, la restaura en una base temporal del Postgres local
(`pnpm dev:infra`), comprueba que cada original que la base cita está en la copia y borra la
base temporal:

    ADELIA_BACKUP_REPO=santiagopatinoserna/adelia-backups python3 scripts/adelia_backup.py drill

En el Mac no hace falta token: el script usa la sesión de `gh`. Conviene hacerlo una vez al mes
y siempre después de cambiar algo de esto.

Otros comandos: `list` (las copias en GitHub), `check --max-age-hours 30` (lo usa el monitor),
`fetch --out DIR` (bajar y descifrar una sin restaurarla).

## Restaurar de verdad (servidor nuevo)

1. Levantar solo los datos, sin API ni web, para que nadie escriba mientras tanto:

       docker compose -f infra/docker-compose.prod.yml --env-file .env.prod up -d postgres minio minio-create-bucket

2. En una máquina con la clave privada:

       ADELIA_BACKUP_REPO=santiagopatinoserna/adelia-backups python3 scripts/adelia_backup.py fetch --out ./restaurar

3. Base de datos (en el servidor nuevo, con `restaurar/` copiado allí):

       docker exec -i infra-postgres-1 sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' < restaurar/db.dump

4. Archivos, con la API ya arrancada (`... up -d api`; al arrancar aplica las migraciones que
   falten):

       docker exec -i infra-api-1 /app/.venv/bin/python scripts/blob_archive.py import < restaurar/blobs.tar

5. Arrancar el resto (`... up -d`) y borrar `restaurar/`: es la base en claro.
6. RGPD: la copia es de una fecha. Si alguien borró su cuenta o un documento después, vuelve a
   estar: hay que volver a borrarlo antes de abrir el servicio.

## Vigilancia

`scripts/monitor-adelia.sh` (el monitor del Mac) comprueba una vez por hora que la última copia de
GitHub tiene menos de 30 h y avisa por Telegram una vez cuando no, y otra cuando vuelve a haberla.
Necesita `ADELIA_BACKUP_REPO` y `gh` en el PATH del plist (`scripts/com.godi.adelia-monitor.plist`).
