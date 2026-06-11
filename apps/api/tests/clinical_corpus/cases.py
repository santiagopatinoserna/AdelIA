"""Synthetic clinical cases with ground truth.

A ground-truth Finding is matched leniently: an extracted entity satisfies it
when its type matches AND any of the `name_contains` substrings appears
(case-insensitive) in the entity name or its raw_quote. This tolerates
phrasing/coding variation while still proving the clinically-critical fact
was captured.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Finding:
    entity_type: str
    name_contains: tuple[str, ...]  # any-of, case-insensitive
    why: str  # why this fact matters clinically (for the failure message)


@dataclass(frozen=True)
class ClinicalCase:
    slug: str
    title: str
    body: str
    must_find: list[Finding] = field(default_factory=list)


CASES: list[ClinicalCase] = [
    ClinicalCase(
        slug="endo-diabetes-dyslipidemia",
        title="Endocrinology lab panel — uncontrolled T2DM + dyslipidemia",
        body="""SERVICIO DE ENDOCRINOLOGIA — INFORME DE ANALITICA

Paciente: Marta Ruiz Gomez    Edad: 58    Sexo: F
Fecha de extraccion: 2024-11-12    N. Historia: 884213

MOTIVO: Control de diabetes mellitus tipo 2 mal controlada.

RESULTADOS DE LABORATORIO
  Hemoglobina glicosilada (HbA1c) ... 9.4 %        [Ref < 7.0]
  Glucosa basal en ayunas .......... 211 mg/dL     [Ref 70-99]
  Colesterol total ................. 264 mg/dL     [Ref < 200]
  Colesterol LDL ................... 178 mg/dL     [Ref < 100]
  Colesterol HDL ................... 38 mg/dL       [Ref > 40]
  Trigliceridos .................... 290 mg/dL      [Ref < 150]
  Creatinina ....................... 1.1 mg/dL      [Ref 0.6-1.1]
  Filtrado glomerular (eGFR) ....... 68 mL/min

DIAGNOSTICOS:
  - Diabetes mellitus tipo 2 descompensada (E11.65)
  - Dislipemia mixta (E78.2)

TRATAMIENTO ACTUAL:
  - Metformina 1000 mg cada 12 horas via oral
  - Atorvastatina 40 mg cada 24 horas

PLAN: Intensificar tratamiento. Anadir inhibidor SGLT2. Revision en 3 meses.
""",
        must_find=[
            Finding("condition", ("diabetes",), "primary diagnosis driving the visit"),
            Finding("condition", ("dislipemia", "dyslipidemia"), "comorbidity to manage"),
            Finding("observation", ("hba1c", "glicosilada"), "9.4% = severely uncontrolled, the headline number"),
            Finding("observation", ("ldl",), "178 mg/dL LDL = high cardiovascular risk"),
            Finding("medication", ("metformina", "metformin"), "current antidiabetic the doctor must know about"),
            Finding("medication", ("atorvastatina", "atorvastatin"), "current statin"),
        ],
    ),
    ClinicalCase(
        slug="cardio-afib-anticoag",
        title="Cardiology discharge — new atrial fibrillation on anticoagulation",
        body="""HOSPITAL UNIVERSITARIO — INFORME DE ALTA — CARDIOLOGIA

Paciente: Jose Antonio Lopez    Edad: 71    Sexo: M
Fecha de ingreso: 2024-09-02    Fecha de alta: 2024-09-06

MOTIVO DE INGRESO: Palpitaciones y disnea de 48 horas de evolucion.

DIAGNOSTICO PRINCIPAL:
  Fibrilacion auricular de novo con respuesta ventricular rapida (I48.0)

DIAGNOSTICOS SECUNDARIOS:
  - Hipertension arterial esencial (I10)
  - Insuficiencia cardiaca con FEVI preservada

CHA2DS2-VASc: 4 puntos. HAS-BLED: 2 puntos.

