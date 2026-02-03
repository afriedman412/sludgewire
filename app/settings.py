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

    return Settings(
        postgres_url=postgres_url,
        gov_api_key=gov_api_key,
        receipts_threshold=receipts_threshold,
        f3x_feed=f3x_feed,
        ie_feeds=ie_feeds,
    )
