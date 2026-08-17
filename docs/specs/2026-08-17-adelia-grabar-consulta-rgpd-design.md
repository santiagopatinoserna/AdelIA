# AdelIA — "Grabar consulta" cumpliendo RGPD — Design Spec

**Fecha**: 2026-08-17
**Estado**: aprobado por Santiago (diseño en chat) — pendiente review del spec escrito
**Contexto previo**: item roadmap v0.2 "Recording consulta en vivo" (spec v0.1 §roadmap, línea 566). Trigger: pregunta de entrevista "¿y le dices al médico que vas a grabar?" — la respuesta era no, y eso no es defendible RGPD para una plataforma cloud.
**Research base**: `agent_marketing/08_adelia/research/2026-08-17_grabar_consulta_rgpd_research.md` (4 agentes, fuentes primarias: BOE, Légifrance, CURIA, AEPD, políticas Nabla/Doctolib/Medcorder/Tandem/Accurx/Hedy).

---

## 1. Qué es

Un botón **"Grabar consulta"** que graba el audio de la visita médica del bebé desde el navegador (móvil), lo transcribe con diarización (Médico / Yo) y lo integra al historial (pipeline RAG existente) — con un flujo de consentimiento que hace la grabación **anunciada, registrada y defendible bajo RGPD** en España y Francia.

Complementa al Modo Consulta existente (`consulta-mode.tsx` = asistencia en vivo por dictado Web Speech, frontend-only): el Modo Consulta te ayuda *durante*; la grabación captura la consulta *para el historial*.

## 2. Fundamento legal (resumen operativo)

| Cuestión | Conclusión | Fuente |
|---|---|---|
| ¿Puede el paciente grabar su consulta en ES? | Sí, como interlocutor (no es interceptación). La **difusión** sin consentimiento sí es problema (intimidad, LO 1/1982). | STC 114/1984; art. 197 CP |
| ¿Y en FR? | Grabación **clandestina** = riesgo penal real incluso siendo participante (zona gris "propos professionnels"). Grabación **anunciada sin oposición** = consentimiento presumido ("au vu et au su"). | Art. 226-1 Code pénal; Cass. crim. 05-84.384, 22-83.581 |
| ¿La excepción doméstica RGPD cubre esto? | Cubre a la madre, **no a AdelIA**: quien "proporciona los medios" queda plenamente sujeto. AdelIA es **responsable del tratamiento** del audio. | Art. 2.2.c + Considerando 18 in fine; TJUE Ryneš C-212/13 |
| Datos implicados | Salud de menor (art. 9 → consentimiento explícito 9.2.a del titular de patria potestad) + voz/identidad/juicio del médico (art. 4.1; transparencia art. 14). | RGPD |
| ¿Firma del médico? | **No** — desproporcionado e innecesario. Sí: informar + registrar no-oposición. | Análisis AEDS/AEPD/CNIL |
| DPIA | **Obligatoria** antes de lanzar (salud + menores + IA + terceros grabados). | Art. 35 RGPD |

Principios de diseño derivados: grabación **anunciada por diseño** (el gate fuerza informar), **prueba embebida** (los primeros segundos capturan la pregunta y el OK verbal), **minimización** (audio se borra tras transcribir; estándar de facto UE: Doctolib, Nabla, Tandem, Accurx), **trazabilidad** (log de consentimiento append-only), **procesamiento 100% UE**.

## 3. Alcance v1 / fuera de alcance

**v1**: grabación en navegador (MediaRecorder), gate de consentimiento, banner + kill switch, upload al pipeline existente, transcripción Voxtral con diarización, borrado de audio post-transcripción, tabla `consent_events`, página pública `/profesionales`, textos legales, i18n es/en/fr.

**Fuera de alcance v1** (documentado, no ignorado):
- Streaming cero-retención estilo Nabla (audio nunca toca disco) — north star v2; Voxtral Realtime no diariza hoy.
- STT on-device (Hedy) — calidad/batería insuficientes para 20-30 min.
- Segmentación con auto-guardado para grabaciones largas / iOS en background — v1.1 (v1 mitiga con Wake Lock + aviso).
- Hosting HDS para usuarios FR — se documenta el gap en la DPIA con plan (OVH/Scaleway HDS si tracción FR).
- Validación/edición del transcript por la madre antes de indexar — v1 indexa automático (como cualquier documento); la madre puede ver el texto y borrar el documento entero (cascada GDPR existente).

## 4. Flujo UX

### 4.1 Entrada
- Card "Grabar consulta" en la página Modo Consulta (`dashboard/consulta`) + acceso desde `dashboard/upload`.
- Ruta nueva: `dashboard/consulta/grabar`.

