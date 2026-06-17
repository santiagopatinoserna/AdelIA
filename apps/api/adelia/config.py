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

    # Generation LLM (chat answers + briefings). Embeddings/OCR always use
    # Mistral — OpenAI has no embeddings parity here. Flip to "openai" once the
    # OpenAI account has credits; "mistral" is the working default.
    llm_provider: str = "mistral"  # "mistral" | "openai"
    mistral_chat_model: str = "mistral-medium-latest"
    openai_chat_model: str = "gpt-4o"

    # M4 ingestion surfaces
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    telegram_bot_mode: str = "webhook"  # "webhook" | "polling"
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
