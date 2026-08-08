from __future__ import annotations

from config import settings
from services import content_source_text, database, wechat_article_candidate, wechat_discovery
from services.cache import cache_dir_for_url, read_cache_meta, write_cache_meta
from services.wechat_discovery import VerifiedArticle
from services.wechat_public_search import _parse_results, _search_sogou, _sogou_script_target
from services.wechat_urls import (
    album_identity,
    article_identity_from_html,
    canonical_wechat_article_id,
    is_wechat_album_url,
    normalize_wechat_url,
)


def test_wechat_article_identity_ignores_tracking_and_sensitive_query_values():
    first = (
        "http://mp.weixin.qq.com/s?__biz=MzA1&mid=123&idx=2&sn=abc"
        "&scene=21&pass_ticket=secret"
    )
    second = "https://mp.weixin.qq.com/s?__biz=MzA1&mid=123&idx=2&sn=abc"

    assert normalize_wechat_url(first) == second
    assert canonical_wechat_article_id(first) == "wechat:MzA1:123:2"
    assert canonical_wechat_article_id(second) == "wechat:MzA1:123:2"


def test_wechat_url_normalization_does_not_decode_timestamp_as_html_times_entity():
    url = "https://mp.weixin.qq.com/s?src=11&timestamp=1785472759&signature=abc"

    assert "timestamp=1785472759" in normalize_wechat_url(url)
    assert "%C3%97tamp" not in normalize_wechat_url(url)


def test_wechat_identity_can_be_recovered_from_short_link_page_html():
    identity = article_identity_from_html(
        """
        <script>
        window.biz = "MzEyMzQ1Njc4OQ==";
        window.mid = "987654";
        window.idx = "3";
        </script>
        """
    )

    assert identity.canonical_id == "wechat:MzEyMzQ1Njc4OQ==:987654:3"


def test_article_verification_ignores_javascript_biz_expression_before_real_identity(monkeypatch):
    expected_biz = "MzI5MDQ2NjY4OQ=="
    article_url = (
        "https://mp.weixin.qq.com/s?__biz=MzI5MDQ2NjY4OQ%3D%3D"
        "&mid=2247605606&idx=1&sn=fixture"
    )

    class Response:
        status_code = 200
        url = article_url
        text = f"""
        <html><body>
          <script>
            var generated = "?__biz=" + biz;
            var biz = "+ biz +";
            window.biz = "{expected_biz}";
            window.mid = "2247605606";
            window.idx = "1";
          </script>
          <h1 class="rich_media_title">技大之星 · 黄大维</h1>
          <strong id="js_name">深圳技术大学</strong>
          <div id="js_content">文章正文</div>
        </body></html>
        """

        @staticmethod
        def raise_for_status():
            return None

    monkeypatch.setattr(
        wechat_article_candidate,
        "fetch_wechat_page",
        lambda url, timeout: Response(),
    )

    article = wechat_article_candidate.verify_article(
        article_url,
        expected_biz=expected_biz,
    )

    assert article.biz == expected_biz
    assert article.canonical_source_id == "wechat:MzI5MDQ2NjY4OQ==:2247605606:1"
    assert "文章正文" in article.page_html


def test_verified_wechat_page_can_prime_readable_article_cache(tmp_path, monkeypatch):
    article_url = "https://mp.weixin.qq.com/s/verified-snapshot"
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(content_source_text, "_sync_fetched_article_metadata", lambda *_args: None)

    article_info = content_source_text.cache_preloaded_wechat_article(
        "content-1",
        article_url,
        """
        <html><body>
          <h1 class="rich_media_title">已校验文章</h1>
          <strong id="js_name">测试公众号</strong>
          <div class="rich_media_content" id="js_content">
            <p>这段正文应直接进入本机缓存。</p>
          </div>
        </body></html>
        """,
    )

    metadata = read_cache_meta(cache_dir_for_url(article_url))
    assert "这段正文应直接进入本机缓存" in article_info["body_text"]
    assert metadata["article_info"]["body_text"] == article_info["body_text"]
    assert metadata["article_capture"]["last_error"] == ""


