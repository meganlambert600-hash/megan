#!/usr/bin/env python3
"""Collect public milk-tea deal leads without login or access-control bypasses.

The collector supports RSS/Atom, selected public HTML pages, and a conservative
adapter for public Bing result pages. App, mini-program, login, CAPTCHA-prone,
and private/social channels are recorded for diagnostics but never scraped.
Every emitted item remains an unverified lead until a person checks the source.
"""
from __future__ import annotations

import concurrent.futures
import datetime as dt
import email.utils
import hashlib
import html
from html.parser import HTMLParser
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "sources.json"
OUTPUT = ROOT / "data" / "offers.json"
MAX_PER_SOURCE = 20
MAX_AGE_DAYS = 21
MAX_RESPONSE_BYTES = 1_000_000
REQUEST_TIMEOUT = 12
UA = "MilkTeaRadar/4.0 (+https://github.com/meganlambert600-hash/megan; public-lead discovery)"

SOURCE_GROUPS = (
    "rss_sources",
    "brand_official",
    "official_links",
    "web_search_sources",
    "mini_program_sources",
)
IN_APP_TYPES = {
    "app", "mini_program", "wechat_official_account", "wechat_group",
    "push", "offline_qr", "deep_link",
}
POLICY_SKIP_HOSTS = {
    "weixin.sogou.com", "www.sogou.com", "sogou.com", "www.xiaohongshu.com",
    "s.weibo.com", "www.zhihu.com", "search.smzdm.com", "www.smzdm.com",
    "www.douyin.com", "life.douyin.com", "search.bilibili.com",
}
GENERIC_TITLES = re.compile(r"(?:官网|首页|网站|入口|app下载|小程序|登录|注册|品牌介绍|门店查询)$", re.I)
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
TRACKING_QUERY_KEYS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "spm", "from"}


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def clean_text(value: str | None, limit: int = 1000) -> str:
    value = html.unescape(TAG_RE.sub(" ", value or ""))
    return SPACE_RE.sub(" ", value).strip()[:limit]


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def child_text(node: ET.Element, names: Iterable[str]) -> str:
    wanted = {name.lower() for name in names}
    for child in node:
        if local_name(child.tag) in wanted and child.text:
            return child.text.strip()
    return ""


def published_time(value: str) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (ValueError, TypeError, IndexError):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    return parsed.replace(tzinfo=dt.timezone.utc) if parsed.tzinfo is None else parsed.astimezone(dt.timezone.utc)


def date_from_text(value: str) -> dt.datetime | None:
    """Infer an explicit Chinese/ISO calendar date; never infer from vague words."""
    match = re.search(r"(?:(20\d{2})[年./-])?(\d{1,2})[月./-](\d{1,2})日?", value or "")
    if not match:
        return None
    current = now()
    year = int(match.group(1) or current.year)
    try:
        parsed = dt.datetime(year, int(match.group(2)), int(match.group(3)), tzinfo=dt.timezone.utc)
    except ValueError:
        return None
    if not match.group(1) and parsed - current > dt.timedelta(days=14):
        parsed = parsed.replace(year=year - 1)
    return parsed


def normalize_link(raw: str, base: str | None = None) -> str | None:
    try:
        absolute = urllib.parse.urljoin(base or "", (raw or "").strip())
        url = urllib.parse.urlsplit(absolute)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            return None
        query = urllib.parse.parse_qsl(url.query, keep_blank_values=True)
        query = [(k, v) for k, v in query if k.lower() not in TRACKING_QUERY_KEYS]
        path = re.sub(r"/{2,}", "/", url.path or "/")
        return urllib.parse.urlunsplit(("https", url.netloc.lower(), path, urllib.parse.urlencode(query), ""))
    except (ValueError, UnicodeError):
        return None


def build_matchers(cfg: dict) -> dict:
    policy = cfg.get("collection_policy", {})
    brands = list(dict.fromkeys(cfg.get("focus_brands", []) + cfg.get("extended_brands", [])))
    aliases: list[tuple[str, str]] = []
    for brand in brands:
        aliases.append((brand, brand))
        aliases.extend((alias, brand) for alias in cfg.get("brand_aliases", {}).get(brand, []))
    aliases.sort(key=lambda pair: len(pair[0]), reverse=True)
    deal_words = list(dict.fromkeys(policy.get("deal_keywords", []) + ["优惠", "促销", "特价", "免费", "折上折"]))
    city_words = list(dict.fromkeys(policy.get("city_filter", []) + policy.get("zhengzhou_areas", [])))
    return {"aliases": aliases, "deal_words": deal_words, "city_words": city_words}


