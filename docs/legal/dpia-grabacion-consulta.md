# DPIA — Grabar consulta (grabación y transcripción de la consulta pediátrica)

**Evaluación de Impacto relativa a la Protección de Datos (art. 35 RGPD)**

| | |
|---|---|
| **Tratamiento evaluado** | Función "Grabar consulta": grabación de audio de la visita pediátrica, transcripción diarizada e incorporación al historial del menor. |
| **Responsable del tratamiento** | SaaS `adelia.godi.ai`: Godi.AI. Instancias self-host: quien despliega la instancia (ver `README.md § Self-host`). |
| **Encargado del tratamiento (STT)** | Mistral AI (Francia/UE) — La Plateforme, `audio/transcriptions`, modelo `voxtral-mini-latest`. |
| **Fecha de esta evaluación** | 2026-08-17 |
| **Artefactos de referencia** | `docs/specs/2026-08-17-adelia-grabar-consulta-rgpd-design.md` (spec); `agent_marketing/08_adelia/research/2026-08-17_grabar_consulta_rgpd_research.md` (research: BOE, Légifrance, CURIA, AEPD, políticas Nabla/Doctolib/Medcorder/Tandem/Accurx/Hedy); `docs/plans/2026-08-17-adelia-grabar-consulta-rgpd.md` (plan de implementación, tasks 1-11). |
| **Ámbito** | v1 tal y como se describe en el spec §3. No cubre streaming cero-retención, STT on-device, ni certificación HDS (gaps documentados abajo). |

---

## 1. Descripción del tratamiento

### 1.1 Qué es

Un botón **"Grabar consulta"** (`dashboard/consulta/grabar`) que permite a un progenitor o tutor grabar, desde el navegador de su móvil, el audio de la visita médica de su bebé. El audio se transcribe con diarización de hablantes y el texto resultante se integra al historial privado del menor, siguiendo el mismo pipeline de ingesta (extracción de entidades, chunking jerárquico, embeddings) que cualquier otro documento subido a AdelIA.

Es un tratamiento **distinto** del "Modo Consulta" existente (`consulta-mode.tsx`, dictado Web Speech client-side, sin grabación ni persistencia de audio): aquí sí hay una grabación de audio real que sale del dispositivo y se procesa en servidores de AdelIA/Mistral.

### 1.2 Flujo de datos (verificado en código)

1. **Inicio voluntario**: el progenitor/tutor abre `dashboard/consulta/grabar`. Componente `apps/web/components/consulta-recorder.tsx`.
2. **Gate de consentimiento no saltable**: pantalla con selector de perfil (bebé), script sugerido ("¿Le parece bien que grabe la consulta para el historial de mi bebé?"), checkbox **"He informado al profesional y no se opone"**, y enlace a `/profesionales`. El botón "Grabar" tiene `disabled={!informed || starting}` — sin marcar el checkbox, es físicamente imposible iniciar la grabación.
3. **Grabación**: `MediaRecorder` captura audio mono a 32 kbps (opus/webm o mp4 según navegador). Banner rojo persistente con cronómetro y nivel de audio en vivo. Durante los primeros 15 segundos se muestra en pantalla "Pregúntaselo ahora en voz alta" — la no-oposición verbal del profesional queda así en los primeros segundos del propio audio.
4. **Kill switch**: en cualquier momento, el botón **"El profesional se opone"** detiene la grabación, descarta el blob localmente (`discardRef`, nunca se sube) y registra un evento `recording_declined` sin audio vía `POST /consent-events`.
5. **Subida**: al pulsar "Terminar y guardar", el blob se envía a `POST /documents` (FormData) con `source=consulta`, `profile_id`, `consent_policy_version=2026-08-17`, `locale`. El backend (`apps/api/adelia/routers/documents.py`) valida la propiedad del `profile_id` contra el usuario autenticado (guarda anti-IDOR, mismo patrón que `enrichment.get_user_profile`) antes de aceptar el fichero.
6. **Consentimiento registrado atómicamente**: en la misma transacción que crea el `Document`, se crea un `ConsentEvent(event_type="recording_informed_professional", policy_version, locale)` — si la transacción falla, se compensa borrando el blob S3 huérfano.
7. **Transcripción**: el orquestador de procesamiento (`_process_document_inner`, `is_consulta=True`) llama a `transcribe_audio(..., diarize=True)`. Proveedor por defecto `stt_provider="mistral"` → Mistral Voxtral (`voxtral-mini-latest`) vía La Plateforme, residencia UE, `diarize=true`. El resultado se formatea como bloques `[Hablante 1] … / [Hablante 2] …` (la diarización no identifica quién es el médico; renombrar hablantes queda para v1.1). El fallback a OpenAI Whisper existe en el código pero está deshabilitado por defecto y no diariza.
8. **Indexación**: el texto transcrito entra al mismo pipeline RAG que cualquier documento — extracción de entidades clínicas, chunking jerárquico, embeddings — sin distinción respecto a documentos subidos por otros medios.
9. **Borrado del audio (minimización)**: al terminar el pipeline, se crea un `BlobTombstone` con `not_before` = ahora + **48 horas** si la transcripción tuvo texto, o + **7 días** si falló (para permitir reintento manual antes de perder el audio fuente). Un sweep al arranque del servidor y otro post-pipeline ejecutan el borrado efectivo del blob S3 cuando llega su hora. Tras el borrado, `documents.s3_key` queda `NULL` y solo sobrevive `raw_text`.

