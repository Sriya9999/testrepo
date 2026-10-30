from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration. Every value can be set through an environment variable
    of the same name (case-insensitive), or through backend/.env in development."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "MarketingOS"
    environment: str = "development"  # development | test | production
    api_prefix: str = "/api/v1"
    web_origin: str = "http://localhost:3000"
    public_api_url: str = "http://localhost:8000"

    database_url: str = "sqlite:///./marketingos.db"
    redis_url: str | None = None
    auto_create_tables: bool = True

    # Secrets. The defaults only exist so the app boots in development; production refuses them.
    secret_key: str = "dev-only-change-me-dev-only-change-me"
    # Key material for encrypting integration tokens at rest (a Fernet key is derived from it).
    token_encryption_key: str = "dev-only-token-encryption-key"

    access_token_minutes: int = 15
    refresh_token_days: int = 30
    email_token_hours: int = 48
    password_reset_minutes: int = 60

    # AI
    ai_provider: str = "offline"  # offline | openai
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_text_model: str = "gpt-4.1-mini"
    openai_image_model: str = "gpt-image-1"
    openai_search_model: str = "gpt-4.1-mini"
    perplexity_api_key: str | None = None
    perplexity_model: str = "sonar"

    # External platforms
    meta_app_id: str | None = None
    meta_app_secret: str | None = None
    meta_graph_version: str = "v21.0"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_ads_developer_token: str | None = None
    google_ads_api_version: str = "v18"
    google_ads_login_customer_id: str | None = None
    pagespeed_api_key: str | None = None
    dataforseo_login: str | None = None
    dataforseo_password: str | None = None
    # Allows the "sandbox" connection mode, which records publishing and ad submissions
    # locally instead of calling Meta/Google. Never enable in production.
    allow_sandbox_integrations: bool = True

    # Payments (Razorpay, INR)
    payments_mode: str = "test"  # test | razorpay
    razorpay_key_id: str | None = None
    razorpay_key_secret: str | None = None
    razorpay_webhook_secret: str | None = None

    # Email
    email_backend: str = "console"  # console | smtp
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    email_from: str = "MarketingOS <no-reply@marketingos.local>"

    # Storage
    storage_dir: str = "./storage"
    max_upload_mb: int = 15

    # Crawling
    crawler_max_pages: int = 50
    crawler_timeout_seconds: float = 10.0
    crawler_user_agent: str = "MarketingOS-AuditBot/1.0 (+https://marketingos.app/bot)"

    # Worker
    worker_poll_seconds: float = 2.0
    job_max_attempts: int = 3

    rate_limit_auth_per_minute: int = Field(default=20)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.is_production:
        if settings.secret_key.startswith("dev-only"):
            raise RuntimeError("SECRET_KEY must be set in production")
        if settings.token_encryption_key.startswith("dev-only"):
            raise RuntimeError("TOKEN_ENCRYPTION_KEY must be set in production")
        if settings.allow_sandbox_integrations:
            raise RuntimeError("ALLOW_SANDBOX_INTEGRATIONS must be false in production")
        if settings.payments_mode == "test":
            raise RuntimeError("PAYMENTS_MODE=test is not allowed in production")
    return settings
