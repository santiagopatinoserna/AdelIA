---
slug: apple-health
title: Apple Health
description: Exporta tu historial completo de salud de Apple Health desde tu iPhone y súbelo a AdelIA.
estimated_time: 5 minutos
device: iPhone (iOS 16+)
output_format: ZIP (export.zip)
---

# Importar desde Apple Health

Apple Health almacena años de datos biométricos (peso, presión arterial, glucosa, frecuencia cardíaca, pasos, sueño…) y, si has conectado proveedores médicos a Apple Health Records, también informes clínicos. La exportación oficial de Apple incluye TODO en un archivo `export.zip`.

## Pre-requisitos

- iPhone con iOS 16 o superior
- App **Health** instalada (viene por defecto)
- Espacio de almacenamiento libre proporcional a tu historial (~50-500 MB típico)

## Pasos

### 1. Abre la app Health en tu iPhone

Toca el icono de tu **perfil** en la esquina superior derecha.

### 2. Desplázate hasta el fondo y toca "Exportar todos los datos de salud"

(En inglés: "Export All Health Data")

### 3. Confirma "Exportar"

iOS empieza a empaquetar todo tu historial. Esto puede tardar **2-10 minutos** dependiendo del volumen de datos. Puedes seguir usando otras apps mientras tanto.

### 4. Cuando termine, comparte el archivo `export.zip`

Opciones:
- **AirDrop a tu Mac** — la forma más rápida
- **Guardar en iCloud Drive** — accesible desde web
- **Enviarte por email a ti mismo** — funciona pero más lento si el archivo es grande
- **Guardar en Files (Archivos)** — y subir desde ahí

### 5. Sube el archivo a AdelIA

1. Abre AdelIA en tu navegador → **Dashboard → Importar → Apple Health**
2. Arrastra el `export.zip` (o haz clic en "Examinar")
3. AdelIA descomprime, parsea y bulk-inserta tus registros biométricos
4. Verás "Importado X.XXX observaciones" cuando termine

## Qué se importa en v0.1

| Tipo de dato Apple Health | Se importa | Notas |
|---------------------------|-----------|-------|
| Peso, altura, IMC | ✅ | Como `entity_type=observation` |
| Glucosa (CGM Dexcom, Libre, etc.) | ✅ | Series temporal completa |
| Presión arterial (sistólica + diastólica) | ✅ | Pareadas por timestamp |
| Frecuencia cardíaca | ✅ | Incluye datos de Apple Watch |
| SpO2, frecuencia respiratoria | ✅ | |
| Pasos, calorías activas, VO2 max | ✅ | Datos de actividad |
| Sueño (duración, fases) | ✅ | Estructura jerárquica |
| Apple Health Records (CDA clínicos) | ⏳ v0.1.1 | Mientras tanto, descárgalos desde la app del hospital y súbelos como PDF |
| Electrocardiogramas (ECG) | ⏳ v0.1.1 | Mientras tanto, exporta como PDF y sube |
| Datos de fertilidad | ✅ | |
| Glucosa en sangre + insulina | ✅ | Crítico para diabéticos |

## Privacidad

- El `export.zip` permanece **temporal en el navegador** hasta que confirmes la subida.
- Una vez procesado en el servidor, el ZIP se borra; solo se persisten los registros parseados como entities.
- Self-host: si corres AdelIA con `docker compose up` local, los datos nunca salen de tu máquina.

## Próximos pasos después de importar

- Abre **Modo A — Chat** y pregunta: *"¿Cuál es mi curva de glucosa en los últimos 6 meses?"* o *"¿Cómo ha evolucionado mi peso en 2 años?"*
- Crea un **Briefing** seleccionando "Endocrinología" — AdelIA detectará los datos de glucosa, HbA1c y peso para el resumen al especialista.

## Solución de problemas

**El export.zip pesa más de 500 MB y la subida falla:**
v0.1 tiene límite de 200 MB en el endpoint. Workaround: descomprime el ZIP en tu Mac, sube solo `export.xml` (sin `export_cda.xml` ni la carpeta `electrocardiograms/`). v0.1.1 añadirá chunked upload.

**No veo mis datos de Apple Health Records en AdelIA:**
v0.1 solo importa `export.xml` (biométricos). Para clínicos completos, abre la app del hospital, descarga el informe como PDF, y súbelo a AdelIA por la vía normal (dashboard → Subir archivo).