EXPLORACIONES:
  ECG: fibrilacion auricular a 142 lpm al ingreso.
  Ecocardiograma: FEVI 55%, auricula izquierda dilatada.

TRATAMIENTO AL ALTA:
  - Apixaban 5 mg cada 12 horas (anticoagulacion oral)
  - Bisoprolol 5 mg cada 24 horas
  - Enalapril 10 mg cada 24 horas

ALERGIAS: No conocidas.

RECOMENDACIONES: Control en consulta de cardiologia en 4 semanas.
""",
        must_find=[
            Finding("condition", ("fibrilacion", "fibrillation", "afib"), "the new, actionable diagnosis"),
            Finding("condition", ("hipertension", "hypertension"), "comorbidity affecting management"),
            Finding("medication", ("apixaban",), "anticoagulant — bleeding risk, NEVER miss before any procedure"),
            Finding("medication", ("bisoprolol",), "rate control beta-blocker"),
        ],
    ),
    ClinicalCase(
        slug="primary-care-allergy-interaction",
        title="Primary care note — penicillin allergy + dangerous drug pair",
        body="""CENTRO DE SALUD — NOTA DE CONSULTA — MEDICINA DE FAMILIA

Paciente: Carmen Diaz    Edad: 64    Sexo: F    Fecha: 2024-10-21

MOTIVO: Dolor lumbar mecanico de 1 semana.

ANTECEDENTES:
  - Alergia a la PENICILINA (reaccion: urticaria generalizada, grave)
  - Fibrilacion auricular en tratamiento con WARFARINA (Sintrom) 4 mg/dia
  - Hipotiroidismo en tratamiento con levotiroxina 75 mcg/dia

EXPLORACION: Contractura paravertebral lumbar. Sin signos de alarma.

JUICIO CLINICO: Lumbalgia mecanica aguda.

PLAN:
  Se pauta IBUPROFENO 600 mg cada 8 horas durante 5 dias.

NOTA DE SEGURIDAD: ATENCION — el paciente toma warfarina; el ibuprofeno
incrementa el riesgo de sangrado. Reconsiderar analgesia (paracetamol).
""",
        must_find=[
            Finding("allergy", ("penicilina", "penicillin"), "allergy — prescribing a beta-lactam could be fatal"),
            Finding("medication", ("warfarina", "warfarin", "sintrom"), "anticoagulant in a dangerous pair with the new NSAID"),
            Finding("medication", ("ibuprofeno", "ibuprofen"), "newly prescribed NSAID — the interaction trigger"),
            Finding("condition", ("hipotiroidismo", "hypothyroid"), "chronic condition on the problem list"),
        ],
    ),
    ClinicalCase(
        slug="pediatric-visit",
        title="Pediatric visit — asthma + immunizations",
        body="""CONSULTA DE PEDIATRIA — INFORME DE REVISION

Paciente: Diego Fernandez    Edad: 7 anos    Sexo: M    Fecha: 2024-08-14

MOTIVO: Revision del nino sano y control de asma.

PROBLEMAS ACTIVOS:
  - Asma bronquial alergico (J45.0), buen control con corticoide inhalado.

MEDICACION:
  - Budesonida inhalada 200 mcg cada 12 horas
  - Salbutamol inhalado a demanda si sintomas

VACUNAS ADMINISTRADAS HOY:
  - Vacuna triple virica (sarampion, rubeola, parotiditis) — segunda dosis
  - Vacuna frente a varicela — segunda dosis

ALERGIAS: Alergia a acaros del polvo confirmada por prick test.

EXPLORACION: Auscultacion pulmonar normal. Peso y talla en percentil 60.

PLAN: Continuar tratamiento de base. Proxima revision en 6 meses.
""",
        must_find=[
            Finding("condition", ("asma", "asthma"), "the chronic condition under control"),
            Finding("medication", ("budesonida", "budesonide"), "controller inhaler"),
            Finding("immunization", ("triple virica", "sarampion", "mmr", "varicela"), "vaccines given today — record for the schedule"),
        ],
    ),
]
