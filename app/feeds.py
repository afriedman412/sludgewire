from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, date, timezone
from email.utils import parsedate_to_datetime
from typing import Optional, Dict

import requests


@dataclass(frozen=True)
class RSSItem:
    title: str
    link: str
    description: str
    pub_date_utc: Optional[datetime]
    meta: Dict[str, str]


def fetch_rss_items(feed_url: str) -> list[RSSItem]:
    r = requests.get(feed_url, timeout=30)
    r.raise_for_status()
    root = ET.fromstring(r.text)

    items: list[RSSItem] = []
    for item in root.findall("./channel/item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        desc = item.findtext("description") or ""
        pub = item.findtext("pubDate")

        pub_dt = None
        if pub:
            dt = parsedate_to_datetime(pub)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            pub_dt = dt.astimezone(timezone.utc)

        meta = parse_meta(desc)

        items.append(RSSItem(title=title, link=link,
                     description=desc, pub_date_utc=pub_dt, meta=meta))

    return items


def parse_meta(description: str) -> Dict[str, str]:
    """
    Extracts the ********* ... ********* key/value blob.
    Example:
    *********CommitteeId: C00813006 | FilingId: 1944492 | FormType: F3XN | CoverageFrom: 07/01/2025 | ...*********
    """
    m = re.search(r"\*{5,}(.*?)\*{5,}", description, flags=re.S)
    blob = m.group(1) if m else description
    out: Dict[str, str] = {}
    for part in blob.split("|"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def parse_mmddyyyy(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s.strip(), "%m/%d/%Y").date()
    except ValueError:
        return None


def infer_filing_id(item: RSSItem) -> Optional[int]:
    """
    Uses meta['FilingId'] if present; else tries to pull from .../<id>.fec
    """
    fid = item.meta.get("FilingId")
    if fid and fid.isdigit():
        return int(fid)
    tail = item.link.rsplit("/", 1)[-1]
    if tail.endswith(".fec"):
        base = tail[:-4]
        if base.isdigit():
            return int(base)
    return None
