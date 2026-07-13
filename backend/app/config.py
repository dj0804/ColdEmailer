from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    hunter_api_key: str = ""
    email_verify_provider: str = "hunter"
    email_verify_api_key: str = ""
    gmail_credentials_file: str = "credentials.json"
    daily_send_cap: int = 20
    reply_poll_minutes: int = 15
    nudge1_business_days: int = 10
    nudge2_business_days: int = 20
    database_url: str = "sqlite:///./applier.db"


settings = Settings()
