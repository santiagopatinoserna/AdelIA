"""Tool execution for the /dashboard agent.

Every clinical tool here now takes the patient's age and sex from the active
Profile rather than from whatever the model typed, and the answering tool
carries its citations back out instead of stripping them (audit 3.5, 3.7,
3.9). `facts` is resolved once per turn by agent/orchestrator and threaded
through, so a tool never opens a session to ask how old the baby is.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4

from adelia.agent import cards
from adelia.agent.pediatrics import (
    calendar_meta,
    due_vaccines,
    growth_percentile,
    resolve_country,
)
from adelia.clinical.red_flags import FEVER_AGE_LIMIT_MONTHS, FEVER_THRESHOLD_C
from adelia.enrichment.drug_interactions import check_interactions
from adelia.enrichment.lab_ranges import evaluate as evaluate_lab
from adelia.enrichment.profile_service import UNKNOWN_PROFILE, ProfileFacts
from adelia.enrichment.trial_matcher import match_for_patient
from adelia.services.answer_contract import red_flag_reply
from adelia.services.chat_orchestrator import answer_question_streaming


@dataclass
class ToolOutcome:
    text: str
    card: dict | None = None
    #: Patient-record citations, `[N]` in `text` (audit 3.7). Same dict shape
    #: the chat's SSE `final` event uses, so one renderer serves both.
    citations: list[dict] = field(default_factory=list)
    #: Clinical-guideline citations, `[ev_N]` in `text`.
    evidence_citations: list[dict] = field(default_factory=list)


def _cid() -> str:
    return uuid4().hex[:12]


_TEMPERATURE_ALIASES = ("temperatura", "temperature", "body temp", "fiebre", "fievre")


def _is_temperature(name: str) -> bool:
    lowered = (name or "").lower()
    return any(alias in lowered for alias in _TEMPERATURE_ALIASES)


async def _immunization_names(user_id: UUID, profile_id: UUID | None) -> list[str]:
    """The child's recorded vaccines, as extracted from their own card.

    Best effort: a DB hiccup must not turn into "every vaccine is overdue",
    which is the failure mode item 3.9 exists to remove, so an error returns
    an empty list AND the caller degrades to "pending" rather than "overdue"
    (see the `record_seen` flag below).
    """
    from sqlalchemy import select

    from adelia.db import AsyncSessionLocal
    from adelia.models import Entity
    from adelia.services.scope import Scope

    # Scope, not a bare equality: a strict `profile_id == pid` drops every row
    # written before profiles existed, and an empty list here reads as "no
    # vaccine on record", which is how a correctly vaccinated child gets every
    # dose marked pending (audit 3.9, 4.1).
    stmt = (
        select(Entity.name)
        .where(*Scope(user_id=user_id, profile_id=profile_id).where(Entity))
        .where(Entity.entity_type == "immunization")
        .where(Entity.deleted_at.is_(None))
        .limit(200)
    )
    async with AsyncSessionLocal() as session:
        result = await session.execute(stmt)
        return [row[0] for row in result.all() if row[0]]


async def execute_tool(
    name: str,
    args: dict,
    *,
    user_id: UUID,
    profile_id: UUID | None,
    locale: str = "es",
    facts: ProfileFacts | None = None,
) -> ToolOutcome:
    facts = facts or UNKNOWN_PROFILE

    if name == "buscar_en_expediente":
        parts: list[str] = []
        citations: list[dict] = []
        evidence: list[dict] = []
        async for ev in answer_question_streaming(
            user_id=user_id,
            question=args["query"],
            locale=locale,
            age_months=facts.age_months,
            # Same child the rest of the turn is about (audit 4.1). `facts`
            # carries the RESOLVED id, so a turn with no explicit profile
            # still searches the default profile's record and not both
            # children's.
            profile_id=facts.profile_id,
        ):
            if ev.type == "token":
                parts.append(ev.content)
            elif ev.type == "final":
                citations = [c.model_dump(mode="json") for c in ev.citations]
                evidence = list(ev.evidence_citations)
        text = "".join(parts).strip()
        # The markers survive now. Week 1 stripped them because AgentEvent had
        # no citations field and the canvas painted plain text, so every
        # [ev_1] on /dashboard pointed at nothing. Item 3.7 gave the agent's
        # SSE both citation namespaces and the canvas the same evidence card
        # the chat uses, so a marker here reaches something real.
        return ToolOutcome(
            text=text or "No encontré datos relevantes.",
            citations=citations,
            evidence_citations=evidence,
        )

    if name == "evaluar_labs":
        return _evaluate_lab_tool(args, facts=facts, locale=locale)

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
        return _growth_tool(args, facts=facts)

    if name == "proximas_vacunas":
        return await _vaccines_tool(args, user_id=user_id, profile_id=profile_id,
                                    facts=facts, locale=locale)

    if name == "generar_briefing":
        # WRITE tool: never executed here — orchestrator intercepts and emits a confirm card.
        return ToolOutcome(text="(pendiente de confirmación)")

    if name == "completar_perfil":
        return ToolOutcome(text="(pendiente de confirmación)")

    return ToolOutcome(text=f"Herramienta desconocida: {name}")


_NO_AGE = (
    "No puedo interpretar {name} = {value} sin saber la edad: en pediatría el "
    "rango de referencia cambia cada pocos meses y el de un adulto no vale para "
    "un bebé. Dime la fecha de nacimiento y lo valoro; mientras tanto, coméntalo "
    "con su pediatra."
)
_NO_BAND = (
    "No tengo un rango de referencia pediátrico para {name} a los {age} meses, así "
    "que no voy a interpretarlo: aplicarle el de un adulto daría un resultado "
    "equivocado. Llévaselo a su pediatra, que lo valora con su edad y su peso."
)


def _evaluate_lab_tool(args: dict, *, facts: ProfileFacts, locale: str) -> ToolOutcome:
    """A value is interpreted only against the band for this child's age.

    Hard rule, and it comes before everything else: a temperature of 38 C or
    more in a baby under 3 months never produces an informative card. NICE
    NG143 1.2.12 puts that child in the high-risk group, and the card is
    painted straight to the screen without passing the model, so a card here
    would be the app itself telling a parent that a red flag is a data point.
    It produces the referral instead (audit 3.5).
    """
    raw_name = str(args.get("name", ""))
    value = args.get("value")
    age = facts.age_months

    if age is not None and age < FEVER_AGE_LIMIT_MONTHS and _is_temperature(raw_name):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = None
        if numeric is not None and numeric >= FEVER_THRESHOLD_C:
            return ToolOutcome(text=red_flag_reply("fever_under_3_months", locale))

    if age is None:
        return ToolOutcome(text=_NO_AGE.format(name=raw_name, value=value))

    status = evaluate_lab(raw_name, value, age_months=age, sex=facts.sex if facts.sex in ("M", "F") else None)
    if status is None:
        return ToolOutcome(text=_NO_BAND.format(name=raw_name, age=age))

    bounds = [b for b in (status.range.low, status.range.high) if b is not None]
    range_str = " a ".join(str(b) for b in bounds) if bounds else "sin rango"
    # The card names the band and the guideline behind it, because "normal"
    # with no age attached is the claim that was wrong before.
    body = f"{status.interpretation}. Fuente: {status.range.source}"
    return ToolOutcome(
        text=body,
        card=cards.card_lab(
            _cid(),
            status.canonical_name,
            status.value,
            status.unit,
            status.flag,
            f"{range_str} {status.unit} (banda {status.range.age_band})",
            body,
        ),
    )


def _growth_tool(args: dict, *, facts: ProfileFacts) -> ToolOutcome:
    """Age and sex come from the profile; the model may only fill the gaps."""
    age = args.get("age_months")
    age = facts.age_months if facts.age_months is not None else age
    sex = facts.sex if facts.sex in ("M", "F") else args.get("sex")
    if age is None or sex not in ("M", "F"):
        return ToolOutcome(text=(
            "Para calcular el percentil necesito la fecha de nacimiento y el sexo del "
            "bebé. Guárdalos en su perfil y lo calculo."
        ))
    p = growth_percentile(metric=args["metric"], value=args["value"],
                          age_months=int(age), sex=sex)
    if p is None:
        return ToolOutcome(text="No pude calcular el percentil (fuera de tabla).")
    metric_es = "peso" if args["metric"] == "weight" else "talla"
    body = f"El {metric_es} está en el percentil {p} para {age} meses."
    tone = "warn" if p < 3 or p > 97 else "positive"
    return ToolOutcome(text=body, card=cards.card_insight(_cid(), "Percentil de crecimiento", body, tone=tone))


async def _vaccines_tool(
    args: dict, *, user_id: UUID, profile_id: UUID | None, facts: ProfileFacts, locale: str
) -> ToolOutcome:
    age = facts.age_months if facts.age_months is not None else args.get("age_months")
    if age is None:
        return ToolOutcome(text=(
            "Para decirte qué vacunas tocan necesito la fecha de nacimiento del bebé. "
            "Guárdala en su perfil y te lo digo."
        ))
    country = resolve_country(args.get("country"), locale)
    try:
        administered = await _immunization_names(user_id, profile_id)
        record_seen = True
    except Exception:  # noqa: BLE001 - never turn a DB error into a false alarm
        administered, record_seen = [], False

    due = due_vaccines(age_months=int(age), country=country, administered=administered)
    meta = calendar_meta(country)
    calendar_line = f" Calendario usado: {meta.get('calendar', country)}." if meta else ""

    if not due:
        return ToolOutcome(text=(
            f"Según su cartilla no le falta ninguna vacuna y no tiene ninguna en los "
            f"próximos {2} meses.{calendar_line}"
        ))

    upcoming = [d for d in due if d["status"] == "due"]
    late = [d for d in due if d["status"] == "overdue"]
    lines: list[str] = []
    if upcoming:
        lines.append("Próximas: " + ", ".join(f"{d['name']} (a los {d['due_month']} meses)" for d in upcoming))
    if late:
        if record_seen:
            lines.append(
                "Sin registro en su cartilla, y ya tocaban: "
                + ", ".join(f"{d['name']} (a los {d['due_month']} meses)" for d in late)
                + ". Si están puestas y no constan, es que falta subir la cartilla."
            )
        else:
            lines.append(
                "No he podido leer su cartilla ahora mismo, así que no puedo confirmar "
                "si estas ya están puestas: "
                + ", ".join(d["name"] for d in late)
            )
    body = " ".join(lines) + calendar_line
    tone = "warn" if (late and record_seen) else "neutral"
    return ToolOutcome(text=body, card=cards.card_insight(_cid(), "Vacunas", body, tone=tone))
