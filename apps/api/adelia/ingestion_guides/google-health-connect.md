---
slug: google-health-connect
title: Google Health Connect / Google Takeout
description: Exporta tu data de salud de Google Health Connect (Android) o servicios Google vía Takeout.
estimated_time: 10-30 minutos (Takeout puede tardar horas)
device: Android (Health Connect) o navegador web (Takeout)
output_format: JSON + CSV (vía Takeout)
---

# Importar desde Google Health Connect / Google Takeout

Google Health Connect es la API unificada de Android para apps de salud (Samsung Health, Fitbit, MyFitnessPal, etc.). Google Takeout permite descargar **toda** tu data de Google, incluida la de Health Connect.

## Pre-requisitos

- Cuenta Google con apps de salud conectadas (Health Connect on Android)
- Acceso a [takeout.google.com](https://takeout.google.com)

## Opción A: Google Takeout (recomendado, todo desde web)

### 1. Abre [takeout.google.com](https://takeout.google.com)

Inicia sesión con tu cuenta Google.

### 2. Selecciona los productos a exportar

Por defecto Takeout exporta TODO. Para AdelIA, deselecciona todo y marca solo:
- **Health Connect** (si lo tienes activado)
- **Fit** (Google Fit, deprecated pero aún funciona si tienes data antigua)

### 3. Click "Next step" → Elige formato

- **File type**: ZIP
- **File size**: 2 GB (si tienes menos data) o 50 GB (si tienes mucha)
- **Delivery method**: Email link (recomendado) o Google Drive

### 4. Click "Create export"

Google empieza a empaquetar. Esto puede tardar **minutos a varias horas** dependiendo del volumen. Recibirás un email cuando esté listo.

### 5. Descarga el ZIP

Cuando llegue el email, descarga el archivo. Dentro encontrarás:
- `Takeout/Fit/All Data/` — CSVs de actividad, peso, frecuencia cardíaca
- `Takeout/Health Connect/` — JSON con datos estructurados

### 6. Sube los CSVs/JSONs a AdelIA

1. Dashboard → **Importar → Google Health Connect**
2. Arrastra el ZIP entero (o los archivos descomprimidos)
3. AdelIA parsea los CSV/JSON y crea entities tipo `observation`

## Opción B: Health Connect app directa (Android)

Si solo tienes Android y quieres exportar de la app:

### 1. Abre Settings → Apps → Health Connect

### 2. Toca "Export data"

Health Connect creará un backup ZIP en tu Downloads.

### 3. Transfiere a tu ordenador y sube a AdelIA

Igual que opción A paso 6.

## Qué se importa en v0.1

| Tipo Google Health | Se importa | Notas |
|--------------------|-----------|-------|
| Pasos | ✅ | Series temporal |
| Frecuencia cardíaca | ✅ | |
| Peso | ✅ | |
| Calorías | ✅ | |
| Glucosa (si app conectada) | ✅ | |
| Presión arterial | ✅ | |
| Sueño | ✅ | |
| Hidratación, nutrición | ⏳ v0.1.1 | |
| Actividades específicas (correr, ciclismo) | ⏳ v0.1.1 | |

## Limitaciones conocidas

- **Google Fit está deprecated** — Google migró todo a Health Connect en 2024. Si tu data antigua está solo en Fit, exporta con Takeout antes de que Google la borre.
- **Health Connect requiere apps conectadas** — si no usabas Samsung Health, Fitbit, MyFitnessPal, etc. con Android, Health Connect estará vacío.

## Solución de problemas

**Takeout tarda más de 24 horas:**
Es normal para historiales grandes. Espera hasta 48h. Si pasan más, vuelve a crear el export.

**No tengo Google Health Connect ni Fit:**
Si usas Fitbit standalone, ve a la guía de **Fitbit** (v0.1.1). Mientras tanto, exporta desde la web de Fitbit Account → Settings → Data Export, y abre un issue para priorizar el parser.

## Próximos pasos

- En **Modo A**, pregunta: *"¿Cuántos pasos he dado en promedio este año?"* o *"¿Cómo ha evolucionado mi frecuencia cardíaca en reposo?"*
- En **Modo B Briefing**, los datos de actividad complementan el contexto para cardiología o medicina general.
