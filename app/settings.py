from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    postgres_url: str
    gov_api_key: str | None
    receipts_threshold: float
    f3x_feed: str
    ie_feeds: list[str]
    # Email settings
    google_app_pw: str | None
    email_from: str | None
    config_password: str | None


def load_settings() -> Settings:
    postgres_url = os.environ["POSTGRES_URL"]
    gov_api_key = os.environ.get("GOV_API_KEY")

    receipts_threshold = float(os.environ.get("RECEIPTS_THRESHOLD", "50000"))

    f3x_feed = os.environ.get(
        "F3X_FEED",
        "https://efilingapps.fec.gov/rss/generate?preDefinedFilingType=F3X",
    )

    ie_feeds_env = os.environ.get("IE_FEEDS")
    if ie_feeds_env:
        ie_feeds = [u.strip() for u in ie_feeds_env.split(",") if u.strip()]
    else:
        ie_feeds = ["https://efilingapps.fec.gov/rss/generate?forms=F5_24"]

    google_app_pw = os.environ.get("GOOGLE_APP_PW")
    email_from = os.environ.get("EMAIL_FROM")
    config_password = os.environ.get("CONFIG_PASSWORD")

    return Settings(
        postgres_url=postgres_url,
        gov_api_key=gov_api_key,
        receipts_threshold=receipts_threshold,
        f3x_feed=f3x_feed,
        ie_feeds=ie_feeds,
        google_app_pw=google_app_pw,
        email_from=email_from,
        config_password=config_password,
    )
