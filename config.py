"""Configuration for Holiday Special Hours Compliance Dashboard."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class SnowflakeConfig:
    account: str
    user: str
    password: str | None
    warehouse: str
    database: str
    schema: str
    role: str | None
    authenticator: str = "snowflake"


@dataclass(frozen=True)
class SlackConfig:
    webhook_url: str
    webhook_url_2: str
    bot_token: str
    channel_id: str


def project_root() -> Path:
    return Path(__file__).resolve().parent


def load_sql() -> str:
    path = project_root() / "sql" / "holiday_compliance.sql"
    return path.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def get_snowflake_config() -> SnowflakeConfig:
    env_path = project_root() / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    pwd = os.getenv("SNOWFLAKE_PASSWORD") or os.getenv("SNOWFLAKE_PAT")
    return SnowflakeConfig(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        password=pwd,
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE", ""),
        database=os.getenv("SNOWFLAKE_DATABASE", "PRODDB"),
        schema=os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC"),
        role=os.getenv("SNOWFLAKE_ROLE") or None,
        authenticator=os.getenv("SNOWFLAKE_AUTHENTICATOR", "snowflake"),
    )


@lru_cache(maxsize=1)
def get_slack_config() -> SlackConfig:
    env_path = project_root() / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    return SlackConfig(
        webhook_url=os.getenv("SLACK_WEBHOOK_URL", ""),
        webhook_url_2=os.getenv("SLACK_WEBHOOK_URL_2", ""),
        bot_token=os.getenv("SLACK_BOT_TOKEN", ""),
        channel_id=os.getenv("SLACK_CHANNEL_ID", ""),
    )


SCHEDULE_CRON: str = os.getenv("SCHEDULE_CRON", "0 9 * * 1")
TIMEZONE: str = os.getenv("TIMEZONE", "America/Toronto")