def test_verified_page_does_not_replace_an_existing_enriched_snapshot(tmp_path, monkeypatch):
    article_url = "https://mp.weixin.qq.com/s/existing-snapshot"
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    cache_dir = cache_dir_for_url(article_url)
    existing = {
        "title": "已有文章",
        "body_text": "已有正文和图片文字",
        "image_ocr": {"attempted": True, "recognized_count": 2},
    }
    write_cache_meta(cache_dir, {"article_info": existing})

    def unexpected_parse(*_args, **_kwargs):
        raise AssertionError("不应重新解析并覆盖缓存")

    monkeypatch.setattr(
        content_source_text,
        "parse_wechat_article_html",
        unexpected_parse,
    )

    result = content_source_text.cache_preloaded_wechat_article(
        "content-1",
        article_url,
        "<div id='js_content'>新响应</div>",
    )

    assert result == existing
    assert read_cache_meta(cache_dir)["article_info"] == existing


def test_import_reuses_verified_page_before_queuing_background_work(tmp_path, monkeypatch):
    db_path = tmp_path / "candidate.db"
    article_url = "https://mp.weixin.qq.com/s?__biz=MzRun&mid=1&idx=1"
    with database.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE content_items (
                id TEXT PRIMARY KEY,
                status TEXT,
                source_provider TEXT,
                source_url TEXT,
                canonical_source_id TEXT,
                title TEXT,
                source_name TEXT,
                published_at TEXT,
                library_folder_id TEXT,
                updated_at TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO content_items (
                id, status, source_provider, source_url, canonical_source_id, title,
                source_name, published_at, updated_at
            ) VALUES ('content-1', 'to_read', 'wechat', ?, 'wechat:MzRun:1:1', '', '', '', '')
            """,
            (article_url,),
        )
        connection.commit()

    calls = []
    monkeypatch.setattr(wechat_article_candidate, "connect", lambda: database.connect(db_path))
    monkeypatch.setattr(
        wechat_article_candidate,
        "cache_preloaded_wechat_article",
        lambda item_id, source_url, page_html, *, fallback_title: calls.append(
            ("cache", item_id, source_url, page_html, fallback_title)
        ),
    )
    monkeypatch.setattr(
        wechat_article_candidate,
        "enqueue_article_source_preparation",
        lambda item_id: calls.append(("enqueue", item_id)),
    )

    result = wechat_article_candidate.import_verified_article(
        VerifiedArticle(
            url=article_url,
            canonical_source_id="wechat:MzRun:1:1",
            title="已校验文章",
            source_name="测试公众号",
            biz="MzRun",
            published_at="2026-08-01",
            page_html="<div id='js_content'>文章正文</div>",
        ),
        auto_analyze=False,
    )

    assert result == ("content-1", True)
    assert calls[0][0] == "cache"
    assert calls[1] == ("enqueue", "content-1")


def test_album_identity_requires_public_album_parameters():
    url = "https://mp.weixin.qq.com/mp/appmsgalbum?__biz=MzAlbum&album_id=42"

    assert is_wechat_album_url(url) is True
    assert album_identity(url) == ("MzAlbum", "42")


def test_discovery_migration_promotes_legacy_full_url_identity(tmp_path):
    db_path = tmp_path / "legacy.db"
    legacy_url = "https://mp.weixin.qq.com/s?__biz=MzOld&mid=9&idx=1&scene=21"
    with database.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE content_items (
                id TEXT PRIMARY KEY,
                source_provider TEXT,
                source_url TEXT,
                canonical_source_id TEXT,
                UNIQUE(source_provider, canonical_source_id)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO content_items (id, source_provider, source_url, canonical_source_id)
            VALUES ('legacy', 'wechat', ?, ?)
            """,
            (legacy_url, legacy_url),
        )
        database._migration_087_wechat_public_discovery(connection)
        row = connection.execute(
            "SELECT canonical_source_id FROM content_items WHERE id = 'legacy'"
        ).fetchone()

    assert row["canonical_source_id"] == "wechat:MzOld:9:1"


def test_album_parser_collects_nested_articles_once():
    payload = {
        "getalbum_resp": {
            "article_list": [
                {
                    "title": "第一篇",
                    "url": "https://mp.weixin.qq.com/s?__biz=MzA&mid=1&idx=1",
                    "msgid": "1",
                    "itemidx": "1",
                    "create_time": 1_700_000_000,
                },
                {
                    "items": [
                        {
                            "title": "第二篇",
                            "url": "https://mp.weixin.qq.com/s?__biz=MzA&mid=2&idx=1",
                        },
                        {
                            "title": "重复",
                            "url": "https://mp.weixin.qq.com/s?__biz=MzA&mid=1&idx=1",
                        },
                    ]
                },
            ]
        }
    }

    articles = wechat_discovery._album_articles(payload)

    assert [item["title"] for item in articles] == ["第一篇", "第二篇"]
    assert (articles[0]["msgid"], articles[0]["itemidx"]) == ("1", "1")