### 1.3 Categorías de datos e interesados

- **Datos de salud del menor** (art. 9 RGPD): contenido clínico de la consulta, transcrito verbatim.
- **Voz y contenido de las explicaciones del profesional sanitario**: dato personal indirecto de un tercero no usuario de la plataforma.
- **Voz del progenitor/tutor** que graba (participante en la conversación, no tercero).
- **Metadatos de consentimiento** (`consent_events`): `user_id`, `profile_id`, `document_id`, `event_type`, `policy_version`, `locale`, `created_at` — deliberadamente **sin** nombre del médico, centro sanitario ni contenido de la conversación (minimización, ver migración `0015_consulta_recording.py`).

---

## 2. Base jurídica

### 2.1 Datos de salud del menor — art. 9.2.a RGPD

Fundamento: **consentimiento explícito** del titular de la patria potestad. Se instrumenta en dos capas:

1. **Consentimiento de plataforma** (aceptación de términos/política de privacidad al registrarse — ya cubre el tratamiento general de documentos médicos del menor).
2. **Consentimiento específico por grabación**, registrado en `consent_events` en el momento exacto de cada uso de "Grabar consulta" — no basta el consentimiento general de la cuenta porque cada grabación implica a un tercero (el profesional) y un acto de captura de audio nuevo.

### 2.2 Datos incidentales del profesional sanitario — interés legítimo (art. 6.1.f)

El profesional no es usuario de AdelIA y no puede prestar un "consentimiento art. 9" en el sentido estricto (no son sus datos de salud los que se tratan como finalidad, sino su voz e intervención verbal). El análisis legal (ver research base) descarta pedir firma del profesional por desproporcionado, y apoya el tratamiento en **interés legítimo documentado**, con el siguiente test de ponderación:

| Factor del test | Resultado |
|---|---|
| **Finalidad legítima** | Memoria familiar y fidelidad del historial clínico del menor — finalidad concreta, explícita y no ligada a evaluación del profesional ni a fines comerciales. |
| **Necesidad** | No hay alternativa igual de fiable: la nota manual pierde precisión (dosis, indicaciones) frente a la transcripción verbatim; el "Modo Consulta" por dictado ya existe como alternativa menos invasiva y sigue disponible como fallback tras el kill switch. |
| **Expectativa razonable del interesado** | El profesional actúa en el ejercicio de su función pública/profesional, en un acto ya sujeto a registro habitual (historia clínica, notas). La grabación está **anunciada por diseño** (gate + script + banner) — no hay expectativa razonable de que la consulta sea confidencial frente al propio paciente/tutor que la graba y anuncia grabar. |
| **Minimización y salvaguardas** | Sin firma ni identificación nominal del profesional en `consent_events`; sin centro sanitario; el audio se borra en ≤48h; el texto se etiqueta por hablante genérico (`Hablante 1/2`), no por nombre. |
| **Balance final** | El interés de la familia (y del interés superior del menor en un historial fiel) prevalece, siempre que se mantengan las salvaguardas de diseño (gate no saltable, minimización, borrado). Si estas salvaguardas se desactivaran, el balance cambiaría — de ahí que el README (§ self-host) exija mantenerlas activas. |