def classify(title: str, description: str, source: dict, matchers: dict | None = None) -> dict | None:
    """Classify a candidate conservatively; never marks a lead as verified."""
    if matchers is None:
        try:
            matchers = build_matchers(json.loads(CONFIG.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            matchers = {
                "aliases": [(x, x) for x in ("霸王茶姬", "古茗", "茶百道", "蜜雪冰城", "喜茶", "瑞幸咖啡")],
                "deal_words": ["优惠", "折扣", "满减", "红包", "券", "立减", "团购", "买一送一", "免单"],
                "city_words": ["郑州", "河南"],
            }
    title, description = clean_text(title, 200), clean_text(description, 500)
    combined = f"{title} {description}"
    hits = [word for word in matchers["deal_words"] if word and word.lower() in combined.lower()]
    brand = next((canonical for alias, canonical in matchers["aliases"] if alias.lower() in combined.lower()), None)
    beverage = bool(brand or re.search(r"奶茶|茶饮|饮品|咖啡|果茶|外卖", combined, re.I))
    if not hits or not beverage or GENERIC_TITLES.fullmatch(title):
        return None
    platform_names = ("美团外卖", "淘宝闪购", "京东外卖", "抖音团购", "美团", "饿了么", "京东", "支付宝", "云闪付")
    platform = next((name for name in platform_names if name in combined), source.get("platform", "公开网页"))
    region = "郑州" if any(word in combined for word in matchers["city_words"]) else source.get("region", "全国")
    if region not in {"郑州", "全国"}:
        region = "郑州" if source.get("region") == "郑州" else "全国"
    amount = next(iter(re.findall(r"(?<!\d)(\d+(?:\.\d{1,2})?)\s*元", combined)), None)
    discount = next(iter(re.findall(r"(?<!\d)(\d(?:\.\d)?)\s*折", combined)), None)
    dates = re.findall(r"(?:20\d{2}[年./-])?\d{1,2}[月./-]\d{1,2}日?", combined)[:2]
    if "免单" in combined:
        deal_type = "免单"
    elif "买一送一" in combined or "买赠" in combined:
        deal_type = "买赠"
    elif "红包" in combined:
        deal_type = "红包"
    elif "团购" in combined:
        deal_type = "团购"
    else:
        deal_type = "优惠券/促销"
    return {
        "brand": brand or "其他/通用",
        "platform": platform,
        "region": region,
        "type": deal_type,
        "deal": {"amount_yuan": amount, "discount": discount, "date_mentions": dates},
        "evidence_keywords": hits[:8],
    }


def fingerprint(title: str, url: str, fields: dict) -> str:
    normalized_title = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", title.lower())
    deal = fields.get("deal", {})
    parts = [fields.get("brand", ""), normalized_title, deal.get("amount_yuan") or "", "|".join(deal.get("date_mentions", []))]
    if len(normalized_title) < 8:
        split = urllib.parse.urlsplit(url)
        parts.append(split.netloc + split.path.rstrip("/"))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]


def make_offer(title: str, summary: str, url: str, source: dict, source_type: str,
               published: dt.datetime | None, prior: dict[str, dict], timestamp: str,
               matchers: dict) -> dict | None:
    link = normalize_link(url)
    fields = classify(title, summary, source, matchers)
    if not link or not fields:
        return None
    if published is None and source_type != "rss_atom":
        published = date_from_text(f"{title} {summary}")
        if published is None:
            return None
    if published and ((now() - published).days > MAX_AGE_DAYS or published - now() > dt.timedelta(days=14)):
        return None
    ident = fingerprint(title, link, fields)
    old = prior.get(ident, {})
    return {
        "id": ident,
        "title": clean_text(title, 150),
        "summary": clean_text(summary, 300),
        "url": link,
        "source_name": source.get("name", source.get("id", "公开来源")),
        "source_id": source.get("id"),
        "source_type": source_type,
        "status": "unverified",
        "verification_status": "manual_review_required",
        "first_seen": old.get("first_seen", timestamp),
        "last_seen": timestamp,
        "published_at": published.isoformat() if published else None,
        "active": True,
        **fields,
    }


def rss_entries(raw: bytes) -> list[dict]:
    root = ET.fromstring(raw)
    root_kind = local_name(root.tag)
    if root_kind not in {"rss", "feed", "rdf"}:
        raise ValueError("Response is not RSS/Atom XML")
    nodes = [node for node in root.iter() if local_name(node.tag) in {"item", "entry"}]
    entries = []
    for node in nodes:
        title = child_text(node, {"title"})
        summary = child_text(node, {"description", "summary", "content", "content:encoded"})
        link = child_text(node, {"link", "guid"})
        if not link:
            for child in node:
                if local_name(child.tag) == "link" and child.attrib.get("href"):
                    link = child.attrib["href"]
                    if child.attrib.get("rel", "alternate") == "alternate":
                        break
        stamp = published_time(child_text(node, {"pubdate", "published", "updated", "date"}))
        entries.append({"title": title, "summary": summary, "url": link, "published": stamp})
    if not entries:
        raise ValueError("Feed contains no items")
    return entries


class PublicHTMLParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.page_title = ""
        self.description = ""
        self.published: dt.datetime | None = None
        self.anchors: list[tuple[str, str]] = []
        self._title = False
        self._anchor_href: str | None = None
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {key.lower(): value or "" for key, value in attrs}
        tag = tag.lower()
        if tag == "title":
            self._title = True
        elif tag == "meta":
            key = (attrs_d.get("name") or attrs_d.get("property") or "").lower()
            if key in {"description", "og:description"} and not self.description:
                self.description = attrs_d.get("content", "")
            elif key in {"article:published_time", "date", "pubdate", "publishdate", "publish_time"} and not self.published:
                self.published = published_time(attrs_d.get("content", ""))
        elif tag == "time" and attrs_d.get("datetime") and not self.published:
            self.published = published_time(attrs_d["datetime"])
        elif tag == "a" and attrs_d.get("href"):
            self._anchor_href = attrs_d["href"]
            self._anchor_text = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._title = False
        elif tag == "a" and self._anchor_href is not None:
            label = clean_text(" ".join(self._anchor_text), 240)
            link = normalize_link(self._anchor_href, self.base_url)
            if label and link:
                self.anchors.append((label, link))
            self._anchor_href = None
            self._anchor_text = []

    def handle_data(self, data: str) -> None:
        if self._title:
            self.page_title += data
        if self._anchor_href is not None:
            self._anchor_text.append(data)


def html_entries(raw: bytes, base_url: str, search_results: bool = False) -> list[dict]:
    sample = raw[:4096].lower()
    if b"captcha" in sample or b"verify" in sample or b"\xe9\xaa\x8c\xe8\xaf\x81\xe7\xa0\x81" in sample:
        raise PermissionError("CAPTCHA/verification page detected")
    parser = PublicHTMLParser(base_url)
    parser.feed(raw.decode("utf-8", errors="replace"))
    source_host = urllib.parse.urlsplit(base_url).hostname or ""
    entries = []
    seen = set()
    for label, link in parser.anchors:
        target_host = urllib.parse.urlsplit(link).hostname or ""
        if search_results and target_host.endswith(("bing.com", "baidu.com")):
            continue
        if not search_results and target_host != source_host and len(label) < 16:
            continue
        key = (label, link)
        if key in seen:
            continue
        seen.add(key)
        entries.append({"title": label, "summary": "", "url": link, "published": None})
    page_title = clean_text(parser.page_title, 200)
    if not search_results and page_title and urllib.parse.urlsplit(base_url).path not in {"", "/"}:
        entries.insert(0, {"title": page_title, "summary": clean_text(parser.description, 400), "url": base_url, "published": parser.published})
    return entries[: MAX_PER_SOURCE * 5]


def status_record(source: dict, group: str, timestamp: str, status: str = "error", **extra: object) -> dict:
    record = {
        "id": source.get("id"), "name": source.get("name", source.get("id", "未知来源")),
        "source_group": group, "channel_type": source.get("channel_type"),
        "access_method": source.get("access_method"), "configured_status": source.get("status"),
        "status": status, "count": 0, "checked_at": timestamp,
    }
    if source.get("url"):
        record["url"] = source["url"]
    record.update(extra)
    return record


def source_disposition(source: dict, group: str) -> tuple[str, str]:
    configured = source.get("status")
    access = source.get("access_method")
    channel = source.get("channel_type")
    url = source.get("url")
    if configured == "needs_login":
        return "skipped_login", "配置标明需要登录或 Cookie，未采集"
    if configured == "in_app_only" or access in {"app", "wechat", "wechat_group", "push", "offline_qr"} and not url:
        return "skipped_in_app", "仅限 App、微信、小程序、社群或线下入口，需人工核验"
    if not url:
        return "manual_review", "没有公开 HTTPS URL，需人工核验"
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return "skipped_policy", "仅允许公开 HTTPS 来源"
    host = parsed.hostname.lower()
    if host in POLICY_SKIP_HOSTS:
        return "skipped_policy", "登录、验证码或反自动化风险较高，按合规策略跳过并人工核验"
    if channel in IN_APP_TYPES and access != "browser" and group != "rss_sources":
        return "skipped_in_app", "非公开网页渠道，需在对应 App/微信内人工核验"
    return "collect", ""


def fetch_bytes(source: dict, accept: str, opener: Callable = urllib.request.urlopen) -> tuple[bytes, str, str]:
    request = urllib.request.Request(source["url"], headers={"User-Agent": UA, "Accept": accept})
    with opener(request, timeout=REQUEST_TIMEOUT) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        content_type = response.headers.get("Content-Type", "")
        final_url = response.geturl()
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("Response exceeds 1 MB safety limit")
    if not normalize_link(final_url):
        raise ValueError("Redirected outside allowed HTTPS URLs")
    return raw, content_type, final_url


def collect_source(source: dict, group: str, cfg: dict, prior: dict[str, dict], timestamp: str,
                   opener: Callable = urllib.request.urlopen) -> tuple[list[dict], dict]:
    disposition, reason = source_disposition(source, group)
    if disposition != "collect":
        return [], status_record(source, group, timestamp, disposition, reason=reason, manual_review=True)
    matchers = build_matchers(cfg)
    is_rss = group == "rss_sources" or source.get("channel_type") == "rss"
    host = urllib.parse.urlsplit(source["url"]).hostname or ""
    is_search = group == "web_search_sources" and host.endswith("bing.com") and "/search" in urllib.parse.urlsplit(source["url"]).path
    try:
        if is_rss:
            raw, content_type, final_url = fetch_bytes(source, "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9", opener)
            prefix = raw[:200].lower()
            if "xml" not in content_type.lower() and not any(token in prefix for token in (b"<rss", b"<feed", b"<?xml", b"<rdf")):
                raise ValueError("Endpoint returned HTML/non-XML instead of RSS/Atom")
            entries = rss_entries(raw)
            source_type = "rss_atom"
        else:
            raw, content_type, final_url = fetch_bytes(source, "text/html, application/xhtml+xml", opener)
            if "html" not in content_type.lower() and b"<html" not in raw[:1000].lower():
                raise ValueError("Endpoint did not return public HTML")
            entries = html_entries(raw, final_url, search_results=is_search)
            source_type = "web_search" if is_search else "public_html"
        offers = []
        for entry in entries:
            offer = make_offer(entry["title"], entry.get("summary", ""), entry["url"], source,
                               source_type, entry.get("published"), prior, timestamp, matchers)
            if offer:
                offers.append(offer)
            if len(offers) >= MAX_PER_SOURCE:
                break
        return offers, status_record(source, group, timestamp, "ok", count=len(offers),
                                     adapter=source_type, fetched_url=final_url,
                                     diagnostic="已检查公开内容；所有结果仍需人工核验")
    except PermissionError as error:
        return [], status_record(source, group, timestamp, "blocked", error=str(error)[:180], manual_review=True)
    except (urllib.error.URLError, TimeoutError, ET.ParseError, ValueError, OSError) as error:
        return [], status_record(source, group, timestamp, "error", error=str(error)[:180])


def merge_offer(target: dict[str, dict], candidate: dict) -> None:
    existing = target.get(candidate["id"])
    if not existing:
        existing = next((item for item in target.values()
                         if item.get("url") == candidate.get("url")
                         and item.get("brand") == candidate.get("brand")), None)
        if existing:
            candidate["id"] = existing["id"]
    if not existing:
        candidate["source_ids"] = [candidate.get("source_id")]
        target[candidate["id"]] = candidate
        return
    source_ids = list(dict.fromkeys(existing.get("source_ids", [existing.get("source_id")]) + [candidate.get("source_id")]))
    existing["source_ids"] = [value for value in source_ids if value]
    existing["last_seen"] = max(existing.get("last_seen", ""), candidate.get("last_seen", ""))
    if len(candidate.get("summary", "")) > len(existing.get("summary", "")):
        keep_first = existing.get("first_seen")
        existing.update(candidate)
        existing["first_seen"] = keep_first
        existing["source_ids"] = source_ids


def source_summary(statuses: list[dict]) -> dict:
    groups = {}
    states = {}
    for item in statuses:
        group = item["source_group"]
        groups.setdefault(group, {"total": 0, "checked": 0, "skipped": 0, "failed": 0, "leads": 0})
        groups[group]["total"] += 1
        groups[group]["leads"] += item.get("count", 0)
        if item["status"] == "ok":
            groups[group]["checked"] += 1
        elif item["status"] in {"error", "blocked"}:
            groups[group]["failed"] += 1
        else:
            groups[group]["skipped"] += 1
        states[item["status"]] = states.get(item["status"], 0) + 1
    return {"groups": groups, "statuses": states}


def main() -> int:
    config_path = Path(os.environ.get("MILK_TEA_CONFIG", CONFIG))
    output_path = Path(os.environ.get("MILK_TEA_OUTPUT", OUTPUT))
    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    try:
        existing = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        existing = {"offers": []}
    prior = {item["id"]: item for item in existing.get("offers", []) if item.get("id")}
    timestamp = now().isoformat(timespec="seconds")
    selected_ids = {value for value in os.environ.get("COLLECT_ONLY_IDS", "").split(",") if value}
    configured = [(group, source) for group in SOURCE_GROUPS for source in cfg.get(group, [])]
    if selected_ids:
        configured = [(group, source) for group, source in configured if source.get("id") in selected_ids]
    limit = int(os.environ.get("COLLECT_SOURCE_LIMIT", "0") or 0)
    if limit:
        configured = configured[:limit]
    workers = max(1, min(int(os.environ.get("COLLECT_MAX_WORKERS", "8")), 12))
    results: dict[str, tuple[list[dict], dict]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(collect_source, source, group, cfg, prior, timestamp): source.get("id", str(index))
                   for index, (group, source) in enumerate(configured)}
        for future in concurrent.futures.as_completed(futures):
            source_id = futures[future]
            try:
                results[source_id] = future.result()
            except Exception as error:  # Keep one unexpected adapter bug from aborting all diagnostics.
                group, source = next((g, s) for g, s in configured if s.get("id") == source_id)
                results[source_id] = ([], status_record(source, group, timestamp, "error", error=f"Unexpected: {error}"[:180]))
    merged: dict[str, dict] = {}
    statuses = []
    for group, source in configured:
        offers, status = results[source.get("id")]
        statuses.append(status)
        for offer in offers:
            merge_offer(merged, offer)
    for old in prior.values():
        try:
            seen = dt.datetime.fromisoformat(old["last_seen"])
            if seen.tzinfo and (now() - seen).days <= 7:
                old = dict(old)
                old["active"] = False
                old["status"] = "unverified_stale"
                merge_offer(merged, old)
        except (KeyError, ValueError, TypeError):
            continue
    offers = sorted(merged.values(), key=lambda item: (item.get("region") == "郑州", item.get("last_seen", "")), reverse=True)[:150]
    data = {
        "schema_version": 2,
        "generated_at": timestamp,
        "city": cfg.get("city", "郑州"),
        "timezone": cfg.get("timezone", "Asia/Shanghai"),
        "offers": offers,
        "sources": statuses,
        "diagnostics": source_summary(statuses),
        "verified_offer_count": 0,
        "unverified_lead_count": len(offers),
        "note": "仅展示公开来源发现的待人工核验线索；入口、首页、新闻或搜索结果不等于已验证优惠。不会绕过登录、验证码、App 或小程序限制。",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(output_path)
    summary = data["diagnostics"]["statuses"]
    print(f"Collected {len(offers)} unverified leads; verified offers: 0; source statuses: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
