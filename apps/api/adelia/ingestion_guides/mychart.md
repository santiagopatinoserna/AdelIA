---
slug: mychart
title: MyChart / Epic
description: Exporta tu historial médico desde el portal MyChart (Epic) en formato CCD para importarlo a AdelIA.
estimated_time: 10 minutos
device: Navegador web o app MyChart
output_format: CCD XML
---

# Importar desde MyChart / Epic

MyChart es el portal de pacientes de Epic, el sistema clínico más usado en hospitales estadounidenses y muchos europeos. Permite exportar tu historial en formato estándar **C-CDA** (Continuity of Care Document) — XML que AdelIA parsea automáticamente.

## Pre-requisitos

- Cuenta MyChart activa en tu hospital
- Acceso a "Sharing" en tu perfil

## Pasos

### 1. Inicia sesión en MyChart

Abre [mychart.com](https://www.mychart.com) o la app móvil de MyChart con tus credenciales del hospital.

### 2. Navega a "Sharing" (Compartir)

- En la web: **Menu → Sharing → Share My Record**
- En la app: **Más → Compartir → Compartir mi historial**

### 3. Selecciona "Download My Record" (Descargar mi historial)

Elige el rango de fechas — recomendamos **"All visits"** (Todas las visitas) para tener historial completo.

### 4. Selecciona formato CCD

Algunas instancias ofrecen también PDF; **prefiere CCD** porque AdelIA puede extraer estructura (medicamentos, alergias, diagnósticos) automáticamente.

### 5. Descarga el archivo

Llegará un `.xml` o `.zip` con uno o más CCD adentro.

### 6. Sube a AdelIA

1. Dashboard → **Importar → MyChart / CCD**
2. Arrastra el archivo CCD
3. AdelIA parsea: Allergies, Medications, Problems, Procedures, Vital Signs, Immunizations, Lab Results
4. Verás "Importado X entities" cuando termine

## Qué extrae el parser CCD v0.1

| Sección CCD | Entity Type | Notas |
|------------|-------------|-------|
| Allergies | `allergy` | Substancia + reacción + severidad |
| Medications | `medication` | Nombre + dosis + frecuencia + ruta |
| Problems | `condition` | Diagnóstico + status (active/resolved) + onset date |
| Procedures | `procedure` | Nombre + fecha |
| Vital Signs | `observation` | Series temporal |
| Immunizations | `immunization` | Vacuna + fecha |
| Lab Results | `observation` | Valor + unidad + fecha + reference range (si presente) |
| Family History | ⏳ v0.1.1 | Mientras tanto, añádelo manualmente desde el chat |
| Social History | ⏳ v0.1.1 | |

## Compatibilidad con otros sistemas

El parser CCD es **estándar HL7 C-CDA R2.1** — funciona también con:
- **Cerner** (Oracle Health) → Sharing → Download
- **Allscripts** (Veradigm) → Patient Portal → Download
- **Athena Health** → Patient Portal → Download
- **eClinicalWorks** → Patient Portal → Download

Si tu sistema no aparece, abre un issue en [github.com/santiagopatinoserna/AdelIA](https://github.com/santiagopatinoserna/AdelIA) con un sample anonimizado del export.

## Solución de problemas

**MyChart no me deja descargar el CCD:**
Algunos hospitales desactivan esta opción. Workaround: pide formalmente tu historial vía GDPR (UE) o HIPAA Right of Access (US) usando los templates en **Dashboard → Importar → GDPR Templates**.

**El CCD se importó pero faltan secciones:**
v0.1 cubre 7 secciones core. Si tu CCD tiene secciones especializadas (oncology, mental health, etc.), abre un issue con el caso de uso para priorizar v0.1.1.

## Próximos pasos

- Abre **Modo A — Chat** y pregunta: *"¿Qué medicamentos he tomado este año?"*
- Crea un **Briefing** filtrado por la especialidad del próximo médico — AdelIA pre-baka las 5 preguntas más probables basándose en tu historial.
