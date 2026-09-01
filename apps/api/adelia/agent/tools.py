from __future__ import annotations

def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}

TOOLS: list[dict] = [
    {"name": "buscar_en_expediente",
     "description": "Busca en el expediente médico del perfil activo para responder una pregunta clínica. Úsalo para cualquier pregunta sobre los datos del paciente.",
     "input_schema": _obj({"query": {"type": "string", "description": "La pregunta o tema a buscar"}}, ["query"])},
    {"name": "evaluar_labs",
     "description": "Compara un valor de laboratorio o una constante (temperatura, frecuencia cardiaca, hemoglobina, leucocitos, saturación) con el rango de referencia de la EDAD del perfil activo, no con el de un adulto. La edad y el sexo los toma del perfil: no los pidas ni los inventes. Si no hay banda pediátrica para esa edad devuelve que no puede interpretarlo, y eso es la respuesta correcta.",
     "input_schema": _obj({"name": {"type": "string", "description": "Nombre del parámetro, p. ej. 'temperatura' o 'hemoglobina'"},
                           "value": {"type": "number"}}, ["name", "value"])},
    {"name": "revisar_interacciones",
     "description": "Revisa interacciones entre una lista de medicamentos.",
     "input_schema": _obj({"medicamentos": {"type": "array", "items": {"type": "string"}}}, ["medicamentos"])},
    {"name": "buscar_ensayos",
     "description": "Busca ensayos clínicos en ClinicalTrials.gov para una condición.",
     "input_schema": _obj({"condition": {"type": "string"}, "country": {"type": "string"}}, ["condition"])},
    {"name": "percentil_crecimiento",
     "description": "Calcula el percentil de peso o talla del bebé según las tablas de la OMS. La edad y el sexo salen del perfil activo; solo pásalos si el perfil no los tiene.",
     "input_schema": _obj({"metric": {"type": "string", "enum": ["weight", "height"]},
                           "value": {"type": "number"},
                           "age_months": {"type": "integer", "description": "Solo si el perfil no tiene fecha de nacimiento"},
                           "sex": {"type": "string", "enum": ["M", "F"], "description": "Solo si el perfil no tiene sexo"}},
                          ["metric", "value"])},
    {"name": "proximas_vacunas",
     "description": "Dice qué vacunas tocan en los próximos 2 meses y cuáles ya tocaban y NO constan en la cartilla del niño. Cruza el calendario del país con las vacunas que la app ya extrajo de sus documentos, así que no marca como atrasado lo que ya está puesto. La edad sale del perfil activo.",
     "input_schema": _obj({"age_months": {"type": "integer", "description": "Solo si el perfil no tiene fecha de nacimiento"},
                           "country": {"type": "string", "enum": ["ES", "FR"], "description": "País del calendario; por defecto el del idioma"}},
                          [])},
    {"name": "generar_briefing",
     "description": "Genera un briefing médico para un especialista. ACCIÓN DE ESCRITURA: se confirmará con el usuario.",
     "input_schema": _obj({"specialty": {"type": "string"}}, ["specialty"])},
    {"name": "completar_perfil",
     "description": "Guarda un dato del perfil (p.ej. fecha de nacimiento o sexo). ACCIÓN DE ESCRITURA: se confirmará.",
     "input_schema": _obj({"field": {"type": "string", "enum": ["date_of_birth", "sex", "display_name"]},
                           "value": {"type": "string"}}, ["field", "value"])},
]

WRITE_TOOLS: set[str] = {"generar_briefing", "completar_perfil"}

def is_write_tool(name: str) -> bool:
    return name in WRITE_TOOLS

def tool_names() -> set[str]:
    return {t["name"] for t in TOOLS}
