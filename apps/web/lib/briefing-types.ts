// TS shape mirror of apps/api/adelia/schemas.py BriefingPayload + related.

export type Specialty =
  | "pediatrics"
  | "endocrinology"
  | "cardiology"
  | "gynecology"
  | "gastroenterology"
  | "dermatology"
  | "general_medicine"
  | "default";

export type BriefingStatus = "processing" | "ready" | "failed";

export type Provenance = "extracted_from_clinician_doc" | "patient_stated";

export interface Citation {
  document_id: string;
  entity_id: string | null;
  raw_quote: string;
  page?: number | null;
}

export interface ProblemItem {
  name: string;
  status?: string | null;
  onset_date?: string | null;
  citations: Citation[];
  provenance: Provenance;
}

export interface MedicationItem {
  name: string;
  dose?: string | null;
  route?: string | null;
  frequency?: string | null;
  started?: string | null;
  citations: Citation[];
  provenance: Provenance;
}

export interface AllergyItem {
  substance: string;
  reaction?: string | null;
  severity?: string | null;
  citations: Citation[];
  provenance: Provenance;
}

export interface ImmunizationItem {
  name: string;
  date?: string | null;
  citations: Citation[];
  provenance: Provenance;
}

export interface ProcedureItem {
  name: string;
  date?: string | null;
  citations: Citation[];
  provenance: Provenance;
}

export interface FamilyHistoryItem {
  relation: string;
  condition: string;
  citations: Citation[];
  provenance: Provenance;
}

export interface ObservationItem {
  name: string;
  value: string;
  unit?: string | null;
  date?: string | null;
  trend?: string | null;
  citations: Citation[];
  provenance: Provenance;
}

export interface QAItem {
  question: string;
  answer: string;
  citations: Citation[];
}

export interface BriefingSections {
  reason_for_consult: string | null;
  active_problems: ProblemItem[];
  medications: MedicationItem[];
  allergies: AllergyItem[] | "no_known_allergies";
  immunizations: ImmunizationItem[] | null;
  procedures: ProcedureItem[];
  family_history: FamilyHistoryItem[] | null;
  relevant_observations: ObservationItem[];
  open_questions: QAItem[];
}

export interface BriefingPayload {
  schema_version: "1.0";
  generated_at: string;
  target_specialty: Specialty;
  patient: { name: string; age: number; sex: string };
  sections: BriefingSections;
  applied_filter: { specialty: string; rules_version: string };
  llm_meta: { model: string; tokens_used: number; cost_estimate_usd: number };
}

export interface BriefingOut {
  id: string;
  target_specialty: Specialty;
  status: BriefingStatus;
  is_stale: boolean;
  created_at: string;
  completed_at?: string | null;
  error_message?: string | null;
}

export interface BriefingDetailOut extends BriefingOut {
  payload?: BriefingPayload | null;
  html_render?: string | null;
}

export interface BriefingCreate {
  locale?: "es" | "en" | "fr";
  target_specialty: Specialty;
}

export const SPECIALTIES: { value: Specialty; labelKey: string }[] = [
  { value: "pediatrics", labelKey: "briefing.specialty.pediatrics" },
  { value: "endocrinology", labelKey: "briefing.specialty.endocrinology" },
  { value: "cardiology", labelKey: "briefing.specialty.cardiology" },
  { value: "gynecology", labelKey: "briefing.specialty.gynecology" },
  { value: "gastroenterology", labelKey: "briefing.specialty.gastroenterology" },
  { value: "dermatology", labelKey: "briefing.specialty.dermatology" },
  { value: "general_medicine", labelKey: "briefing.specialty.general_medicine" },
  { value: "default", labelKey: "briefing.specialty.default" },
];
