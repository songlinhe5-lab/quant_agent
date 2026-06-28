"""
Quant Agent 全局配置校验（Pydantic Settings v2）

🚨 核心规则：缺失关键配置直接 fail-fast，禁止带病启动。
"""
from enum import Enum
from typing import Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class QuantEnv(str, Enum):
    development = "development"
    production = "production"
    testing = "testing"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # 允许额外的环境变量
    )

    # ===== 环境标识 =====
    quant_env: QuantEnv = Field(default=QuantEnv.development, alias="QUANT_ENV")

    # ===== 数据库配置 =====
    database_url: str = Field(alias="DATABASE_URL")
    db_user: Optional[str] = Field(default=None, alias="DB_USER")
    db_password: Optional[str] = Field(default=None, alias="DB_PASSWORD")
    db_name: Optional[str] = Field(default=None, alias="DB_NAME")

    # ===== Redis 配置 =====
    redis_host: str = Field(default="localhost", alias="REDIS_HOST")
    redis_port: int = Field(default=6379, alias="REDIS_PORT")
    redis_password: Optional[str] = Field(default=None, alias="REDIS_PASSWORD")

    # ===== LLM 配置 =====
    llm_api_key: Optional[str] = Field(default=None, alias="LLM_API_KEY")
    llm_base_url: Optional[str] = Field(default=None, alias="LLM_BASE_URL")
    llm_model: Optional[str] = Field(default=None, alias="LLM_MODEL")
    llm_pro_model: Optional[str] = Field(default=None, alias="LLM_PRO_MODEL")

    # ===== OpenAI / Embedding 配置 =====
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")
    embedding_api_key: str = Field(alias="EMBEDDING_API_KEY")
    embedding_base_url: str = Field(alias="EMBEDDING_BASE_URL")
    embedding_model: str = Field(default="BAAI/bge-large-zh-v1.5", alias="EMBEDDING_MODEL")  # noqa: E501
    embedding_dim: int = Field(default=1024, alias="EMBEDDING_DIM")

    # ===== 数据源 API Key =====
    fmp_api_key: Optional[str] = Field(default=None, alias="FMP_API_KEY")
    finnhub_api_key: Optional[str] = Field(default=None, alias="FINNHUB_API_KEY")
    akshare_api_key: Optional[str] = Field(default=None, alias="AKSHARE_API_KEY")
    fred_api_key: Optional[str] = Field(default=None, alias="FRED_API_KEY")

    # ===== Futu OpenD 配置 =====
    futu_host: str = Field(default="127.0.0.1", alias="FUTU_HOST")
    futu_port: int = Field(default=11111, alias="FUTU_PORT")
    futu_trd_env: Literal["SIMULATE", "REAL"] = Field(default="SIMULATE", alias="FUTU_TRD_ENV")  # noqa: E501
    futu_pwd_unlock: Optional[str] = Field(default=None, alias="FUTU_PWD_UNLOCK")

    # ===== 告警配置 =====
    telegram_bot_token: Optional[str] = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: Optional[str] = Field(default=None, alias="TELEGRAM_CHAT_ID")
    serverchan_sendkey: Optional[str] = Field(default=None, alias="SERVERCHAN_SENDKEY")
    feishu_webhook_url: Optional[str] = Field(default=None, alias="FEISHU_WEBHOOK_URL")

    # ===== 全局风控 =====
    real_trade_execute: bool = Field(default=False, alias="REAL_TRADE_EXECUTE")

    # ===== 内部通信安全 =====
    internal_api_secret: str = Field(
        default="default-internal-secret-change-me",
        alias="INTERNAL_API_SECRET"
    )

    # ===== 敏感字段加密 =====
    encryption_master_key: Optional[str] = Field(
        default=None,
        alias="ENCRYPTION_MASTER_KEY"
    )

    # ===== Meilisearch 配置 =====
    meilisearch_host: Optional[str] = Field(default=None, alias="MEILISEARCH_HOST")
    meilisearch_api_key: Optional[str] = Field(default=None, alias="MEILISEARCH_API_KEY")  # noqa: E501

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v or v.strip() == "":
            raise ValueError("❌ DATABASE_URL 必须配置，禁止空值")
        if not (v.startswith("sqlite://") or v.startswith("postgresql://")):
            raise ValueError("❌ DATABASE_URL 必须以 sqlite:// 或 postgresql:// 开头")
        return v

    @field_validator("embedding_api_key")
    @classmethod
    def validate_embedding_api_key(cls, v: str) -> str:
        if not v or v.strip() == "":
            raise ValueError("❌ EMBEDDING_API_KEY 必须配置（硅基流动 API Key）")
        return v

    @field_validator("real_trade_execute")
    @classmethod
    def validate_real_trade_execute(cls, v: bool, info) -> bool:
        if v is True:
            # 实盘交易开启时，必须配置 Futu 解锁密码
            if not info.data.get("futu_pwd_unlock"):
                raise ValueError(
                    "❌ 实盘交易已开启 (REAL_TRADE_EXECUTE=true)，"
                    "必须配置 FUTU_PWD_UNLOCK（Futu 交易密码）"
                )
        return v

    @property
    def is_production(self) -> bool:
        return self.quant_env == QuantEnv.production

    @property
    def is_development(self) -> bool:
        return self.quant_env == QuantEnv.development


# 全局单例
settings = Settings()
