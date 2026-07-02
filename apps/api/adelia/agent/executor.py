from __future__ import annotations
from dataclasses import dataclass
from uuid import UUID, uuid4

from adelia.agent import cards
from adelia.agent.pediatrics import growth_percentile, due_vaccines
from adelia.enrichment.lab_ranges import evaluate as lab_evaluate
from adelia.enrichment.drug_interactions import check_interactions
from adelia.enrichment.trial_matcher import match_for_patient
from adelia.services.chat_orchestrator import answer_question_streaming

@dataclass
class ToolOutcome:
    text: str
    card: dict | None = None

def _cid() -> str:
    return uuid4().hex[:12]

async def execute_tool(name: str, args: dict, *, user_id: UUID, profile_id: UUID | None,
                       locale: str = "es") -> ToolOutcome:
    if name == "buscar_en_expediente":
        parts: list[str] = []
        async for ev in answer_question_streaming(user_id=user_id, question=args["query"], locale=locale):
            if ev.type == "token":
                parts.append(ev.content)
        return ToolOutcome(text="".join(parts) or "No encontré datos relevantes.")

    if name == "evaluar_labs":
        r = lab_evaluate(args["name"], args["value"])
        if r is None:
            return ToolOutcome(text=f"No tengo rango de referencia para {args['name']}.")
        # r.range is a ReferenceRange dataclass (not JSON-serializable) — format to a string
        # so the card survives json.dumps in the /agent router.
        range_str = f"{r.range.low}-{r.range.high}"
        card = cards.card_lab(_cid(), r.canonical_name, r.value, r.unit, r.flag, range_str, r.interpretation)
        return ToolOutcome(text=f"{r.canonical_name}: {r.value} {r.unit} ({r.interpretation}).", card=card)

    if name == "revisar_interacciones":
        found = check_interactions(args["medicamentos"])
        if not found:
            return ToolOutcome(text="No detecté interacciones conocidas.")
        top = found[0]
        body = f"{top.drug_a} + {top.drug_b}: {top.recommendation}"
        return ToolOutcome(text=f"{len(found)} interacción(es). {body}",
                           card=cards.card_insight(_cid(), "Interacción detectada", body, tone="warn"))

    if name == "buscar_ensayos":
        res = await match_for_patient(conditions=[args["condition"]], country=args.get("country"))
        trials = res.get(args["condition"], [])
        if not trials:
            return ToolOutcome(text="No encontré ensayos que coincidan.")
        body = "; ".join(getattr(t, "title", "") for t in trials[:3])
        return ToolOutcome(text=f"{len(trials)} ensayo(s).",
                           card=cards.card_insight(_cid(), "Ensayos clínicos", body))

    if name == "percentil_crecimiento":
        p = growth_percentile(metric=args["metric"], value=args["value"],
                              age_months=args["age_months"], sex=args["sex"])
        if p is None:
            return ToolOutcome(text="No pude calcular el percentil (fuera de tabla).")
        metric_es = "peso" if args["metric"] == "weight" else "talla"
        body = f"El {metric_es} está en el percentil {p}."
        tone = "warn" if p < 3 or p > 97 else "positive"
        return ToolOutcome(text=body, card=cards.card_insight(_cid(), "Percentil de crecimiento", body, tone=tone))

    if name == "proximas_vacunas":
        due = due_vaccines(age_months=args["age_months"])
        if not due:
            return ToolOutcome(text="No hay vacunas pendientes próximas.")
        body = ", ".join(d["name"] for d in due)
        overdue = any(d["overdue"] for d in due)
        return ToolOutcome(text=f"Próximas vacunas: {body}",
                           card=cards.card_insight(_cid(), "Vacunas", body, tone="warn" if overdue else "neutral"))

    if name == "generar_briefing":
        # WRITE tool: never executed here — orchestrator intercepts and emits a confirm card.
        return ToolOutcome(text="(pendiente de confirmación)")

    if name == "completar_perfil":
        return ToolOutcome(text="(pendiente de confirmación)")

    return ToolOutcome(text=f"Herramienta desconocida: {name}")