def test_album_discovery_uses_last_article_as_next_page_cursor(monkeypatch):
    requested_urls = []
    inserted_urls = []
    saved_cursors = []
    first_page = {
        "getalbum_resp": {
            "continue_flag": 1,
            "article_list": [
                {
                    "title": "第一篇",
                    "url": "https://mp.weixin.qq.com/s?__biz=MzA&mid=10&idx=1",
                    "msgid": "10",
                    "itemidx": "1",
                },
                {
                    "title": "第二篇",
                    "url": "https://mp.weixin.qq.com/s?__biz=MzA&mid=11&idx=2",
                    "msgid": "11",
                    "itemidx": "2",
                },
            ],
        }
    }
    second_page = {
        "getalbum_resp": {
            "continue_flag": 0,
            "article_list": [
                {
                    "title": "第三篇",
                    "url": "https://mp.weixin.qq.com/s?__biz=MzA&mid=12&idx=1",
                    "msgid": "12",
                    "itemidx": "1",
                }
            ],
        }
    }

    def fetch(url: str, *, referer: str):
        requested_urls.append(url)
        return second_page if "begin_msgid=11" in url else first_page

    def insert_candidate(run_id: str, url: str, **kwargs):
        inserted_urls.append(url)
        return True

    monkeypatch.setattr(wechat_discovery, "_fetch_album_payload", fetch)
    monkeypatch.setattr(wechat_discovery, "_insert_candidate", insert_candidate)
    monkeypatch.setattr(
        wechat_discovery,
        "_save_cursor",
        lambda run_id, **cursor: saved_cursors.append(cursor),
    )

    wechat_discovery._discover_album(
        "run-1",
        {
            "biz": "MzA",
            "album_id": "album-1",
            "album_url": "https://mp.weixin.qq.com/mp/appmsgalbum?__biz=MzA&album_id=album-1",
        },
        on_progress=None,
        cancel_check=None,
    )

    assert len(requested_urls) == 2
    assert "begin_msgid=11" in requested_urls[1]
    assert "begin_itemidx=2" in requested_urls[1]
    assert len(inserted_urls) == 3
    assert saved_cursors[0]["begin_msgid"] == "11"


