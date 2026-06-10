---
slug: generic-ccd
title: CCD genérico (Cerner, Allscripts, Athena, eClinicalWorks)
description: Importa archivos CCD XML de cualquier portal de pacientes que use el estándar HL7 C-CDA.
estimated_time: 5-10 minutos
device: Navegador web del portal de tu hospital
output_format: CCD XML
---

# Importar CCD genérico (cualquier hospital US/UE)

El formato **C-CDA** (Continuity of Care Document) es un estándar HL7 obligatorio para portales de pacientes en EE.UU. (regulación Meaningful Use) y opcional pero común en Europa. AdelIA tiene un parser genérico que funciona con CCD de cualquier vendor.

## Sistemas compatibles confirmados

| Vendor | Portal | Cómo descargar |
|--------|--------|----------------|
| **Cerner / Oracle Health** | HealtheLife | Sharing → Download Health Information |
| **Allscripts (Veradigm)** | FollowMyHealth | Health Record → Download |
| **Athena Health** | athenaPatient | Test Results → Download (PDF or CCD) |
| **eClinicalWorks** | healow | Records → Download CCD |
| **NextGen** | Patient Portal | Records → Export CCD |
| **Greenway Health** | Patient Portal | Health Records → Download |
| **Epic** | MyChart | Sharing → Download My Record |

Si tu vendor no está listado pero ofrece descarga en `.xml`, prueba — el parser AdelIA acepta cualquier CCD válido HL7 R2.1+.

## Pasos genéricos

### 1. Inicia sesión en el portal del paciente de tu hospital

Cada hospital tiene su URL. Busca "patient portal" + nombre del hospital.

### 2. Busca la opción de descarga/exportación

Nombres comunes:
- "Download My Record"
- "Share My Health Information"
- "Export Health Summary"
- "Health Records Export"

### 3. Selecciona formato CCD / CCDA / XML

Si el portal ofrece varios formatos:
- ✅ **CCD/CCDA/XML** — Preferido (estructurado)
- ⚠️ **PDF** — Aceptable (AdelIA usa OCR, pero menos preciso)
- ❌ **TXT** — Evitar (estructura perdida)

### 4. Descarga (rango de fechas: TODO)

Si te pregunta rango, elige el máximo disponible. AdelIA deduplica por timestamp.

### 5. Sube a AdelIA

1. Dashboard → **Importar → CCD**
2. Arrastra el archivo `.xml`
3. AdelIA parsea entities (allergies, medications, problems, procedures, vital signs, immunizations, lab results)

## Qué extrae el parser

Igual que la guía de [MyChart](./mychart):

| Sección CCD | Entity Type |
|------------|-------------|
| Allergies (Allergies and Adverse Reactions) | `allergy` |
| Medications (Active Medications) | `medication` |
| Problems (Active Problems) | `condition` |
| Procedures | `procedure` |
| Vital Signs | `observation` |
| Immunizations | `immunization` |
| Lab Results / Results | `observation` |
| Encounters | (no se importa v0.1, futuro v0.1.1) |
| Care Plan | (no se importa v0.1, futuro v0.2) |

## Verificación de import correcto

Después de subir:

1. Abre el documento en el dashboard
2. Verás counts: "X entities extraídas, Y chunks indexados"
3. Si entity count es muy bajo (< 5) para un CCD substancial, posibles causas:
   - CCD vacío (raro, pero posible si el hospital aún no ha cargado nada)
   - CCD con formato no estándar (vendor custom) — abre un issue con el sample anonimizado

## Solución de problemas

**Mi hospital usa Epic pero la guía de MyChart no me funciona:**
Algunos hospitales con Epic deshabilitan el download CCD por políticas internas. Workaround: pide formalmente tu historial vía HIPAA Right of Access usando el template **Dashboard → Importar → GDPR/HIPAA Templates → US Generic**.

**El CCD se descarga como .zip:**
Algunos portales empaquetan el CCD + attachments (PDFs, imágenes). Descomprime y sube el `.xml`; los attachments PDFs súbelos por separado desde el dashboard.

**El parser dice "0 entities found":**
Tu CCD podría usar un schema HL7 R1.x antiguo. v0.1 soporta R2.1+. Abre un issue con un sample anonimizado para evaluar añadir compatibilidad.

## Más allá

- En v0.3+, AdelIA integrará SMART on FHIR directo (sin export manual) para Epic, Cerner, Allscripts.
- Hasta entonces, este import manual es la vía estable y privacy-respecting.
