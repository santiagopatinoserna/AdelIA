from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values Mistral documents for `reasoning_effort` on the models in
# adelia.llm.REASONING_EFFORT_MODELS: "none" thinks minimally and returns no
# thinking trace, "high" returns a full thinking chunk before the answer and
# spends more tokens. A typo in the env var fails at boot instead of as a 422
# in the middle of a parent's chat turn.
ReasoningEffort = Literal["none", "high"]

# The output size of every embedding model this code knows how to store, and
# the ONE place that couples a model name to a vector dimension. The `chunks`
# and `evidence_chunks` embedding columns are Vector(1024) (migrations 0001
# and 0005, models.py) because mistral-embed returns 1024 floats, so changing
# the embedding model is a migration plus a full re-embed, never a config edit:
# a model that returns another size cannot be stored, and one that returns the
# same size is still a different vector space, so every stored vector and
# every distance cut-off (evidence_max_distance) stops meaning anything.
# Settings refuses a name that is not in this table, and
# tests/test_model_config.py compares this table with the real columns, so a
# new entry cannot be added without the migration that makes it storable.
# Procedure: apps/api/docs/MODELOS.md.
EMBEDDING_MODEL_DIMENSIONS: dict[str, int] = {"mistral-embed": 1024}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    postgres_user: str = "adelia"
    postgres_password: str = "adelia_dev"
    postgres_db: str = "adelia"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "adelia-dev"
    s3_region: str = "us-east-1"

    auth_secret: str = ""
    mistral_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    agent_model: str = "claude-sonnet-5"

    # Stripe billing — 30-day free trial then a recurring subscription. Card is
    # required up front (payment_method_collection="always"); no charge during
    # the trial. Empty secret => billing disabled (endpoints return 503).
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_id: str = ""  # the recurring Price (e.g. 8€/mo) the trial is on
    stripe_trial_days: int = 30

    # Generation LLM (chat answers + briefings). Embeddings/OCR always use
    # Mistral — OpenAI has no embeddings parity here. Flip to "openai" once the
    # OpenAI account has credits; "mistral" is the working default.
    llm_provider: str = "mistral"  # "mistral" | "openai"
    mistral_chat_model: str = "mistral-medium-latest"
    openai_chat_model: str = "gpt-5.1"

    # ---- Every other model name the product sends to a provider ----
    # They used to sit inline in worker code (ocr.py, embed.py, extract.py,
    # qa_pre_baker.py), so changing one meant editing logic. The defaults below
    # are exactly the literals that were inline; tests/test_model_config.py pins
    # them, so a future bump is a visible diff in a test and not a silent edit.
    # extraction and briefing are separate settings from mistral_chat_model on
    # purpose: they share its value today, but setting MISTRAL_CHAT_MODEL for the
    # chat must never move structured extraction or the briefing with it.
    # Table of all models, what depends on each, and the approval procedure:
    # apps/api/docs/MODELOS.md.
    mistral_extraction_model: str = "mistral-medium-latest"
    mistral_briefing_model: str = "mistral-medium-latest"
    mistral_ocr_model: str = "mistral-ocr-latest"
    # Not a free choice: must be a key of EMBEDDING_MODEL_DIMENSIONS (see above).
    mistral_embed_model: str = "mistral-embed"

    # Reasoning effort, per surface. None (the default, and what both were
    # before this setting existed) means the request carries no reasoning_effort
    # field at all, so it is identical to the one sent today. When set, it is sent
    # only if the configured model is on adelia.llm.REASONING_EFFORT_MODELS; on
    # any other model it is ignored with one warning, never forwarded, so it
    # cannot reach a model that would reject it. The default model name
    # "mistral-medium-latest" is NOT on that list: Mistral does not state which
    # model that alias points to, so using the knob means pinning
    # MISTRAL_CHAT_MODEL (or MISTRAL_BRIEFING_MODEL) to a listed id as a
    # deliberate second step. Neither knob has been measured; do not set them in
    # production before the evaluation in apps/api/docs/MODELOS.md.
    #   chat_reasoning_effort      read by the RAG chat stream (which also serves
    #                              /demo) and by the agent's Mistral fallback
    #   briefing_reasoning_effort  read by the briefing Q&A pre-baker
    # Not read by extraction (temperature 0, JSON) or by the consultation summary.
    chat_reasoning_effort: ReasoningEffort | None = None
    briefing_reasoning_effort: ReasoningEffort | None = None

    # ---- Dual-RAG retrieval cut-offs (cosine distance, lower = closer) ----
    # Calibrated 2026-08-31 against the production corpus (118 sources, 258
    # chunks, mistral-embed 1024d) loaded in the dev stack. Full method and
    # raw numbers: docs/CALIBRACION_UMBRAL_EVIDENCIA.md.
    #
    # Two measured populations, best-fragment distance, measured against the
    # index the code actually searches (the 110 pediatric-tagged sources; see
    # chat_orchestrator, which passes specialties=["pediatrics"]):
    #   in-corpus  (240 probes: reflujo, alimentación 6-24 m, guardería,
    #               lactancia, hierro)   p50 0.0663  p95 0.1110  max 0.1715
    #               worst case cross-topic                        max 0.1821
    #   out-of-corpus (14 probes: fibrilación auricular ESC, hipertensión,
    #               colesterol, cribado de cáncer de mama y colorrectal,
    #               endometriosis, diabetes del adulto, SBAR)
    #                                    min 0.1989  p50 0.2127  max 0.2309
    # The valley is [0.1821, 0.1989]. 0.19 keeps 240/240 in-corpus probes and
    # rejects 14/14 out-of-corpus ones.
    #
    # It was 0.20, from a first measurement whose OUT population was scored
    # against the three baby FILES (min 0.2094) while the code searched all
    # 258 chunks. Re-measured against the searched index, the nearest
    # off-corpus probe is 0.1989 (the USPSTF colorectal-screening text
    # reaching the CDC immunization schedule), so 0.20 sat 0.0011 OUTSIDE the
    # valley and leaked 1 of the 14. The previous value before that, 0.45, sat
    # above the corpus's own diameter (max pairwise distance 0.3386) and
    # filtered nothing at all: every question got four "clinical evidence"
    # fragments whether or not they were about the question.
    evidence_max_distance: float = 0.19
    # Relative cut-off, applied on top of the absolute one: a fragment is dropped
    # when its distance exceeds the BEST fragment's distance for the same query
    # by more than this margin. Measured on the public demo on 2026-10-14, the
    # absolute cut-off alone let a reflux guideline through as the fourth
    # "evidence" of a question about sudden infant death: it was inside 0.19, so
    # it passed. An absolute number says "close enough to the corpus", not
    # "close enough to what this question found", and when only one or two
    # sources are good the remaining slots get filled with the next best thing
    # the corpus has. This one is anchored to the query's own best result, so a
    # question with one good source returns one citation. Only the title of
    # that fourth card was recorded: fragment 2 of that guideline (NICE NG1) is
    # the sleeping-position advice, which IS about the question, so the card may
    # have been legitimate; the margin is aimed at its feeding fragments.
    #
    # How 0.08 was chosen, and what it was NOT checked against. There is no
    # embeddings key in the environment this was written in, so no mother's
    # question could be embedded. What was measured is the dev corpus (reflux
    # topic: 7 sources, 14 fragments used as probes, each against the other six
    # sources, the same chunk-as-query proxy docs/CALIBRACION_UMBRAL_EVIDENCIA.md
    # uses): the 2nd, 3rd and 4th best sources of the same topic sit at most
    # 0.0479, 0.0499 and 0.0557 behind the best (p90 0.0472, 0.0491, 0.0551). The
    # margin is 1.4 times the largest of them, so on that sample it removes none
    # of the sources a question legitimately has, and that is what "conservative"
    # means here: a wrongly dropped citation costs a card, a wrongly kept
    # off-topic one costs the mother's trust. It is a floor on how loose it can
    # be, not a fitted value. Short questions embed farther from a passage than a
    # passage does from another passage (the calibration doc's own caveat), so
    # the real spread may be wider; and a margin this wide does nothing when the
    # best fragment is itself poor (best 0.12 + 0.08 is already past 0.19).
    # Re-measure with `scripts/calibrate_answer_threshold.py --mode questions`
    # once a dev key exists, and read the `distance` field of the citations the
    # demo returns for the three 2026-10-14 questions. Tunable through
    # EVIDENCE_RELATIVE_MARGIN without touching code, like the absolute cut.
    evidence_relative_margin: float = 0.08
    # Patient chunks are the user's OWN documents and carry facts, not clinical
    # claims (the answer contract forbids interpreting them without an [ev_N]
    # citation), so this cut is deliberately looser: its job is to drop noise,
    # not to gate the clinical promise. Not empirically calibrated because
    # production holds 0 patient documents; re-measure once real ones exist.
    patient_max_distance: float = 0.45

    # Hybrid retrieval: pgvector cosine search cross-checked by Postgres
    # full-text search and fused by Reciprocal Rank Fusion (services/fusion.py,
    # wired in enrichment/evidence_retrieval.py and services/retrieval.py).
    #
    # OFF by default and it stays off until the eval harness says the fused
    # order is better than the vector one: a retrieval change moves what the
    # model is allowed to cite about a baby, so it is not flipped on a hunch.
    # With the flag off both retrieval functions run the exact SQL they ran
    # before it existed, and no lexical query is issued.
    #
    # The flag changes the ORDER of what survives the cut-offs above, never
    # which fragments survive: evidence_max_distance and patient_max_distance
    # remain the only admission control (see evidence_retrieval for why).
    retrieval_hybrid_enabled: bool = False

    # STT (speech-to-text). "mistral" = Voxtral (UE por defecto, diarización);
    # "openai" = whisper-1 (sin diarización). Voxtral reusa mistral_api_key.
    stt_provider: str = "mistral"  # "mistral" | "openai"
    mistral_stt_model: str = "voxtral-mini-latest"
    openai_stt_model: str = "whisper-1"
    # Default to the EU data-residency endpoint (not api.openai.com): the DPIA
    # and the /profesionales page commit to patient audio never leaving the
    # EU, and eu.api.openai.com is how we honor that for OpenAI STT. This is
    # transcription-only: openai_chat_model and the chat client are untouched,
    # so switching STT provider never moves where chat traffic goes.
    #
    # PREREQUISITE, verified live 2026-08-19: this endpoint rejects ordinary
    # projects with 401 "This endpoint is only accessible by projects with
    # geography restrictions enabled". Enabling OpenAI STT therefore needs an
    # OpenAI project with EU data residency, not just credits. Pointing this
    # at api.openai.com instead sends patient audio to the US and contradicts
    # the published privacy notice, so that swap requires a DPIA revision.
    openai_stt_base_url: str = "https://eu.api.openai.com/v1"

    # M4 ingestion surfaces
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    telegram_bot_mode: str = "webhook"  # "webhook" | "polling"
    telegram_bot_username: str = "Adelia_godiai_bot"
    # Daily diary reminder (Telegram-first daily interaction): at this local
    # hour, every linked chat without a diary entry for today gets a nudge.
    diary_reminder_hour: int = 20
    diary_reminder_tz: str = "Europe/Madrid"
    postmark_inbound_token: str = ""
    adelia_email_domain: str = "in.adelia.app"
    adelia_app_url: str = "http://localhost:3000"
    # Comma-separated browser origins allowed by CORS (web app hosts).
    cors_origins: str = "http://localhost:3000,http://localhost:3001"
    # In-process per-identity rate limiting (disable only for test suites).
    rate_limit_enabled: bool = True
    # DB connection pool — defaults too small for concurrent uploads.
    db_pool_size: int = 20
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    # Max documents processed concurrently in-process (BackgroundTasks).
    # Bounds DB-pool + Mistral-API pressure; excess uploads queue, not 500.
    # v0.2 replaces in-process tasks with a real worker queue (Celery).
    doc_processing_concurrency: int = 8
    # Reconciliation at boot (audit 4.4). A document still unprocessed this
    # many minutes after it was created was orphaned by a crash, an OOM or a
    # deploy: the in-process task died with the worker and nothing ever
    # retried it, so the app said "procesando" forever over an unrepeatable
    # recording. 15 minutes is comfortably above the slowest real pipeline
    # (a 20-minute consultation transcribes in ~2-3 min) so a healthy job in
    # flight during a restart is never requeued underneath itself.
    document_stuck_after_minutes: int = 15
    # Cap per boot so a bad night cannot start hundreds of pipelines at once;
    # the rest are picked up by the next boot or by /reprocess.
    document_requeue_limit: int = 50

    # ---- Funnel + public demo (audit 4.6, 4.7, 4.8) ----
    # Who may read GET /funnel/summary. Empty (the default, and every
    # self-hosted install) means nobody can: the endpoint answers 404 rather
    # than 403 so it does not advertise that a set of numbers exists behind
    # the right account. Compared case-insensitively against users.email.
    owner_email: str = ""
    # The card-free trial (audit 4.7) is granted by the code, not by Stripe:
    # an account that has never touched checkout is treated as trialing for
    # stripe_trial_days from users.created_at. Set to 0 to require checkout
    # from the first screen, as it worked until 2026-09-01.
    free_trial_days: int = 30
    # /demo is a public LLM endpoint, which is a spending endpoint anybody on
    # the internet can press. Two brakes: a per-minute rate limit per IP
    # (ratelimit.ROUTE_BUDGETS) and this hard daily ceiling, counted in the
    # funnel_counters row for "demo_ask" so it survives a restart. Past it the
    # demo answers 429 and the page says to come back tomorrow.
    demo_daily_budget: int = 300
    # Kill switch for the whole public demo (endpoints answer 503).
    demo_enabled: bool = True
    # Longest question the demo will embed. A public endpoint with no cap is
    # a way to buy someone else's embeddings by the megabyte.
    demo_max_question_chars: int = 300

    @field_validator("chat_reasoning_effort", "briefing_reasoning_effort", mode="before")
    @classmethod
    def _blank_effort_means_unset(cls, value):
        # An env file line such as `CHAT_REASONING_EFFORT=` arrives as "". That
        # is not a valid effort and should read as "not configured".
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("mistral_embed_model")
    @classmethod
    def _embed_model_must_have_a_known_dimension(cls, value: str) -> str:
        if value not in EMBEDDING_MODEL_DIMENSIONS:
            raise ValueError(
                f"unknown embedding model {value!r}: the vector columns are sized for "
                f"{sorted(EMBEDDING_MODEL_DIMENSIONS)}. Changing the embedding model is a "
                "migration plus a re-embed of every stored vector, not a config edit "
                "(see apps/api/docs/MODELOS.md)."
            )
        return value

    @property
    def embedding_dimension(self) -> int:
        return EMBEDDING_MODEL_DIMENSIONS[self.mistral_embed_model]

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