### 2.3 Marco legal ES/FR que sostiene el diseño (resumen operativo)

| Cuestión | Conclusión | Fuente |
|---|---|---|
| ¿Puede el paciente grabar su propia consulta en España? | Sí, como interlocutor — no es interceptación de comunicación ajena. La **difusión** sin consentimiento del médico sí sería un problema de intimidad (LO 1/1982). | STC 114/1984; art. 197 CP |
| ¿Y en Francia? | Grabación **clandestina** = riesgo penal real incluso siendo participante en la conversación (zona gris "propos professionnels"). Grabación **anunciada, sin oposición** = consentimiento presumido ("au vu et au su"). | Art. 226-1 Code pénal; jurisprudencia Cass. crim. 05-84.384, 22-83.581 |
| ¿Cubre esto la excepción doméstica del RGPD (art. 2.2.c)? | Cubre a la madre que graba para uso puramente personal, **no cubre a AdelIA**: quien "proporciona los medios" de tratamiento (app, servidores, IA de transcripción) queda plenamente sujeto al RGPD como responsable. | Art. 2.2.c + Considerando 18 in fine RGPD; TJUE, *Ryneš*, C-212/13 |
| ¿Se necesita DPIA? | Sí, obligatoria antes de lanzar: cruce de datos de salud (art. 9) + menores + procesamiento por IA + grabación de terceros. Este documento la satisface. | Art. 35 RGPD |

**Principios de diseño derivados de este marco** (verificados en el código, §1.2): grabación anunciada por diseño (gate no saltable), prueba embebida en el propio audio (primeros 15s), minimización (borrado ≤48h), trazabilidad (log append-only), procesamiento 100% UE.

---

## 3. Transparencia (art. 13/14 RGPD)

| Destinatario | Mecanismo | Momento |
|---|---|---|
| **Progenitor/tutor** (art. 13) | Política de privacidad de la cuenta (aceptada al registro) + microcopy legal en el propio gate: ES *"Grabar tu propia consulta es legal en España. Compartirla o difundirla, no. Uso personal y familiar."* / FR *"Graba siempre de forma anunciada: en Francia la grabación oculta puede ser delito (art. 226-1)."* | Antes de cada grabación. |
| **Profesional sanitario** (art. 14, dato de tercero) | Página pública `/profesionales` (`apps/web/app/[locale]/profesionales/page.tsx`), sin login, indexable, en es/en/fr. Contenido real (mensajes i18n `professionals.*`): qué se graba y para qué, dónde se procesa (UE, Mistral AI como encargado, sin entrenamiento de modelos con estos datos), cuánto se conserva (audio ≤48h, solo texto después), sus derechos (oposición inmediata vía kill switch + RGPD estándar) y contacto — `security@godi.ai`, respuesta en ≤30 días (mensaje `professionals.contactBody`). | Enlazada desde el propio gate ("Mostrar información para profesionales") y accesible en cualquier momento antes/durante/después de la consulta. |
| **Prueba embebida en el acto** | Script verbal sugerido + recordatorio "Pregúntaselo ahora en voz alta" en los primeros 15s de grabación — deja la no-oposición del profesional grabada en el propio audio (refuerza la presunción "au vu et au su" en Francia). | Primeros segundos de cada grabación. |

La transparencia hacia el profesional no depende de que la familia recuerde mostrar la página: el propio diseño del gate la fuerza a estar un clic de distancia, y el guion oral la sustituye cuando el profesional no la lee.

---

## 4. Riesgos y mitigaciones

