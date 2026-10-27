// Shared endpoint definitions, parameterized by fetcher so the same surface
// works server-side (authedFetch signs with the session JWT) and browser-side
// (proxy fetch through /api/backend, which signs server-side).
// No auth import here — this module must stay bundleable for the client.

import type {
  BriefingCreate,
  BriefingDetailOut,
  BriefingOut,
} from "./briefing-types";
import type {
  ClinicalTrial,
  SavedGenomics,
  CoverageStats,
  DrugInteraction,
  GDPRTemplateContent,
  GDPRTemplateSummary,
  GuideContent,
  GuideSummary,
  IngestionImportResult,
  LabEvalBulkRequest,
  LabEvalResult,
  NormalizedCode,
  Profile,
  ProfileCreateRequest,
  VariantHit,
} from "./enrichment-types";

export type DocumentStatus = "processing" | "ready" | "failed";

export type DocumentDTO = {
  id: string;
  source: "web" | "manual" | "consulta";
  mime_type: string;
  file_name: string;
  raw_text: string | null;
  created_at: string;
  processed_at: string | null;
  status: DocumentStatus;
  entity_count: number;
  chunk_count: number;
  speaker_names?: Record<string, string> | null;
  // Post-recording essence bullets (consulta docs only, best-effort).
  summary?: string | null;
  /** Daily diary entries (Telegram): ISO date the entry is about. */
  diary_date?: string | null;
};

export type TelegramLinkDTO = {
  bot_url: string;
  link_token: string;
  instructions: string;
};

export type EmailAliasDTO = {
  alias: string;
  instructions: string;
};

/** One line of the "Hoy con <nombre>" card (GET /today, computed server-side). */
export type TodayItem = {
  kind: "vaccine" | "observation" | "remember";
  text: string;
  tone: "neutral" | "warn";
};
export type TodayDTO = { name: string | null; items: TodayItem[] };

export type Fetcher = (path: string, init?: RequestInit) => Promise<Response>;

/** Whether the baby screen still has to be shown (audit 4.3). */
export type OnboardingStatus = { needed: boolean };

export type BabyOnboarding = {
  display_name: string;
  date_of_birth?: string | null;
  sex?: "M" | "F" | "other" | null;
};

export type BillingStatus = {
  status: string;
  active: boolean;
  plan: string | null;
  trial_end: string | null;
  current_period_end: string | null;
  trial_days: number;
  /** "stripe" | "local" | null. "local" is the card-free trial this server
   *  grants a brand-new account (audit 4.7); Stripe has never heard of it. */
  trial_source?: "stripe" | "local" | null;
  /** Whether a Stripe customer exists, i.e. whether POST /billing/portal has
   *  anything to open. Settings shows "manage" when true and "subscribe" when
   *  false, instead of a one-click button that answers 400. */
  can_manage?: boolean;
};

