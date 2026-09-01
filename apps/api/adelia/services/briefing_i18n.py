"""Briefing template labels per locale (es/en/fr).

The Jinja templates render with `labels` in context; payload.locale picks
the set. The QA pre-baker uses QA_LANGUAGE to instruct the LLM. Single
source of truth shared by the HTML render and the M6 PDF (same template).
"""

LABELS: dict[str, dict[str, str]] = {
    "en": {
        "lang": "en",
        "age_unknown": "age not recorded",
        "sex_unknown": "sex not recorded",
        "month": "month",
        "months": "months",
        "year": "year",
        "years": "years",
        "sex_m": "boy",
        "sex_f": "girl",
        "generated": "Generated",
        "target_specialty": "Target specialty",
        "reason_for_consult": "Reason for consult",
        "active_problems": "Active problems",
        "no_active_problems": "No active problems recorded.",
        "onset": "onset",
        "medications": "Current medications",
        "no_medications": "No current medications recorded.",
        "since": "since",
        "allergies": "Allergies",
        "no_known_allergies": "No known allergies.",
        "immunizations": "Immunizations",
        "no_immunizations": "No immunizations on file.",
        "procedures": "Procedures",
        "no_procedures": "No procedures recorded.",
        "family_history": "Family history",
        "no_family_history": "No family history recorded.",
        "relevant_observations": "Relevant observations",
        "no_observations": "No relevant observations recorded.",
        "open_questions": "Open questions (Q&A pre-baker)",
        "no_open_questions": "No pre-baked questions generated.",
        "evidence": "📘 Clinical evidence consulted",
        "source": "source",
        "disclaimer": (
            "AI-generated briefing. Verify all clinical findings with the source "
            "documents. AdelIA is a personal documentation tool, not a medical device."
        ),
    },
    "es": {
        "lang": "es",
        "age_unknown": "edad no registrada",
        "sex_unknown": "sexo no registrado",
        "month": "mes",
        "months": "meses",
        "year": "año",
        "years": "años",
        "sex_m": "niño",
        "sex_f": "niña",
        "generated": "Generado",
        "target_specialty": "Especialidad destino",
        "reason_for_consult": "Motivo de consulta",
        "active_problems": "Problemas activos",
        "no_active_problems": "Sin problemas activos registrados.",
        "onset": "inicio",
        "medications": "Medicación actual",
        "no_medications": "Sin medicación actual registrada.",
        "since": "desde",
        "allergies": "Alergias",
        "no_known_allergies": "Sin alergias conocidas.",
        "immunizations": "Vacunación",
        "no_immunizations": "Sin vacunas registradas.",
        "procedures": "Procedimientos",
        "no_procedures": "Sin procedimientos registrados.",
        "family_history": "Antecedentes familiares",
        "no_family_history": "Sin antecedentes familiares registrados.",
        "relevant_observations": "Observaciones relevantes",
        "no_observations": "Sin observaciones relevantes registradas.",
        "open_questions": "Preguntas abiertas (Q&A pre-generadas)",
        "no_open_questions": "Sin preguntas pre-generadas.",
        "evidence": "📘 Evidencia clínica consultada",
        "source": "fuente",
        "disclaimer": (
            "Briefing generado por IA. Verifica todos los hallazgos clínicos con los "
            "documentos fuente. AdelIA es una herramienta de documentación personal, "
            "no un producto sanitario."
        ),
    },
    "fr": {
        "lang": "fr",
        "age_unknown": "âge non renseigné",
        "sex_unknown": "sexe non renseigné",
        "month": "mois",
        "months": "mois",
        "year": "an",
        "years": "ans",
        "sex_m": "garçon",
        "sex_f": "fille",
        "generated": "Généré",
        "target_specialty": "Spécialité cible",
        "reason_for_consult": "Motif de consultation",
        "active_problems": "Problèmes actifs",
        "no_active_problems": "Aucun problème actif enregistré.",
        "onset": "début",
        "medications": "Traitements en cours",
        "no_medications": "Aucun traitement en cours enregistré.",
        "since": "depuis",
        "allergies": "Allergies",
        "no_known_allergies": "Aucune allergie connue.",
        "immunizations": "Vaccinations",
        "no_immunizations": "Aucune vaccination enregistrée.",
        "procedures": "Procédures",
        "no_procedures": "Aucune procédure enregistrée.",
        "family_history": "Antécédents familiaux",
        "no_family_history": "Aucun antécédent familial enregistré.",
        "relevant_observations": "Observations pertinentes",
        "no_observations": "Aucune observation pertinente enregistrée.",
        "open_questions": "Questions ouvertes (Q&A pré-générées)",
        "no_open_questions": "Aucune question pré-générée.",
        "evidence": "📘 Évidence clinique consultée",
        "source": "source",
        "disclaimer": (
            "Briefing généré par IA. Vérifiez tous les éléments cliniques avec les "
            "documents sources. AdelIA est un outil de documentation personnelle, "
            "pas un dispositif médical."
        ),
    },
}

# Language line injected into the QA pre-baker system prompt.
QA_LANGUAGE: dict[str, str] = {
    "es": "Write all questions and answers in Spanish.",
    "en": "Write all questions and answers in English.",
    "fr": "Write all questions and answers in French.",
}


def briefing_labels(locale: str) -> dict[str, str]:
    return LABELS.get(locale, LABELS["es"])


def qa_language(locale: str) -> str:
    return QA_LANGUAGE.get(locale, QA_LANGUAGE["es"])
