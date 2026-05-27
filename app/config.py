from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = ""
    db_host: str = "postgres"
    db_port: int = 5432
    db_name: str = "capstone"
    db_user: str = "capstone_user"
    db_password: str = "capstone_password_1234"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    azure_blob_connection_string: str = ""
    azure_blob_container: str = "documents"
    gemini_api_key: str = ""
    openrouter_api_key: str = ""
    ai_provider: str = "gemini"
    ai_model: str = "gemini-2.0-flash"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def resolved_database_url(self) -> str:
        if self.database_url.strip():
            return self.database_url.strip()
        return (
            f"postgresql+psycopg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


settings = Settings()
