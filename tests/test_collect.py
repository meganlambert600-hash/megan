import datetime as dt
import importlib.util
import io
import json
import pathlib
import tempfile
import unittest

MODULE = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "collect.py"
spec = importlib.util.spec_from_file_location("collect", MODULE)
collect = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collect)


def config():
    return {
        "city": "郑州",
        "focus_brands": ["霸王茶姬", "古茗", "茶百道", "蜜雪冰城", "喜茶"],
        "extended_brands": ["瑞幸咖啡"],
        "brand_aliases": {"霸王茶姬": ["CHAGEE"], "蜜雪冰城": ["蜜雪", "雪王"]},
        "collection_policy": {
            "city_filter": ["郑州", "河南"],
            "zhengzhou_areas": ["金水", "二七"],
            "deal_keywords": ["优惠", "满减", "红包", "优惠券", "买一送一", "免单", "团购", "立减"],
        },
    }


class FakeResponse:
    def __init__(self, body, content_type, url="https://example.org/feed"):
        self.body = body
        self.headers = {"Content-Type": content_type}
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _size=-1):
        return self.body

    def geturl(self):
        return self.url


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.matchers = collect.build_matchers(config())

    def test_valid_offer_lead_with_alias_and_region(self):
        value = collect.classify("郑州 CHAGEE 奶茶满减券活动", "立减 10 元", {"region": "全国", "platform": "公开资讯"}, self.matchers)
        self.assertEqual(value["region"], "郑州")
        self.assertEqual(value["brand"], "霸王茶姬")
        self.assertEqual(value["deal"]["amount_yuan"], "10")

    def test_no_coupon_keyword(self):
        self.assertIsNone(collect.classify("郑州奶茶新品上市", "", {"region": "郑州"}, self.matchers))

    def test_reject_generic_entry_as_offer(self):
        self.assertIsNone(collect.classify("蜜雪冰城小程序入口", "", {"region": "郑州"}, self.matchers))

    def test_reject_non_https_and_strip_tracking(self):
        self.assertIsNone(collect.normalize_link("javascript:alert(1)"))
        self.assertIsNone(collect.normalize_link("http://example.org/a"))
        self.assertEqual(collect.normalize_link("https://EXAMPLE.org/a?utm_source=x&item=1#part"), "https://example.org/a?item=1")

    def test_parse_rss_and_atom(self):
        rss = b"<rss><channel><item><title>Deal</title><link>https://example.org/a</link><description>Text</description><pubDate>Thu, 12 Nov 2026 10:00:00 GMT</pubDate></item></channel></rss>"
        atom = b"<feed xmlns='http://www.w3.org/2005/Atom'><entry><title>Deal</title><link href='https://example.org/b'/><summary>Text</summary><updated>2026-11-12T10:00:00Z</updated></entry></feed>"
        self.assertEqual(collect.rss_entries(rss)[0]["url"], "https://example.org/a")
        self.assertEqual(collect.rss_entries(atom)[0]["url"], "https://example.org/b")

    def test_reject_html_disguised_as_feed(self):
        source = {"id": "rss", "name": "RSS", "url": "https://example.org/feed", "channel_type": "rss", "access_method": "rss_reader", "status": "ok"}
        opener = lambda *_args, **_kwargs: FakeResponse(b"<html><title>not feed</title></html>", "text/html")
        offers, status = collect.collect_source(source, "rss_sources", config(), {}, "2026-11-13T00:00:00+00:00", opener)
        self.assertEqual(offers, [])
        self.assertEqual(status["status"], "error")
        self.assertIn("non-XML", status["error"])

    def test_collect_public_rss_offer(self):
        body = """<rss><channel><item><title>郑州蜜雪冰城买一送一优惠</title><link>https://example.org/deal</link><description>活动时间 11月13日</description><pubDate>Fri, 13 Nov 2026 01:00:00 GMT</pubDate></item></channel></rss>""".encode()
        source = {"id": "rss", "name": "RSS", "url": "https://example.org/feed", "channel_type": "rss", "access_method": "rss_reader", "status": "ok", "region": "郑州"}
        opener = lambda *_args, **_kwargs: FakeResponse(body, "application/rss+xml")
        original_now = collect.now
        collect.now = lambda: dt.datetime(2026, 11, 13, tzinfo=dt.timezone.utc)
        try:
            offers, status = collect.collect_source(source, "rss_sources", config(), {}, "2026-11-13T02:00:00+00:00", opener)
        finally:
            collect.now = original_now
        self.assertEqual(status["status"], "ok")
        self.assertEqual(status["count"], 1)
        self.assertEqual(offers[0]["verification_status"], "manual_review_required")
        self.assertEqual(offers[0]["brand"], "蜜雪冰城")

    def test_collect_public_html_anchor(self):
        body = """<html><head><meta charset='utf-8'><title>活动页</title></head><body><a href='/deal'>11月13日郑州古茗奶茶优惠券满减活动</a><a href='/'>官网首页</a></body></html>""".encode()
        source = {"id": "web", "name": "公开活动页", "url": "https://example.org/events", "channel_type": "web", "access_method": "browser", "status": "ok", "region": "郑州"}
        opener = lambda *_args, **_kwargs: FakeResponse(body, "text/html; charset=utf-8", "https://example.org/events")
        original_now = collect.now
        collect.now = lambda: dt.datetime(2026, 11, 13, tzinfo=dt.timezone.utc)
        try:
            offers, status = collect.collect_source(source, "official_links", config(), {}, "2026-11-13T02:00:00+00:00", opener)
        finally:
            collect.now = original_now
        self.assertEqual(status["adapter"], "public_html")
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["url"], "https://example.org/deal")

    def test_undated_html_lead_is_not_published(self):
        fields = collect.make_offer("郑州古茗奶茶优惠券", "满减活动", "https://example.org/deal", {"id": "web", "name": "Web", "region": "郑州"}, "public_html", None, {}, "2026-11-13T00:00:00+00:00", self.matchers)
        self.assertIsNone(fields)

    def test_search_adapter_excludes_engine_links(self):
        body = b"<html><a href='https://www.bing.com/search?q=x'>next</a><a href='https://deals.example/deal'>Zhengzhou milk tea coupon</a></html>"
        entries = collect.html_entries(body, "https://www.bing.com/search?q=tea", search_results=True)
        self.assertEqual([item["url"] for item in entries], ["https://deals.example/deal"])

    def test_local_search_rejects_another_city_result(self):
        body = """<html><a href='https://news.example/nanchang'>
        南昌11月9日奶茶免单优惠活动汇总
        </a></html>""".encode()
        source = {
            "id": "search", "name": "郑州奶茶搜索",
            "url": "https://www.bing.com/search?q=zhengzhou+tea", "status": "ok",
            "access_method": "browser", "region": "郑州",
        }
        opener = lambda *_args, **_kwargs: FakeResponse(
            body, "text/html; charset=utf-8", source["url"]
        )
        original_now = collect.now
        collect.now = lambda: dt.datetime(2026, 11, 13, tzinfo=dt.timezone.utc)
        try:
            offers, status = collect.collect_source(
                source, "web_search_sources", config(), {},
                "2026-11-13T02:00:00+00:00", opener,
            )
        finally:
            collect.now = original_now
        self.assertEqual(status["status"], "ok")
        self.assertEqual(offers, [])
        self.assertFalse(collect.search_region_matches(
            "南昌11月9日奶茶免单优惠活动汇总", "", source,
            "web_search_sources", config(), self.matchers,
        ))

    def test_captcha_page_is_blocked(self):
        source = {"id": "web", "name": "公开搜索", "url": "https://example.org/search", "channel_type": "web", "access_method": "browser", "status": "ok"}
        opener = lambda *_args, **_kwargs: FakeResponse(b"<html>captcha verify</html>", "text/html", source["url"])
        offers, status = collect.collect_source(source, "web_search_sources", config(), {}, "2026-11-13T00:00:00+00:00", opener)
        self.assertEqual(offers, [])
        self.assertEqual(status["status"], "blocked")
        self.assertTrue(status["manual_review"])

    def test_login_and_in_app_are_skipped(self):
        login = {"id": "login", "status": "needs_login", "url": "https://example.org", "access_method": "browser"}
        app = {"id": "app", "status": "in_app_only", "access_method": "app", "channel_type": "app"}
        self.assertEqual(collect.source_disposition(login, "official_links")[0], "skipped_login")
        self.assertEqual(collect.source_disposition(app, "brand_official")[0], "skipped_in_app")

    def test_policy_skips_captcha_prone_social_search(self):
        source = {"id": "wx", "status": "ok", "url": "https://weixin.sogou.com/weixin?query=x", "access_method": "browser"}
        self.assertEqual(collect.source_disposition(source, "web_search_sources")[0], "skipped_policy")

    def test_dedupe_uses_brand_title_amount_and_date(self):
        fields = {"brand": "古茗", "deal": {"amount_yuan": "10", "date_mentions": ["11月13日"]}}
        first = collect.fingerprint("古茗奶茶优惠券 10元 11月13日", "https://a.example/x", fields)
        second = collect.fingerprint("古茗奶茶优惠券 10元 11月13日", "https://b.example/y", fields)
        self.assertEqual(first, second)

    def test_merge_dedupes_same_url_with_title_variation(self):
        base = {"id": "one", "url": "https://example.org/deal", "brand": "古茗", "summary": "", "source_id": "a", "first_seen": "1", "last_seen": "1"}
        variation = {"id": "two", "url": "https://example.org/deal", "brand": "古茗", "summary": "more", "source_id": "b", "first_seen": "2", "last_seen": "2"}
        merged = {}
        collect.merge_offer(merged, base)
        collect.merge_offer(merged, variation)
        self.assertEqual(len(merged), 1)
        self.assertEqual(next(iter(merged.values()))["source_ids"], ["a", "b"])

    def test_source_summary_has_all_outcome_buckets(self):
        statuses = [
            {"source_group": "rss_sources", "status": "ok", "count": 2},
            {"source_group": "rss_sources", "status": "error", "count": 0},
            {"source_group": "brand_official", "status": "skipped_in_app", "count": 0},
        ]
        summary = collect.source_summary(statuses)
        self.assertEqual(summary["groups"]["rss_sources"]["checked"], 1)
        self.assertEqual(summary["groups"]["rss_sources"]["failed"], 1)
        self.assertEqual(summary["groups"]["brand_official"]["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
