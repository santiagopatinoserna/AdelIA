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

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