### 4.2 Gate pre-grabación (cada grabación, no saltable — patrón Medcorder)
Pantalla con:
1. Selector de perfil (bebé) — default el perfil activo.
2. Script sugerido, grande y localizado: *"¿Le parece bien que grabe la consulta para el historial de mi bebé?"*
3. Checkbox: **"He informado al profesional y no se opone"** — sin marcar, el botón Grabar está `disabled` (con motivo visible, patrón ya usado en la app).
4. Enlace "Mostrar información al profesional" → `/profesionales` (público, sin login, es/en/fr): qué se graba, para qué, dónde se aloja (UE), retención, derechos RGPD del profesional y canal de contacto. Cubre transparencia art. 14 by design.
5. Microcopy legal por locale: ES "Grabar tu propia consulta es legal; difundirla no. Uso personal y familiar." / FR "Enregistrez toujours de manière annoncée: l'enregistrement clandestin peut constituer un délit (art. 226-1)."

Al marcar el checkbox se registra el **consent event** (se envía con el upload, §6.3).

### 4.3 Durante la grabación
- Banner rojo persistente + cronómetro + nivel de audio (feedback de que capta). Diferenciador: casi ningún competidor muestra indicador prominente.
- Botón **Parar** (finaliza y sube).
- Botón **"El profesional se opone"** → para y **borra localmente** el blob, sin subir nada; registra evento `recording_declined` (sin audio). La madre vuelve al Modo Consulta (dictado) como fallback.
- Wake Lock API activo + aviso "mantén la pantalla encendida" (iOS suspende MediaRecorder al bloquear).
- Recordatorio en pantalla los primeros segundos: "Pregúntaselo ahora en voz alta" — deja la no-oposición grabada (en FR activa la presunción del 226-1).

### 4.4 Después
- Upload (opus mono ~32 kbps: ~5 MB por 20 min) → card de estado "Transcribiendo…" (polling estado documento, patrón briefings).
- Al terminar: documento tipo consulta en `dashboard/documents` con transcript diarizado por hablantes (`[Hablante 1] / [Hablante 2]` — la diarización no sabe quién es el médico; renombrar hablantes es v1.1) en `raw_text`; entities/chunks/briefings-stale como cualquier documento.
- Mensaje explícito de minimización: **"El audio se ha eliminado. Solo conservamos la transcripción."**

## 5. Arquitectura técnica — Frontend

| Pieza | Detalle |
|---|---|
| `next.config.ts` | **Bloqueante**: `Permissions-Policy: camera=(), microphone=(self), geolocation=()` (hoy `microphone=()` bloquea getUserMedia/MediaRecorder — y probablemente el dictado Web Speech del Modo Consulta actual). |
| `components/consulta-recorder.tsx` | Client component: gate + MediaRecorder (`audio/webm;codecs=opus` Chrome/Firefox, `audio/mp4` Safari — detectar con `MediaRecorder.isTypeSupported`), `audioBitsPerSecond: 32_000`, mono. Timer, nivel de audio (AnalyserNode), Wake Lock, kill switch. |
| Ruta | `app/[locale]/dashboard/consulta/grabar/page.tsx`; card de entrada en la página consulta + enlace en upload. |
| Página pública | `app/[locale]/profesionales/page.tsx` (sin auth, indexable, estática). |
| Upload | `POST /api/backend/documents` (FormData) con campos nuevos: `profile_id`, `source=consulta`, `consent_policy_version`. Proxy: prefijo `documents` ya allow-listed; ojo que bufferiza el body en RAM (route.ts) — aceptable a 5-15 MB. |
| i18n | Claves nuevas bajo `consulta.record.*` + `professionals.*` en es/en/fr (paridad de leaf keys, patrón existente). |
| Design system | `.ad-btn-danger` para estado grabando, `.ad-card`, tokens existentes. |

Límite cliente: subir cap de validación de audio a 50 MB (alineado con backend) — el actual 25 MB de `upload-zone` se queda corto para >60 min; con opus 32 kbps, 50 MB ≈ 3h20 (de sobra).

## 6. Arquitectura técnica — Backend

### 6.1 MIME + router (`routers/documents.py`)
- `ALLOWED_MIME` += `audio/webm`, `audio/mp4`, `audio/ogg`, `audio/x-m4a`, `audio/flac`.
- Normalizar `content_type` antes del check: `content_type.split(";")[0].strip()` (MediaRecorder emite `audio/webm;codecs=opus`).
- `upload_document` acepta `profile_id: uuid | None = Form(None)`, `source: str = Form("web")` (validado contra `{'web','manual','consulta'}`), `consent_policy_version: str | None = Form(None)`.
- Si `source == "consulta"`: exigir `consent_policy_version` (400 si falta) y crear `ConsentEvent` en la misma transacción que el `Document`.
- Propagar `profile_id` a `Document` y (en `_process_document_inner`) a entities/chunks — hoy el upload no lo asigna.

### 6.2 STT conmutable (`workers/transcribe.py` + `config.py`)
- `config.py`: `stt_provider: str = "mistral"` (`"mistral" | "openai"`), `mistral_stt_model: str = "voxtral-mini-latest"`.
- `transcribe_audio(body, mime_type, *, diarize: bool = False) -> str` — el orquestador pasa `diarize=True` solo cuando `document.source == "consulta"` (las notas de voz sueltas siguen con transcript plano):
  - **mistral** (default): La Plateforme `audio/transcriptions` con `diarize=True` para consultas → formatear segmentos como `[Hablante 1] … / [Hablante 2] …` en el transcript. Residencia UE por defecto. ~$0.003/min (~$0.06 por consulta de 20 min). Reusa `mistral_api_key` ya en prod.
  - **openai** (fallback): whisper-1 actual, sin diarización (transcript plano).
  - Errores: mismo contrato actual (RuntimeError config / transient retry con `_with_retry`).
