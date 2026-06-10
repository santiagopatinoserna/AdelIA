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

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
