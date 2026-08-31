from __future__ import annotations
import re
from dataclasses import dataclass
from uuid import UUID, uuid4

from adelia.agent import cards
from adelia.agent.pediatrics import growth_percentile, due_vaccines
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
        sources: list[str] = []
        async for ev in answer_question_streaming(user_id=user_id, question=args["query"], locale=locale):
            if ev.type == "token":
                parts.append(ev.content)
            elif ev.type == "final":
                # The terminal event was being discarded, citations included.
                sources = [
                    " ".join(
                        str(x)
                        for x in (c.get("organization"), c.get("title"), c.get("year"))
                        if x
                    )
                    for c in ev.evidence_citations
                ]
        # /dashboard paints m.content as plain text: agent-canvas has no
        # citation card and AgentEvent carries no citation field, so a [ev_1]
        # arriving here is an orphan marker on the screen the parent lands on.
        # The answer contract demands markers because the CHAT renders them;
        # on this surface the source is named in prose instead, from the line
        # below (answer_contract.agent_system_prompt says so explicitly).
        # Propagating the citations properly is audit item 3.7, week 3.
        text = re.sub(r"\[(?:ev_)?\d+\]", "", "".join(parts)).strip()
        if sources:
            text += "\n\nFuentes citables (nómbralas en el texto): " + "; ".join(sources)
        return ToolOutcome(text=text or "No encontré datos relevantes.")

    if name == "evaluar_labs":
        # lab_ranges v0.1 are ADULT ranges (enrichment/lab_ranges.py:5-7 says
        # so) and evaluate() takes no age, so on a baby the card was wrong in
        # both directions: false alarm (140 bpm -> "tachycardia" against
        # 60-100, normal in an infant; Hb 10,5 -> "low" against 12,0-17,5,
        # normal at 6 months) and false reassurance (38,0 C -> "low_grade
        # fever", when in an infant under 3 months that is same-day
        # assessment). The card is emitted straight to the screen without
        # passing the model (agent/orchestrator.py, the `outcome.card` yield),
        # so no clause of answer_contract can correct it, and it carries
        # neither [ev_N] nor a disclaimer. No card until the reference bands
        # are stratified by age (audit 3.5).
        return ToolOutcome(text=(
            f"No puedo interpretar {args['name']} = {args['value']}: mis rangos de "
            "referencia son de adulto y no sirven para un bebé. Coméntalo con su "
            "pediatra, que valora el dato con su edad y su peso."
        ))

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
