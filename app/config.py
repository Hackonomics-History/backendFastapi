from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    jwks_url: str
    jwt_issuer: str
    jwt_audience: str
    gemini_api_key: str
    qdrant_url: str = "http://qdrant:6333"
    qdrant_collection: str = "business_news"
    internal_ai_token: str
    google_client_id: str = ""
    google_client_secret: str = ""
    google_calendar_redirect_uri: str = "http://localhost:8000/api/calendar/oauth/callback/"
    # Redis
    redis_url: str = "redis://localhost:6380/0"
    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_news_refresh_request_topic: str = "news.refresh.request"
    kafka_news_refresh_result_topic: str = "news.refresh.result"
    kafka_consumer_group_id: str = "hackonomics-fastapi-news"
    # gRPC server
    grpc_port: int = 50052


settings = Settings()
