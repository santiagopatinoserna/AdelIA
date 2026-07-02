from adelia.agent.tools import TOOLS, is_write_tool, tool_names

def test_core_tools_present():
    names = tool_names()
    for n in ["buscar_en_expediente", "evaluar_labs", "revisar_interacciones",
              "buscar_ensayos", "generar_briefing", "completar_perfil",
              "percentil_crecimiento", "proximas_vacunas"]:
        assert n in names

def test_write_classification():
    assert is_write_tool("generar_briefing") is True
    assert is_write_tool("completar_perfil") is True
    assert is_write_tool("buscar_en_expediente") is False

def test_schema_shape():
    for t in TOOLS:
        assert {"name", "description", "input_schema"} <= set(t)
        assert t["input_schema"]["type"] == "object"
