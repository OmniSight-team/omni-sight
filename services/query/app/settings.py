from omnisight_common import CommonSettings


class Settings(CommonSettings):
    app_name: str = "omnisight-query"

    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_port: int = 5432


settings = Settings()