export function makeApi(fetcher: Fetcher) {
  return {
    async today(locale: string): Promise<TodayDTO> {
      const res = await fetcher(`/today?locale=${encodeURIComponent(locale)}`);
      if (!res.ok) throw new Error(`today: ${res.status}`);
      return res.json();
    },

    async billingStatus(): Promise<BillingStatus> {
      const res = await fetcher("/billing/status");
      if (!res.ok) throw new Error(`billingStatus: ${res.status}`);
      return res.json();
    },

    onboarding: {
      async status(): Promise<OnboardingStatus> {
        const res = await fetcher("/users/me/onboarding");
        if (!res.ok) throw new Error(`onboarding.status: ${res.status}`);
        return res.json();
      },

      async complete(payload: BabyOnboarding): Promise<void> {
        const res = await fetcher("/users/me/onboarding", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error(`onboarding.complete: ${res.status}`);
      },

      async skip(): Promise<void> {
        const res = await fetcher("/users/me/onboarding/skip", { method: "POST" });
        if (!res.ok && res.status !== 204) {
          throw new Error(`onboarding.skip: ${res.status}`);
        }
      },
    },

    async listDocuments(profileId?: string | null): Promise<DocumentDTO[]> {
      const qs = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : "";
      const res = await fetcher(`/documents${qs}`);
      if (!res.ok) throw new Error(`listDocuments: ${res.status}`);
      return res.json();
    },

    async getDocument(id: string): Promise<DocumentDTO> {
      const res = await fetcher(`/documents/${id}`);
      if (!res.ok) throw new Error(`getDocument: ${res.status}`);
      return res.json();
    },

    /** Run the pipeline again on a document that failed or hung (audit 4.4).
     *  Returns the row reset to "processing"; the caller resumes polling. */
    async reprocessDocument(id: string): Promise<DocumentDTO> {
      const res = await fetcher(`/documents/${id}/reprocess`, { method: "POST" });
      if (!res.ok) throw new Error(`reprocessDocument: ${res.status}`);
      return res.json();
    },

    async deleteDocument(id: string): Promise<void> {
      const res = await fetcher(`/documents/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`deleteDocument: ${res.status}`);
    },

    async setSpeakerNames(id: string, names: Record<string, string>): Promise<DocumentDTO> {
      const res = await fetcher(`/documents/${id}/speakers`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ speaker_names: names }),
      });
      if (!res.ok) throw new Error(`setSpeakerNames: ${res.status}`);
      return res.json();
    },

    briefings: {
      async create(input: BriefingCreate): Promise<BriefingOut> {
        const res = await fetcher("/briefings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(input),
        });
        if (!res.ok) throw new Error(`briefings.create: ${res.status}`);
        return res.json();
      },

      async list(): Promise<BriefingOut[]> {
        const res = await fetcher("/briefings");
        if (!res.ok) throw new Error(`briefings.list: ${res.status}`);
        return res.json();
      },

      async getById(id: string): Promise<BriefingDetailOut> {
        const res = await fetcher(`/briefings/${id}`);
        if (!res.ok) throw new Error(`briefings.getById: ${res.status}`);
        return res.json();
      },

      async regenerate(id: string): Promise<BriefingOut> {
        const res = await fetcher(`/briefings/${id}/regenerate`, { method: "POST" });
        if (!res.ok) throw new Error(`briefings.regenerate: ${res.status}`);
        return res.json();
      },

      async remove(id: string): Promise<void> {
        const res = await fetcher(`/briefings/${id}`, { method: "DELETE" });
        if (!res.ok) throw new Error(`briefings.remove: ${res.status}`);
      },
    },

    ingestion: {
      async listGuides(): Promise<GuideSummary[]> {
        const res = await fetcher("/ingestion/guides");
        if (!res.ok) throw new Error(`ingestion.listGuides: ${res.status}`);
        return res.json();
      },

      async getGuide(slug: string): Promise<GuideContent> {
        const res = await fetcher(`/ingestion/guides/${slug}`);
        if (!res.ok) throw new Error(`ingestion.getGuide: ${res.status}`);
        return res.json();
      },

      async listGdprTemplates(): Promise<GDPRTemplateSummary[]> {
        const res = await fetcher("/ingestion/gdpr-templates");
        if (!res.ok) throw new Error(`ingestion.listGdprTemplates: ${res.status}`);
        return res.json();
      },

      async getGdprTemplate(country: string): Promise<GDPRTemplateContent> {
        const res = await fetcher(`/ingestion/gdpr-templates/${country}`);
        if (!res.ok) throw new Error(`ingestion.getGdprTemplate: ${res.status}`);
        return res.json();
      },

      async importAppleHealth(file: File): Promise<IngestionImportResult> {
        const fd = new FormData();
        fd.append("file", file);
        const res = await fetcher("/ingestion/apple-health/import", {
          method: "POST",
          body: fd,
        });
        if (!res.ok) throw new Error(`ingestion.importAppleHealth: ${res.status}`);
        return res.json();
      },

      async importCcd(file: File): Promise<IngestionImportResult> {
        const fd = new FormData();
        fd.append("file", file);
        const res = await fetcher("/ingestion/ccd/import", {
          method: "POST",
          body: fd,
        });
        if (!res.ok) throw new Error(`ingestion.importCcd: ${res.status}`);
        return res.json();
      },

      /** `locale` travels inside the link token so the bot replies in the UI language. */
      async getTelegramLink(locale?: string): Promise<TelegramLinkDTO> {
        const qs = locale ? `?locale=${encodeURIComponent(locale)}` : "";
        const res = await fetcher(`/ingestion/telegram/link${qs}`);
        if (!res.ok) throw new Error(`ingestion.getTelegramLink: ${res.status}`);
        return res.json();
      },

      async getEmailAlias(): Promise<EmailAliasDTO> {
        const res = await fetcher("/ingestion/email/alias");
        if (!res.ok) throw new Error(`ingestion.getEmailAlias: ${res.status}`);
        return res.json();
      },
    },

    enrichment: {
      async normalize(query: string): Promise<NormalizedCode> {
        const res = await fetcher(
          `/enrichment/code-normalize?query=${encodeURIComponent(query)}`,
        );
        if (!res.ok) throw new Error(`enrichment.normalize: ${res.status}`);
        return res.json();
      },

      async evaluateLabs(payload: LabEvalBulkRequest): Promise<LabEvalResult[]> {
        const res = await fetcher("/enrichment/lab-evaluate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error(`enrichment.evaluateLabs: ${res.status}`);
        return res.json();
      },

      async checkDrugInteractions(medications: string[]): Promise<DrugInteraction[]> {
        const res = await fetcher("/enrichment/drug-interactions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ medications }),
        });
        if (!res.ok) throw new Error(`enrichment.checkDrugInteractions: ${res.status}`);
        return res.json();
      },

      async searchTrials(
        condition: string,
        country?: string,
        maxResults = 10,
      ): Promise<ClinicalTrial[]> {
        const params = new URLSearchParams({
          condition,
          max_results: String(maxResults),
        });
        if (country) params.set("country", country);
        const res = await fetcher(`/enrichment/trials?${params.toString()}`);
        if (!res.ok) throw new Error(`enrichment.searchTrials: ${res.status}`);
        return res.json();
      },

      async savedGenomics(): Promise<SavedGenomics> {
        const res = await fetcher("/enrichment/genomics");
        if (!res.ok) throw new Error(`enrichment.savedGenomics: ${res.status}`);
        return res.json();
      },

      async uploadGenomics(file: File): Promise<VariantHit[]> {
        const fd = new FormData();
        fd.append("file", file);
        const res = await fetcher("/enrichment/genomics/upload", {
          method: "POST",
          body: fd,
        });
        if (!res.ok) throw new Error(`enrichment.uploadGenomics: ${res.status}`);
        return res.json();
      },

      async listProfiles(): Promise<Profile[]> {
        const res = await fetcher("/enrichment/profiles");
        if (!res.ok) throw new Error(`enrichment.listProfiles: ${res.status}`);
        return res.json();
      },

      async createProfile(payload: ProfileCreateRequest): Promise<Profile> {
        const res = await fetcher("/enrichment/profiles", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error(`enrichment.createProfile: ${res.status}`);
        return res.json();
      },

      async setDefaultProfile(id: string): Promise<Profile> {
        const res = await fetcher(`/enrichment/profiles/${id}/default`, {
          method: "POST",
        });
        if (!res.ok) throw new Error(`enrichment.setDefaultProfile: ${res.status}`);
        return res.json();
      },

      async deleteProfile(id: string): Promise<void> {
        const res = await fetcher(`/enrichment/profiles/${id}`, { method: "DELETE" });
        if (!res.ok) throw new Error(`enrichment.deleteProfile: ${res.status}`);
      },

      async coverage(): Promise<CoverageStats> {
        const res = await fetcher("/enrichment/coverage");
        if (!res.ok) throw new Error(`enrichment.coverage: ${res.status}`);
        return res.json();
      },
    },
  };
}
