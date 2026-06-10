---
slug: mon-espace-sante-fr
title: Mon Espace Santé (Francia)
description: Descarga tus documentos médicos desde Mon Espace Santé (DMP/INS) e impórtalos a AdelIA.
estimated_time: 15-20 minutos
device: Navegador web o app Mon Espace Santé
output_format: PDF (uno por documento)
---

# Importar desde Mon Espace Santé (Francia)

Mon Espace Santé es el portal sanitario francés operado por l'Assurance Maladie. Centraliza tu Dossier Médical Partagé (DMP) con informes hospitalarios, recetas, resultados de laboratorio y vacunación.

A diferencia de MyChart, Mon Espace Santé **no exporta CCD estructurado** — solo PDFs individuales. Pero AdelIA los procesa con OCR (M2) y extrae entities automáticamente.

## Pre-requisitos

- Cuenta activa en [monespacesante.fr](https://monespacesante.fr)
- Identifiant ID France (FranceConnect) o credenciales directas

## Pasos

### 1. Inicia sesión en monespacesante.fr

Usa FranceConnect (recomendado) o tus credenciales directas de l'Assurance Maladie.

### 2. Ve a "Mon dossier médical" → "Mes documents"

Verás la lista completa de documentos cargados por tus médicos, hospitales, laboratorios.

### 3. Descarga cada documento como PDF

**Importante:** Mon Espace Santé NO ofrece descarga masiva en v0.1 — debes descargar uno por uno. Workaround:

- Filtra por fecha (últimos 6 meses → 1 año → todo)
- Filtra por tipo (Comptes-rendus → Résultats biologiques → Vaccinations)
- Para cada documento: clic → "Télécharger" → guardar PDF

**Time estimate**: 1-2 min por documento × 10-30 documentos típicos = 15-30 min total.

### 4. Sube los PDFs a AdelIA en batch

1. Dashboard → **Subir archivo** (no Importar — Importar es para formatos estructurados)
2. Selecciona TODOS los PDFs juntos (Cmd+A en la carpeta)
3. AdelIA los procesa secuencialmente con OCR (Mistral) + entity extraction
4. Cada uno toma 30-60s. Para 20 documentos: ~10-20 min en background.

### 5. Verifica entities extraídas

Cuando termine el procesamiento (badge "Listo" en el dashboard):

- Abre **Modo A — Chat** y pregunta: *"¿Qué medicamentos he tomado en 2024?"* o *"¿Cuándo fue mi última vacuna?"*

## Qué documentos típicamente exporta Mon Espace Santé

| Tipo de documento | OCR-friendly | Notas |
|-------------------|-------------|-------|
| Compte-rendu de consultation | ✅ Alto | Tu médico generalista |
| Compte-rendu d'hospitalisation | ✅ Alto | Reciente del hospital |
| Résultats de biologie (analyses) | ⚠️ Medio | OCR puede confundir números — verifica HbA1c, glucosa, lípidos |
| Imagerie (radio, écho, scanner) | ⚠️ Bajo | Solo el reporte textual; las imágenes en sí no se procesan en v0.1 |
| Vaccinations | ✅ Alto | Lista estructurada |
| Ordonnances (prescripciones) | ✅ Alto | Medicación con dosis |
| Certificats médicaux | ⚠️ Variable | Depende del formato |

## Alternativa: API FHIR (v0.3+)

Mon Espace Santé expone una API FHIR R4 para apps autorizadas. AdelIA la integrará en v0.3 (requiere aprobación del Ministerio de la Salud francés + autenticación INS). Hasta entonces, el workflow manual de exportar PDFs es la vía.

## Solución de problemas

**Algunos documentos no aparecen aunque visité al médico:**
Mon Espace Santé requiere que tu médico opte activamente por subir documentos. No es automático. Pídele explícitamente: "Pouvez-vous déposer le compte-rendu sur mon Espace Santé ?"

**El OCR confunde valores numéricos en los análisis:**
v0.1 usa Mistral OCR. Si detectas errores en HbA1c o glucosa, abre el documento en AdelIA → entity detail → flag "needs review" (M5 puede mostrar esto en briefing). v0.1.1 añadirá UI manual de corrección.

## Próximos pasos

- Crea un **Briefing** filtrado por la especialidad del próximo médico (e.g. "Cardiologie" si vas al cardiólogo). AdelIA pre-baka las 5 preguntas más probables.
- Si tienes hijos también con Mon Espace Santé, en v0.3 podrás gestionar multi-perfil. Hasta entonces, una cuenta AdelIA por persona.