def test_manual_discovery_run_persists_partial_failures(tmp_path, monkeypatch):
    db_path = tmp_path / "discovery.db"
    with database.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE content_items (
                id TEXT PRIMARY KEY,
                source_provider TEXT,
                source_url TEXT,
                canonical_source_id TEXT,
                UNIQUE(source_provider, canonical_source_id)
            )
            """
        )
        connection.execute(
            "INSERT INTO content_items (id, source_provider) VALUES ('content-1', 'wechat')"
        )
        database._migration_087_wechat_public_discovery(connection)
        database._migration_088_wechat_seed_discovery_review(connection)
        database._migration_089_wechat_album_subscriptions(connection)
        connection.commit()

    monkeypatch.setattr(wechat_discovery, "ensure_database_initialized", lambda: None)
    monkeypatch.setattr(wechat_discovery, "connect", lambda: database.connect(db_path))
    first_url = "https://mp.weixin.qq.com/s?__biz=MzRun&mid=1&idx=1"
    second_url = "https://mp.weixin.qq.com/s?__biz=MzRun&mid=2&idx=1"
    run = wechat_discovery.create_discovery_run(f"{first_url}\n{second_url}")
    assert "request" not in wechat_discovery.list_discovery_runs()[0]

    def verify(url: str, *, expected_biz: str = "") -> VerifiedArticle:
        if "mid=2" in url:
            raise wechat_discovery.WeChatDiscoveryError("文章已删除")
        return VerifiedArticle(
            url=url,
            canonical_source_id="wechat:MzRun:1:1",
            title="可用文章",
            source_name="测试公众号",
            biz="MzRun",
            published_at="2026-07-31",
        )

    monkeypatch.setattr(wechat_discovery, "_verify_article", verify)
    monkeypatch.setattr(
        wechat_discovery,
        "_import_verified_article",
        lambda article, *, auto_analyze: ("content-1", False),
    )

    result = wechat_discovery.run_wechat_discovery(run["id"])

    assert result["status"] == "succeeded"
    assert result["candidate_count"] == 2
    assert result["verified_count"] == 1
    assert result["imported_count"] == 1
    assert result["failed_count"] == 1


def test_public_search_parser_keeps_only_wechat_articles_and_unwraps_duckduckgo():
    page = """
    <a class="result__a"
       href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fmp.weixin.qq.com%2Fs%3F__biz%3DMzSeed%26mid%3D2%26idx%3D1">
       同公众号文章
    </a>
    <a class="result__a" href="https://example.com/not-wechat">无关页面</a>
    """

    results = _parse_results("duckduckgo", '"测试号" site:mp.weixin.qq.com/s', page)

    assert len(results) == 1
    assert results[0].url == "https://mp.weixin.qq.com/s?__biz=MzSeed&mid=2&idx=1"
    assert results[0].provider == "duckduckgo"


def test_sogou_redirect_script_is_reassembled_without_corrupting_timestamp():
    page = """
    <script>
      var url = '';
      url += 'https://mp.weixin.qq.com/s?src=11';
      url += '&timestamp=1785472759&';
      url += 'signature=abc';
    </script>
    """

    assert _sogou_script_target(page) == (
        "https://mp.weixin.qq.com/s?src=11&timestamp=1785472759&signature=abc"
    )


def test_sogou_search_never_follows_an_external_result_redirect():
    class Response:
        status_code = 200
        url = "https://weixin.sogou.com/weixin?type=2"
        text = '<div class="txt-box"><h3><a href="https://example.com/trap">文章</a></h3></div>'

        @staticmethod
        def raise_for_status():
            return None

    class Session:
        calls = []

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            if len(self.calls) > 1:
                raise AssertionError("不应访问非搜狗跳转地址")
            return Response()

    session = Session()

    assert _search_sogou(session, {"User-Agent": "test"}, "测试号") == []
    assert len(session.calls) == 1


def test_seed_discovery_requires_review_before_search_candidates_import(tmp_path, monkeypatch):
    db_path = tmp_path / "seed-discovery.db"
    with database.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE content_items (
                id TEXT PRIMARY KEY,
                source_provider TEXT,
                source_url TEXT,
                canonical_source_id TEXT,
                UNIQUE(source_provider, canonical_source_id)
            )
            """
        )
        connection.execute(
            "INSERT INTO content_items (id, source_provider) VALUES ('seed-item', 'wechat')"
        )
        database._migration_087_wechat_public_discovery(connection)
        database._migration_088_wechat_seed_discovery_review(connection)
        database._migration_089_wechat_album_subscriptions(connection)
        connection.commit()

    monkeypatch.setattr(wechat_discovery, "ensure_database_initialized", lambda: None)
    monkeypatch.setattr(wechat_discovery, "connect", lambda: database.connect(db_path))
    seed_url = "https://mp.weixin.qq.com/s?__biz=MzSeed&mid=1&idx=1"
    candidate_url = "https://mp.weixin.qq.com/s?__biz=MzSeed&mid=2&idx=1"
    run = wechat_discovery.create_discovery_run(seed_url, strategy="seed")

    def verify(url: str, *, expected_biz: str = "") -> VerifiedArticle:
        assert expected_biz in {"", "MzSeed"}
        mid = "2" if "mid=2" in url else "1"
        return VerifiedArticle(
            url=url,
            canonical_source_id=f"wechat:MzSeed:{mid}:1",
            title=f"文章 {mid}",
            source_name="测试公众号",
            biz="MzSeed",
            published_at="2026-07-31",
        )

    monkeypatch.setattr(wechat_discovery, "_verify_article", verify)
    monkeypatch.setattr(
        wechat_discovery,
        "_import_verified_article",
        lambda article, *, auto_analyze: ("seed-item", article.canonical_source_id.endswith(":1:1")),
    )
    monkeypatch.setattr(
        wechat_discovery,
        "search_public_wechat_articles",
        lambda query: (
            [
                wechat_discovery.SearchResult(
                    url=candidate_url,
                    title="搜索标题",
                    provider="bing",
                    query=query,
                    rank=1,
                )
            ],
            {"bing": {"status": "ok", "result_count": 1}},
        ),
    )

    result = wechat_discovery.run_wechat_discovery(run["id"])
    candidates = wechat_discovery.list_discovery_candidates(run["id"])

    assert result["status"] == "succeeded"
    assert result["review_required"] == 1
    assert result["source_title"] == "测试公众号"
    assert candidates[0]["import_state"] == "duplicate"
    assert candidates[1]["verification_state"] == "verified"
    assert candidates[1]["import_state"] == "pending"

    imported = wechat_discovery.import_reviewed_candidates(
        run["id"],
        [candidates[1]["id"]],
    )

    assert imported["review_required"] == 0
    assert imported["review_import_status"] == "succeeded"
