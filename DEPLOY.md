# Desplegar AdelIA en producción (VPS + Docker, ~15 min)

Esta guía despliega **todo** AdelIA (Postgres + MinIO + API + web + backups
automáticos) con el `infra/docker-compose.prod.yml` ya verificado, detrás de
HTTPS automático con Caddy.

**Recomendado para datos médicos**: un VPS propio en la UE (control total de
los datos, coste fijo y predecible) — p. ej. **Hetzner Cloud CX22** (~4 €/mes,
Alemania/Finlandia) o DigitalOcean Frankfurt. Resend ya envía desde la región
EU (Ireland), así que todo queda en Europa.

> Alternativa sin servidor: Railway/Render (conectas el repo de GitHub). Más
> rápido de arrancar pero hay que partir el compose en servicios gestionados y
> el coste sube con el uso. Para validar con tus primeros usuarios, el VPS con
> el compose tal cual es menos trabajo (ya está hecho y probado).

## 0. Prerrequisitos

- Un VPS Ubuntu 24.04 con IP pública.
- El dominio: la web irá en `https://adelia.godi.ai` (coexiste con el email de
  Resend — son registros DNS distintos). El DNS está en Cloudflare.

## 1. Apuntar el dominio (Cloudflare, 2 min)

En Cloudflare → `godi.ai` → DNS → Records, añade un registro **A**:

| Type | Name           | Content        | Proxy        |
|------|----------------|----------------|--------------|
| A    | `adelia`       | `<IP del VPS>` | DNS only (gris) |

(Ponlo en gris primero para que Caddy emita el certificado TLS; luego puedes
proxearlo si quieres el CDN/WAF de Cloudflare.)

## 2. Preparar el servidor

```bash
ssh root@<IP-del-VPS>
apt update && apt install -y docker.io docker-compose-plugin git
git clone https://github.com/santiagopatinoserna/AdelIA.git
cd AdelIA
```

## 3. Crear el archivo de secretos `.env.prod`

```bash
cp .env.prod.example .env.prod
nano .env.prod
```

Rellena (los valores generados te los paso por chat; las keys de servicio son
tuyas):

```ini
POSTGRES_PASSWORD=<generado>
S3_ACCESS_KEY=adelia
S3_SECRET_KEY=<generado>
S3_BUCKET=adelia
AUTH_SECRET=<generado — el MISMO que ve la web y la API>
MISTRAL_API_KEY=<tu key de Mistral, con billing activo>
OPENAI_API_KEY=            # opcional (transcripción de audio)
RESEND_API_KEY=<tu key 'adelia' de Resend: re_...>
ADELIA_APP_URL=https://adelia.godi.ai
NEXT_PUBLIC_API_URL=https://adelia.godi.ai/api
BACKUP_INTERVAL_SECONDS=86400
BACKUP_RETENTION_DAYS=14
```

## 4. TLS automático con Caddy

Crea `Caddyfile`:

```
adelia.godi.ai {
    # API under /api (strip the prefix) — the web's browser proxy + public PDFs
    handle /api/* {
        uri strip_prefix /api
        reverse_proxy api:8000
    }
    # Public share links are served by the API at /s/{token} (no /api prefix)
    handle /s/* {
        reverse_proxy api:8000
    }
    # Everything else is the Next.js web app
    handle {
        reverse_proxy web:3000
    }
}
```

> The `/s/*` route matters: `share_url` is `https://adelia.godi.ai/s/{token}`
> and that HTML/PDF is served by the API, not the web — without this rule the
> public share links 404.

Y un override `docker-compose.caddy.yml`:

```yaml
services:
  caddy:
    image: caddy:2
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
    depends_on:
      - web
      - api
volumes:
  caddy_data:
```

> Con Caddy delante, NO publiques los puertos 3000/8000 al exterior: quita los
> bloques `ports:` de `web` y `api` en el compose (o déjalos en `127.0.0.1:`).

## 5. Levantar

```bash
docker compose -f infra/docker-compose.prod.yml -f docker-compose.caddy.yml \
  --env-file .env.prod up -d --build
```

La API corre `alembic upgrade head` al arrancar (crea el esquema). Caddy emite
el certificado TLS solo en el primer arranque.

## 6. Verificar

```bash
curl -fsS https://adelia.godi.ai/api/health     # {"status":"ok",...}
```

Abre `https://adelia.godi.ai`, mete **tu email real**, y debe llegarte el magic
link desde `noreply@adelia.godi.ai`. Inicia sesión → sube un PDF → genera un
briefing. Eres el primer usuario real.

## Desplegar en el servidor de casa: `scripts/deploy-prod.sh`

El servidor doméstico no se despliega con `git pull`, sino con
`./scripts/deploy-prod.sh`, que descubre la IP (DHCP), hace `rsync` del
**árbol de trabajo** y reconstruye los contenedores.

Como lo que viaja es el árbol de trabajo y no un commit, el script se niega a
desplegar si el árbol no es exactamente `origin/main`:

- `git status --porcelain` tiene que estar vacío, y
- `HEAD` tiene que ser el mismo commit que `origin/main` (hace `git fetch
  origin main` antes de comparar; si el fetch falla, avisa y compara contra la
  última copia local de la referencia).

Si alguna de las dos cosas falla, aborta **antes** de tocar el servidor y dice
qué ficheros están sucios o qué dos sha no coinciden. El motivo: sin esta
puerta, un despliegue publica código que no existe en ninguna rama, que nadie
ha revisado y que ninguna ejecución de CI ha probado.

```bash
# Camino normal: commitea, empuja, despliega.
git add -A && git commit -m "..." && git push origin main
./scripts/deploy-prod.sh              # api + web
./scripts/deploy-prod.sh api          # solo api

# Solo para un incendio: salta la puerta.
./scripts/deploy-prod.sh --allow-dirty
```

`--allow-dirty` imprime en cada línea de aviso qué se está saltando (cuántos
ficheros sucios, qué sha frente a qué sha). Después de usarlo, apunta qué
desplegaste y empuja el commit en cuanto se apague el fuego: el servidor queda
con código que no está en ninguna rama.

`--discover-only` no pasa por la puerta, porque no despliega nada: solo
imprime la IP del servidor.

## Operación

- **Logs**: `docker compose -f infra/docker-compose.prod.yml logs -f api`
- **Backups**: dumps cada 24 h en el volumen `pgbackups` (restore en el README).
  Los blobs (PDFs originales) están en `miniodata` — snapshot del volumen aparte.
- **Actualizar**: `git pull && docker compose ... up -d --build`