| Riesgo | Mitigación implementada | Estado |
|---|---|---|
| **Grabación clandestina** (el profesional no se entera) | Imposible por diseño: gate no saltable (checkbox obligatorio + botón `disabled`), banner rojo persistente durante toda la grabación, script verbal + recordatorio en los primeros 15s. | Mitigado (control técnico, no solo política). |
| **Difusión no autorizada** del audio o transcripción (fuera de la familia) | Prohibida en los términos de uso (finalidad exclusivamente personal y familiar). No existe ninguna función de compartir el audio; la función de compartir existente (`sharing.py`, enlaces firmados) aplica a *briefings*, no a documentos crudos de tipo consulta. | Mitigado a nivel de producto; residual: nada impide técnicamente a la familia grabar la pantalla o descargar el texto y reenviarlo — fuera del control de AdelIA, como con cualquier documento. |
| **Retención de 30 días en Mistral** (abuse monitoring, plan estándar de La Plateforme) | Documentado aquí y en la política de privacidad. Mitigación: minimización (solo se envía el audio de la consulta, sin metadatos identificativos adicionales), DPA art. 28 con Mistral AI, y **ZDR (Zero Data Retention) disponible al escalar a plan Scale** — pendiente de contratar si el volumen lo justifica. Fallback interno documentado (no desplegado en v1): self-host `faster-whisper` con cero salida de datos, para cuando la escala lo requiera. | **Riesgo residual aceptado para v1**, con plan de mitigación futura conocido. |
| **Servidor de producción sin certificación HDS** (Hébergeur de Données de Santé, exigible en Francia para datos de salud) | El servidor actual (self-hosted en infraestructura propia) **no está certificado HDS**. Gap documentado explícitamente: plan de migración a OVH o Scaleway (ambos con oferta HDS) si hay tracción significativa de usuarios franceses. Mitigación mientras tanto: cifrado en tránsito, minimización del dato retenido (el audio se borra en 48h; solo persiste texto), y transparencia de este gap en la propia DPIA. | **Riesgo residual aceptado para v1**, activador de acción claro (tracción FR) — no es un placeholder, es una decisión explícita con criterio de revisión. |
| **Acceso no autorizado al blob de audio** (otro usuario, fuga de credenciales) | `profile_id` validado contra el usuario autenticado antes de aceptar el upload y antes de registrar el evento de rechazo (guarda anti-IDOR en `documents.py` y `consent.py`); el objeto S3 se sube sin ACL pública (privado por defecto, sin `public-read`); el propio blob desaparece a las 48h. Cifrado en tránsito depende de que el endpoint S3 de producción esté servido sobre HTTPS (self-host: responsabilidad de quien despliega, ver README); cifrado en reposo depende de la configuración del proveedor de almacenamiento de objetos (SSE del proveedor en el SaaS) — **no está forzado a nivel de código de aplicación** (`storage.py` no pasa `ServerSideEncryption`), así que no se afirma como garantía universal. | Mitigado en el vector de mayor probabilidad (IDOR de aplicación); dependiente de configuración de infraestructura para cifrado en reposo — documentado como tal, no asumido. |
| **Fallo de transcripción deja audio "vivo" más tiempo** | Gracia de 7 días (en vez de 48h) solo para permitir un reintento manual; pasado ese plazo, tombstone igual que el caso de éxito. Sweep de borrado corre al arranque del servidor y tras cada pipeline. | Mitigado (ventana acotada y justificada). |
| **Diarización floja con solapes / bebé llorando** | No es un riesgo RGPD directo, pero afecta la fidelidad del historial. Documentado en el spec (§9) como validación pendiente con audio real antes de promover a producción; plan B conocido (Gladia, FR, ZDR, diarización incluida). | Riesgo de calidad, no de conformidad — mitigación de producto en curso. |
| **Supresión de una grabación individual sin borrar toda la cuenta** | Verificado en código: hoy **no existe** un endpoint de borrado por documento (`DELETE /documents/{id}`); el único borrado self-service disponible es el de cuenta completa (`DELETE /users/me`), que sí cascada correctamente todo lo relacionado con esa grabación (ver §5). Se documenta como limitación conocida, no se afirma una capacidad de borrado granular que no existe. | **Gap identificado en esta revisión** — mitigación interina: solicitud a `security@godi.ai`; recomendado como ítem de roadmap (fuera del alcance de v1 según spec §3). |

---

## 5. Derechos de las personas afectadas

### 5.1 Progenitor/tutor y menor (titulares de los datos de salud)