- Context biasing (Voxtral, hasta 100 términos): lista pediátrica es/fr/en (vacunas, percentil, fármacos comunes) — mejora nombres propios clínicos. Opcional v1, barato de añadir.

### 6.3 Migración `0015_consulta_recording`
1. `documents_source_check` → `('web','manual','consulta')`.
2. Tabla **`consent_events`** (append-only, sin UPDATE/DELETE en app):
   - `id` UUID PK, `user_id` FK users, `profile_id` FK profiles nullable, `document_id` FK documents nullable (NULL en `recording_declined`), `event_type` CHECK `('recording_informed_professional','recording_declined')`, `policy_version` text, `locale` text, `created_at` timestamptz.
   - **Minimización**: sin nombre del médico, sin centro, sin contenido.
3. Endpoint `POST /consent-events` para `recording_declined` (el caso informed va embebido en el upload).

### 6.4 Borrado del audio (minimización art. 5.1.c)
- Al completar el pipeline (transcript persistido + embeddings): programar borrado del blob S3 vía **`blob_tombstones`** (infra existente de 0013) con gracia de **48 h** (reintentos/soporte); tras el sweep, `s3_key` queda NULL y el documento conserva solo `raw_text`.
- Si el stage transcribe falla definitivamente: conservar el audio **7 días** (reintento manual) y luego tombstone igualmente.
- El borrado por usuario (documento o cuenta) reutiliza cascadas GDPR existentes (0011) — borra transcript + entities + chunks; los `consent_events` se borran en cascada con la cuenta (minimización; mientras la cuenta exista sirven de accountability art. 5.2).

### 6.5 Registro de tratamiento
- `IngestionEvent` con `source='web'` sigue registrando el ingest (sin ampliar su CHECK; la traza fina está en `consent_events` + `documents.source='consulta'`).

## 7. RGPD operativo (entregables no-código)

1. **DPIA** (`docs/legal/dpia-grabacion-consulta.md`) — antes de activar en prod: riesgos (menor art. 9, voz del médico, retención Mistral 30 días abuse-monitoring en plan estándar —ZDR solo Scale—, server casero sin HDS para FR), mitigaciones (este diseño), decisión y firma. Es también el artefacto que responde la pregunta de entrevista.
2. **Política de privacidad**: sección "Grabar consulta" (finalidad, encargado STT = Mistral con DPA art. 28, ubicación UE, retención: audio ≤48h post-transcripción / transcript como historial, no entrenamiento con tus datos).
3. **Términos**: uso personal y familiar; prohibida la difusión pública; aviso diferenciado ES/FR.
4. **`/profesionales`**: la nota art. 14 para el médico (§4.2.4).
5. **README/self-host**: reparto de roles — en self-host el responsable es quien despliega; en el SaaS, AdelIA.

## 8. Testing

- **Unit backend**: normalización MIME (`;codecs=`), transcribe provider switch (mocked), formateo diarización, creación atómica Document+ConsentEvent, exigencia de `consent_policy_version` con `source=consulta`, tombstone programado post-pipeline.
- **Live-gated**: transcripción Voxtral real con `MISTRAL_API_KEY` (patrón skipif existente).
- **E2E (Playwright)**: gate bloquea Grabar sin checkbox; kill switch no sube nada y registra declined; flujo completo con audio corto fixture → documento ready → mensaje "audio eliminado"; `/profesionales` accesible sin login en 3 locales.
- **A11y**: axe sobre las 2 superficies nuevas (patrón e2e/a11y.spec.ts).

## 9. Riesgos y mitigaciones

| Riesgo | Mitigación |
|---|---|
| iOS corta MediaRecorder al bloquear pantalla | Wake Lock + aviso; segmentación v1.1 |
| Diarización Voxtral floja con bebé llorando/solapes | Probar con audio real antes de promover; plan B Gladia (FR, ZDR, diarización incluida, ~$0.20/consulta) |
| Mistral retiene 30 días (abuse monitoring) | Documentado en DPIA + privacy; ZDR al pasar a plan Scale; fallback self-host faster-whisper = cero salida de datos |
| Transcripciones largas ocupan el worker in-process (BackgroundTasks, semáforo 8) | Aceptable v1 (batch async, no realtime); Celery ya previsto en roadmap |
| Proxy Next bufferiza el body en RAM | Aceptable a 5-15 MB opus; revisar si se amplía a >1h |
| Médico descubre grabación no anunciada → ruptura de confianza | El producto no lo permite: gate + script + banner |

## 10. Coste

~$0.06 por consulta de 20 min (Voxtral batch). 100 consultas/mes ≈ $6. Sin coste nuevo de vendors (Mistral ya contratado).
