// TS shape mirror of v0.2 enrichment endpoints

export interface NormalizedCode {
  query: string;
  canonical_name: string | null;
  icd10: string | null;
  snomed: string | null;
  category: string | null;
  match_score: number;
}

export interface LabEvalRequest {
  name: string;
  value: number | string;
  sex?: "M" | "F" | null;
}

export interface LabEvalBulkRequest {
  observations: LabEvalRequest[];
  sex?: "M" | "F" | null;
}

export interface LabEvalResult {
  name: string;
  canonical_name?: string | null;
  value?: number | null;
  unit?: string | null;
  flag?: "low" | "normal" | "high" | null;
  zone_label?: string | null;
  interpretation?: string | null;
  range_low?: number | null;
  range_high?: number | null;
}

export interface DrugCheckRequest {
  medications: string[];
}

export type Severity = "contraindicated" | "major" | "moderate" | "minor";

export interface DrugInteraction {
  drug_a: string;
  drug_b: string;
  severity: Severity;
  mechanism: string;
  recommendation: string;
}

export interface ClinicalTrial {
  nct_id: string;
  title: string;
  brief_summary: string;
  status: string;
  phase?: string | null;
  conditions: string[];
  interventions: string[];
  locations: Array<{
    country?: string | null;
    city?: string | null;
    facility?: string | null;
    status?: string | null;
  }>;
  eligibility_age_min?: string | null;
  eligibility_age_max?: string | null;
  eligibility_sex?: string | null;
  sponsor?: string | null;
  url: string;
}

export interface VariantHit {
  rsid: string;
  gene: string;
  user_genotype: string;
  risk_alleles: string[];
  zygosity: "homozygous" | "heterozygous" | "absent";
  category: "pharmacogenomics" | "disease_risk" | "carrier_status";
  phenotype: string;
  actionability: string;
  evidence_level: string;
  url: string;
}

export type Relationship = "self" | "child" | "parent" | "spouse" | "sibling" | "other";

export interface Profile {
  id: string;
  display_name: string;
  relationship: Relationship;
  date_of_birth?: string | null;
  sex?: string | null;
  is_default: boolean;
  created_at: string;
}

export interface ProfileCreateRequest {
  display_name: string;
  relationship: Relationship;
  date_of_birth?: string | null;
  sex?: string | null;
  is_default?: boolean;
}

export interface CoverageStats {
  normalization: { total: number; [category: string]: number };
  lab_ranges_count: number;
  drugs: {
    drugs_known: number;
    aliases_total: number;
    interactions_total: number;
    by_severity: Record<string, number>;
  };
  variants: {
    variants_total: number;
    by_category: Record<string, number>;
  };
}

// M4 ingestion types
export interface GuideSummary {
  slug: string;
  title: string;
  description: string;
  estimated_time?: string | null;
}

export interface GuideContent extends GuideSummary {
  markdown: string;
  front_matter: Record<string, string>;
}

export interface GDPRTemplateSummary {
  country: string;
  authority: string;
  legal_basis: string;
  response_deadline: string;
  output_language: string;
}

export interface GDPRTemplateContent extends GDPRTemplateSummary {
  markdown: string;
}

export interface IngestionImportResult {
  event_id: string;
  source: string;
  document_count: number;
  entity_count: number;
  elapsed_seconds: number;
  sample_names: string[];
}

// Dual-RAG evidence citation (from chat + briefing responses)
export interface EvidenceCitation {
  tag: string;
  source_id: string;
  chunk_id: string;
  title: string;
  organization?: string | null;
  year?: number | null;
  url?: string | null;
  snippet: string;
  distance?: number;
}
