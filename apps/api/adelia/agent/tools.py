from __future__ import annotations

def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}

TOOLS: list[dict] = [
    {"name": "buscar_en_expediente",
     "description": "Busca en el expediente médico del perfil activo para responder una pregunta clínica. Úsalo para cualquier pregunta sobre los datos del paciente.",
     "input_schema": _obj({"query": {"type": "string", "description": "La pregunta o tema a buscar"}}, ["query"])},
    {"name": "evaluar_labs",
     "description": "NO DISPONIBLE para bebés: los rangos de referencia son de adulto y no valen para un lactante. Devuelve siempre que no puede interpretarlo. No la uses; para un valor de laboratorio usa buscar_en_expediente y remite al pediatra.",
     "input_schema": _obj({"name": {"type": "string"}, "value": {"type": "number"}}, ["name", "value"])},
    {"name": "revisar_interacciones",
     "description": "Revisa interacciones entre una lista de medicamentos.",
     "input_schema": _obj({"medicamentos": {"type": "array", "items": {"type": "string"}}}, ["medicamentos"])},
    {"name": "buscar_ensayos",
     "description": "Busca ensayos clínicos en ClinicalTrials.gov para una condición.",
     "input_schema": _obj({"condition": {"type": "string"}, "country": {"type": "string"}}, ["condition"])},
    {"name": "percentil_crecimiento",
     "description": "Calcula el percentil de peso o talla de un bebé/niño según edad y sexo (tablas OMS).",
     "input_schema": _obj({"metric": {"type": "string", "enum": ["weight", "height"]},
                           "value": {"type": "number"}, "age_months": {"type": "integer"},
                           "sex": {"type": "string", "enum": ["M", "F"]}},
                          ["metric", "value", "age_months", "sex"])},
    {"name": "proximas_vacunas",
     "description": "Lista las próximas vacunas debidas según la edad del bebé/niño (calendario ES).",
     "input_schema": _obj({"age_months": {"type": "integer"}}, ["age_months"])},
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
