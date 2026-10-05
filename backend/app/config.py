from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = ""
    openai_model: str = "gpt-4o"          # reply classification (cheap/fast)
    openai_draft_model: str = "gpt-5"     # outreach drafting (nudges are templated)
    openai_draft_reasoning_effort: str = "low"
    # Hard cap on OpenAI spend per budget window. Every call is priced from its
    # reported token usage; once the window's total reaches the cap, further
    # calls raise BudgetExceeded instead of reaching OpenAI. 0 disables the cap.
    llm_budget_usd: float = 5.0
    llm_budget_start: str = "2026-10-05"  # first window's start date (UTC)
    llm_budget_days: int = 42             # window length; rolls over after this
    hunter_api_key: str = ""
    # Off = discovery and verification never call Hunter, even with a key set.
    hunter_enabled: bool = True
    # Role-specific resume variants live at {resume_dir}/resume_{variant}.pdf
    # (e.g. resume_ai_engineer.pdf). Applications carry the variant to attach;
    # anything unset falls back to resume_default_variant.
    resume_dir: str = "../assets"
    resume_default_variant: str = "ai_engineer"

    # Candidate identity injected into the drafting prompt. Personal details are
    # intentionally NOT hardcoded here — set them in .env (gitignored) so they
    # never land in version control. See .env.example.
    candidate_name: str = ""
    candidate_email: str = ""
    candidate_phone: str = ""
    candidate_links: str = ""
    candidate_school: str = ""
    candidate_year: str = ""
    candidate_prior: str = ""
    candidate_availability: str = ""
    email_verify_provider: str = "hunter"
    email_verify_api_key: str = ""
    gmail_credentials_file: str = "credentials.json"
    daily_send_cap: int = 20
    reply_poll_minutes: int = 15
    nudge1_business_days: int = 10
    nudge2_business_days: int = 20  # 0 disables the second nudge
    # Business days after which a still-silent application is marked ghosted_dead.
    # Kept past nudge2 so the second nudge has time to land.
    nudge_dead_business_days: int = 30
    ghost_check_hour: int = 8  # daily ghosting sweep, UTC hour

    # Daily outreach routine: works through the company queue on weekdays,
    # staging drafts for approval. It NEVER sends — approval is still required.
    outreach_enabled: bool = False
    outreach_per_day: int = 2
    outreach_hour: int = 3  # UTC (03:00 UTC = 08:30 IST)
    database_url: str = "sqlite:///./applier.db"


settings = Settings()
