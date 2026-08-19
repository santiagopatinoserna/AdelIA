# Por qué la transcripción usa Mistral Voxtral y no Whisper de OpenAI

**Fecha de la prueba:** 19 de agosto de 2026
**Decisión:** seguir con `STT_PROVIDER=mistral` (Voxtral). El proveedor de OpenAI queda cableado pero inactivo.

Este documento existe porque la elección de encargado de transcripción no es un detalle técnico: es la base de lo que la DPIA (`docs/legal/dpia-grabacion-consulta.md`) y la política de privacidad publicada afirman sobre dónde se procesa el audio de una consulta pediátrica. Si algún día alguien pregunta por qué no usamos Whisper, la respuesta está aquí, con datos y no con intuición.

## Prueba

Audio de 13 segundos con dos voces (fixture `apps/api/tests/fixtures/consulta-dos-voces.wav`, generado con las voces del sistema macOS para no usar audio real de nadie). Simula una consulta pediátrica:

1. Profesional: "El peso está muy bien, en el percentil sesenta. La fiebre es normal después de la vacuna."
2. Madre: "¿Y le puedo dar **paracetamol** esta noche si sube de treinta y ocho?"
3. Profesional: "Sí, **dos mililitros cada ocho horas** como máximo."

Las dos frases que importan clínicamente son la segunda y la tercera: el nombre del fármaco y la posología.

## Resultados

| Motor | Resultado | Nombre del fármaco | Posología | Hablantes |
|---|---|---|---|---|
| **Voxtral** (`voxtral-mini-latest`) | Transcripción completa y correcta | Correcto | Correcta | **Sí, separados** |
| `gpt-4o-mini-transcribe` | Completa, con "Se" en lugar de "Y" | Correcto | Correcta | No |
| `whisper-1` | Completa, pero inventa el fármaco | **"parafetamol"** | Correcta | No |
| `gpt-4o-transcribe` | **Solo la primera frase** | Perdido | **Perdida** | No |

El fallo de `gpt-4o-transcribe` se reprodujo 3 de 3 veces, con y sin `language=es`: descarta silenciosamente las dos últimas frases, incluida la dosis. Un fallo silencioso es peor que un error visible, porque el historial queda incompleto sin que nadie lo note.

`whisper-1` da el mismo error de fármaco con y sin `language=es`.

## Conclusión

En el único punto donde una transcripción médica no puede fallar (cómo se llama la medicina y cuánta se da), Voxtral fue el único que acertó todo. Además separa hablantes, que es lo que permite distinguir lo que dijo el profesional de lo que preguntó la madre.

## Limitaciones honestas de esta prueba

- Es voz sintética limpia, no una consulta real con ruido, llanto de bebé o solapamientos. Los resultados son indicativos, no definitivos.
- Un solo audio corto y un solo idioma (español).
- No mide latencia ni coste (Voxtral ~0,06 $ por consulta de 20 minutos; `whisper-1` ~0,12 $).

Si algún día se repite la comparación con audio real de consulta, actualizar este documento y, si cambia la decisión, revisar la DPIA (el cambio de encargado es uno de sus disparadores de revisión declarados).

## Estado de OpenAI a fecha de esta prueba

- **Créditos:** disponibles desde el 19 de agosto de 2026.
- **Residencia europea:** NO activada. El endpoint `eu.api.openai.com` responde 401 "This endpoint is only accessible by projects with geography restrictions enabled". La región se fija al crear el proyecto y no se puede cambiar después, así que activar OpenAI exigiría un proyecto nuevo creado en región Europa. Usar `api.openai.com` enviaría el audio fuera de la UE y dejaría en falso lo publicado en `/{locale}/privacidad` y en la DPIA.

## Cómo reproducir

```bash
cd apps/api
MISTRAL_API_KEY=... uv run python -c "
import asyncio
from adelia.workers.transcribe import transcribe_audio
body = open('tests/fixtures/consulta-dos-voces.wav','rb').read()
print(asyncio.run(transcribe_audio(body, 'audio/wav', diarize=True)))"

# Y el proveedor de OpenAI, cuando haya proyecto con residencia europea:
OPENAI_API_KEY=... uv run python scripts/verify_stt_openai.py tests/fixtures/consulta-dos-voces.wav
```