- **Acceso**: el texto transcrito es visible en `dashboard/documents/{id}` como cualquier otro documento; las entidades clínicas extraídas siguen un esquema alineado con terminologías estándar (ICD-10/SNOMED/LOINC/RxNorm) y son consultables vía la app y el chat sobre el historial. **Precisión importante**: no existe hoy un botón único de "exportar todos mis datos en FHIR" — el acceso es a través de la interfaz de la aplicación (documento por documento, chat, briefings en PDF vía enlaces firmados), no un export masivo estandarizado. Se evita aquí afirmar una función de portabilidad automatizada que el código no implementa.
- **Rectificación**: la transcripción no es editable en v1 (spec §3, fuera de alcance); la corrección disponible es el borrado del documento completo (a nivel de cuenta, ver abajo) y volver a grabar o subir manualmente.
- **Supresión (art. 17)**: self-service desde Ajustes de cuenta (`account-settings-view.tsx`) — requiere marcar una casilla de "entiendo que es irreversible" y escribir el email de la cuenta para armar el botón de borrado. Al confirmarse, `DELETE /users/me` ejecuta de inmediato la cascada RGPD (migración `0011_gdpr_cascade`): documentos → entidades/chunks, briefings → citas/enlaces de compartición, sesiones de chat → mensajes, perfiles, y programa el borrado de todos los blobs S3 vía tombstone. Los `consent_events` se borran en cascada con la cuenta (FK `ON DELETE CASCADE` sobre `user_id`) — mientras la cuenta exista, sirven de prueba de accountability (art. 5.2); al borrarse la cuenta, se borran con ella (minimización). **Limitación documentada**: no hay borrado self-service de una grabación individual sin borrar toda la cuenta (ver gap en §4); mitigación interina vía `security@godi.ai`.
- **Oposición / retirada**: cada grabación requiere un nuevo consentimiento explícito (el gate no es "recordado" entre sesiones); no grabar es simplemente no usar el botón — el "Modo Consulta" por dictado sigue disponible sin grabación de audio.

### 5.2 Profesional sanitario (tercero cuyos datos incidentales se tratan)

- **Información** (art. 14): página `/profesionales`, accesible sin cuenta, en su idioma.
- **Oposición inmediata**: botón **"El profesional se opone"** durante la grabación — detiene la captura, borra el blob localmente sin subir nada, y dice explícitamente en pantalla "Grabación descartada. No se ha guardado nada." El único rastro que queda es un `ConsentEvent(event_type="recording_declined")` sin audio ni contenido, para trazabilidad de que el mecanismo se usó.
- **Canal de contacto**: `security@godi.ai`, con compromiso de respuesta en un plazo máximo de 30 días (texto ya publicado en `/profesionales`, clave i18n `professionals.contactBody`), para ejercer derechos RGPD de acceso, rectificación o supresión sobre su voz/participación si una grabación ya se completó sin que el kill switch se usara a tiempo.

---

## 6. Decisión

**Evaluación**: los riesgos identificados en §4 tienen mitigaciones de diseño verificadas en el código (gate no saltable, minimización por borrado a 48h, trazabilidad append-only, validación anti-IDOR, procesamiento 100% UE para la transcripción) o son riesgos residuales explícitamente aceptados con un plan de acción conocido (retención Mistral 30 días → ZDR en plan Scale; ausencia de HDS → migración OVH/Scaleway si hay tracción FR; ausencia de borrado granular por documento → item de roadmap, mitigado interinamente por contacto directo).

Ninguna mitigación aquí descrita es aspiracional: cada una se verificó contra el código en la fecha de esta evaluación (`git log --oneline -1` en `feat/consulta-recording`).

**Decisión**: **aprobado para lanzar en v1** con las salvaguardas descritas, condicionado a mantener activos el gate de consentimiento, el borrado de audio a 48h/7 días, y la página `/profesionales`. Esta condición se traslada operativamente al README (sección Self-host): quien despliega una instancia self-host asume el rol de responsable del tratamiento y hereda esta misma obligación de mantener las salvaguardas activas.

**Revisión de esta DPIA requerida antes de**: (a) activar el fallback OpenAI Whisper por defecto (pierde diarización y cambia el proveedor de tratamiento), (b) escalar a streaming cero-retención u otro cambio de arquitectura de STT, (c) tracción significativa de usuarios franceses (dispara la migración HDS ya planificada), (d) cualquier cambio que reduzca la fricción del gate de consentimiento.

---

Firmado: Santiago Patiño — _______________ (fecha)
