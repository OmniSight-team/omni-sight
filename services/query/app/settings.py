from omnisight_common import CommonSettings


class Settings(CommonSettings):
    app_name: str = "omnisight-query"

    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    admin_email: str
    admin_password: str

    jwt_secret_key: str
    access_token_expire_minutes: int = 15

    max_failed_attempts: int = 5
    account_lockout_minutes: int = 15

    frontend_origin: str = "http://localhost:3000"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


settings = Settings()
