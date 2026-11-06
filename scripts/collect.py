#!/usr/bin/env python3
"""Public RSS discovery only. No login, scraping bypass, or private account data."""
from __future__ import annotations

import datetime as dt
import email.utils
import hashlib
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "sources.json"
OUTPUT = ROOT / "data" / "offers.json"
MAX_PER_SOURCE = 20
MAX_AGE_DAYS = 21
SIGNAL = re.compile(r"优惠|折扣|满减|红包|券|立减|促销|特价|团购|买一送一|免费|折上折")
DRINK = re.compile(r"奶茶|饮品|茶饮|霸王茶姬|古茗|茶百道|蜜雪冰城|喜茶|奈雪|沪上阿姨|益禾堂|1点点|瑞幸")
PLATFORMS = ("美团外卖", "淘宝闪购", "京东外卖", "抖音团购", "美团", "饿了么", "京东")
UA = "MilkTeaRadar/3.0 (+https://github.com/meganlambert600-hash/megan; public RSS discovery)"


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def text(node: ET.Element, tag: str) -> str:
    return (node.findtext(tag) or "").strip()


def published_time(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        return parsed.replace(tzinfo=dt.timezone.utc) if parsed.tzinfo is None else parsed.astimezone(dt.timezone.utc)
    except (ValueError, TypeError, IndexError):
        return None


def normalize_link(raw: str) -> str | None:
    try:
        url = urllib.parse.urlsplit(raw.strip())
        if url.scheme != "https" or not url.hostname:
            return None
        return urllib.parse.urlunsplit((url.scheme, url.netloc, url.path, url.query, ""))
    except ValueError:
        return None


def classify(title: str, description: str, source: dict) -> dict | None:
    combined = f"{title} {description}"
    if not SIGNAL.search(combined) or not (DRINK.search(combined) or "外卖" in combined):
        return None
    brand = next((x for x in ("霸王茶姬", "古茗", "茶百道", "蜜雪冰城", "喜茶", "奈雪的茶", "沪上阿姨", "益禾堂") if x in combined), "其他/通用")
    platform = next((x for x in PLATFORMS if x in combined), source.get("platform", "公开资讯"))
    return {"brand": brand, "platform": platform, "region": "郑州" if "郑州" in combined else source.get("region", "未知"), "type": "公开优惠线索"}


def collect_source(source: dict, prior: dict, timestamp: str) -> tuple[list[dict], dict]:
    status = {"id": source["id"], "name": source["name"], "status": "error", "count": 0, "checked_at": timestamp}
    req = urllib.request.Request(source["url"], headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml"})
    try:
        with urllib.request.urlopen(req, timeout=14) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Feed too large")
        root = ET.fromstring(raw)
        items = root.findall("./channel/item")
        if not items:
            raise ValueError("No RSS items")
        out = []
        for item in items[:MAX_PER_SOURCE * 3]:
            title, desc, link = text(item, "title"), re.sub(r"<[^>]+>", " ", text(item, "description")), normalize_link(text(item, "link"))
            if not title or not link:
                continue
            stamp = published_time(text(item, "pubDate"))
            if stamp and (now() - stamp).days > MAX_AGE_DAYS:
                continue
            fields = classify(title, desc, source)
            if not fields:
                continue
            id_ = hashlib.sha256(link.encode()).hexdigest()[:20]
            old = prior.get(id_, {})
            out.append({"id": id_, "title": title[:150], "summary": desc[:300], "url": link, "source_name": source["name"], "source_type": "rss_news", "status": "unverified", "first_seen": old.get("first_seen", timestamp), "last_seen": timestamp, "published_at": stamp.isoformat() if stamp else None, **fields})
            if len(out) == MAX_PER_SOURCE:
                break
        status.update(status="ok", count=len(out))
        return out, status
    except (urllib.error.URLError, TimeoutError, ET.ParseError, ValueError, OSError) as error:
        status["error"] = str(error)[:160]
        return [], status


def main() -> int:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    try:
        existing = json.loads(OUTPUT.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        existing = {"offers": []}
    prior = {x["id"]: x for x in existing.get("offers", []) if "id" in x}
    timestamp = now().isoformat(timespec="seconds")
    merged: dict[str, dict] = {}
    statuses = []
    for source in cfg["rss_sources"]:
        collected, status = collect_source(source, prior, timestamp)
        statuses.append(status)
        for row in collected:
            merged.setdefault(row["id"], row)
    # Keep previously seen leads briefly when a feed is unavailable; never claim they were reverified.
    for old in prior.values():
        try:
            seen = dt.datetime.fromisoformat(old["last_seen"])
            if seen.tzinfo and (now() - seen).days <= MAX_AGE_DAYS:
                merged.setdefault(old["id"], old)
        except (KeyError, ValueError, TypeError):
            pass
    data = {"schema_version": 1, "generated_at": timestamp, "city": cfg["city"], "offers": sorted(merged.values(), key=lambda x: x["first_seen"], reverse=True)[:100], "sources": statuses, "note": "这些是公开资讯中的优惠线索，未核实可领取资格。请前往原始来源核对。"}
    OUTPUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Collected {len(data['offers'])} candidate leads; source statuses: {[x['status'] for x in statuses]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
