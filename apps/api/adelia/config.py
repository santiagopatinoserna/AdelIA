from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # Patient chunks are the user's OWN documents and carry facts, not clinical
    # claims (the answer contract forbids interpreting them without an [ev_N]
    # citation), so this cut is deliberately looser: its job is to drop noise,
    # not to gate the clinical promise. Not empirically calibrated because
    # production holds 0 patient documents; re-measure once real ones exist.
    patient_max_distance: float = 0.45

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

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
