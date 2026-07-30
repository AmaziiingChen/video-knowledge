from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from config import settings
from services.content_source_text import inspect_content_text_readiness, load_content_source_text
from services.database import connect, initialize_database
from services.forum_capture_parser import (
    FeedCandidate,
    detect_feed_candidates,
    estimate_display_time,
    feed_candidates_equivalent,
    latest_tab_position,
    looks_like_deleted_post,
    looks_like_detail_bottom,
    looks_like_feed_page,
    looks_like_transient_overlay,
    measure_ocr_vertical_displacement,
    parse_detail_capture,
    parse_feed_candidate,
)
from services.forum_capture_repository import ForumCaptureRepository
from services.markdown_sync import get_markdown_state
from services.repository import ContentRepository
from services.macos_miniprogram import (
    MacOSMiniProgramDriver,
    MiniProgramDriverError,
    _find_feed_top_button,
)
from services.miniprogram_forum_settings import (
    MiniProgramForumScheduler,
    load_miniprogram_forum_settings,
    update_miniprogram_forum_settings,
)
from services.miniprogram_forum_collector import (
    DeletedForumPost,
    MiniProgramForumCollector,
    miniprogram_forum_collector,
)


def ocr_payload(lines: list[tuple[str, int, int]], *, width: int = 828, height: int = 1560):
    return {
        "available": True,
        "width": width,
        "height": height,
        "lines": [
            {"text": text, "x": x, "y": y, "width": 220, "height": 32, "confidence": 0.95}
            for text, x, y in lines
        ],
    }


class ForumCaptureParserTests(unittest.TestCase):
    @staticmethod
    def _candidate(*, author: str, body: str, signature: str) -> FeedCandidate:
        return FeedCandidate(
            display_time="2天前",
            author_hint=author,
            card_text=f"{author}\n{body}",
            signature=signature,
            click_x=300,
            click_y=500,
            top=300,
            bottom=700,
            body_text=body,
        )

    def test_detect_feed_candidates_uses_time_labels_as_card_anchors(self):
        payload = ocr_payload(
            [
                ("本校", 420, 60),
                ("用户甲", 130, 390),
                ("2天前", 130, 435),
                ("第一篇正文", 45, 520),
                ("用户乙", 130, 930),
                ("3小时前", 130, 975),
                ("第二篇正文", 45, 1060),
            ]
        )

        candidates = detect_feed_candidates(payload)

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0].author_hint, "用户甲")
        self.assertEqual(candidates[1].display_time, "3小时前")
        self.assertGreater(candidates[0].click_y, 450)
        self.assertFalse(looks_like_feed_page(payload))

    def test_feed_page_requires_forum_navigation_and_categories(self):
        payload = ocr_payload(
            [
                ("本校", 420, 60), ("全部", 30, 220), ("避雷", 140, 220),
                ("校园日常", 500, 220), ("用户甲", 130, 390),
                ("2天前", 130, 435), ("正文", 45, 520),
            ]
        )

        self.assertTrue(looks_like_feed_page(payload))
        payload["lines"][0]["text"] = "本松"
        self.assertTrue(looks_like_feed_page(payload))
        payload["lines"][0]["text"] = "本校••一"
        self.assertTrue(looks_like_feed_page(payload))
        payload["lines"][0]["text"] = "关注 高校圈 本校•••一"
        self.assertTrue(looks_like_feed_page(payload))

    def test_feed_page_allows_recommendation_viewport_without_timestamp(self):
        payload = ocr_payload(
            [
                ("本校", 420, 60),
                ("全部", 30, 220),
                ("避雷", 140, 220),
                ("校园日常", 500, 220),
                ("达人推荐", 40, 650),
            ]
        )

        self.assertTrue(looks_like_feed_page(payload))

    def test_feed_candidate_identity_ignores_rotating_header_and_symbol_author(self):
        def payload(headline: str):
            return ocr_payload(
                [
                    ("本校", 420, 60), (headline, 40, 180), ("・・・", 130, 390),
                    ("2天前", 130, 435), ("租计算器", 45, 520),
                    ("南区女生", 45, 575), ("带价来", 45, 630),
                    ("评论者…：还有吗", 45, 690),
                ]
            )

        first = detect_feed_candidates(payload("01 第一条轮播"))[0]
        second = detect_feed_candidates(payload("09 完全不同的轮播"))[0]

        self.assertEqual(first.signature, second.signature)
        self.assertEqual(first.author_hint, "")

    def test_feed_candidates_ignore_talent_recommendation_and_choose_detail_by_content(self):
        payload = ocr_payload(
            [
                ("本校", 420, 60), ("全部", 30, 220), ("避雷", 140, 220),
                ("作者甲", 130, 350), ("21分钟前", 130, 395),
                ("完整的简短正文", 45, 470),
                ("达人推荐", 45, 650), ("小箙ii", 45, 750),
                ("作者乙", 130, 1050), ("22分钟前", 130, 1095),
                ("这是超过五行后会被省略的正文…", 45, 1170),
                ("评论者…：有用的回复", 45, 1250),
            ]
        )

        candidates = detect_feed_candidates(payload)

        self.assertEqual(len(candidates), 2)
        self.assertNotIn("达人推荐", candidates[0].card_text)
        self.assertFalse(candidates[0].needs_detail)
        self.assertTrue(candidates[1].truncated)
        self.assertTrue(candidates[1].has_comments)
        self.assertTrue(candidates[1].needs_detail)

    def test_feed_candidate_excludes_ocr_variants_of_comment_preview_ellipsis(self):
        for preview in (
            "信使猹爱举.：还打不开",
            "信使猹爱举..：还打不开",
            "信使猹爱举•：还打不开",
            "信使猹爱举…：还打不开",
        ):
            with self.subTest(preview=preview):
                payload = ocr_payload(
                    [
                        ("信使猹在喝冷饮", 130, 350), ("3小时前", 130, 395),
                        ("为啥教务系统打不开了", 45, 470),
                        (preview, 45, 525),
                        ("共4条回复>", 45, 580),
                    ]
                )

                candidate = detect_feed_candidates(payload)[0]

                self.assertEqual(candidate.body_text, "为啥教务系统打不开了")
                self.assertTrue(candidate.has_comments)

    def test_visible_no_comment_post_can_be_parsed_without_opening_detail(self):
        payload = ocr_payload(
            [
                ("作者甲", 130, 350), ("21分钟前", 130, 395),
                ("完整的简短正文", 45, 470),
                ("作者乙", 130, 800), ("22分钟前", 130, 845),
                ("下一篇正文", 45, 920),
            ]
        )
        candidate = detect_feed_candidates(payload)[0]

        parsed = parse_feed_candidate(
            candidate,
            captured_at=datetime.fromisoformat("2026-07-17T10:00:00+08:00"),
        )

        self.assertEqual(parsed["body_text"], "完整的简短正文")
        self.assertTrue(parsed["capture_complete"])
        self.assertEqual(parsed["comments"], [])

    def test_feed_candidate_fuzzy_identity_tolerates_small_ocr_changes(self):
        first = self._candidate(
            author="哈密瓜在鬼屋大叫",
            body="因本人不在学校，宿舍还没搬，老师在催了",
            signature="first",
        )
        noisy = self._candidate(
            author="哈宓爪在鬼犀大叫",
            body="因本人不在学校，宿舍还没搬，老师在催了。",
            signature="second",
        )
        different = self._candidate(
            author="哈密瓜在鬼屋大叫",
            body="为什么教务系统打不开了",
            signature="third",
        )
        expanded = self._candidate(
            author="哈密瓜在鬼屋大叫",
            body=(
                "因本人不在学校，宿舍还没般，老师在催了！"
                "比较辛苦，是我所有的东西，从E3搬到E2"
            ),
            signature="fourth",
        )

        self.assertTrue(feed_candidates_equivalent(first, noisy))
        self.assertTrue(feed_candidates_equivalent(first, expanded))
        self.assertFalse(feed_candidates_equivalent(first, different))

    def test_ocr_displacement_reports_page_down_as_negative_pixels(self):
        before = ocr_payload(
            [("匿名用户甲", 130, 900), ("宿舍搬迁求助正文", 45, 1000)]
        )
        after = ocr_payload(
            [("匿名用户甲", 130, 800), ("宿舍搬迁求助正文", 45, 900)]
        )

        self.assertEqual(measure_ocr_vertical_displacement(before, after), -100.0)
        self.assertEqual(measure_ocr_vertical_displacement(before, before), 0.0)
        self.assertEqual(measure_ocr_vertical_displacement(after, before), 100.0)

    def test_detail_bottom_tolerates_ocr_line_wrap(self):
        payload = ocr_payload(
            [
                ("长按评论可赞赏，遇到热心猹友可以给TA一点鼓", 100, 1300),
                ("励", 400, 1350),
            ]
        )

        self.assertTrue(looks_like_detail_bottom(payload))

    def test_deleted_post_detection_tolerates_wrap_and_excludes_deleted_comment(self):
        deleted_post = ocr_payload(
            [("详情", 380, 60), ("哦哦，来晚了，帖子已经被删", 120, 800), ("除", 400, 850)]
        )
        deleted_comment = ocr_payload(
            [("详情", 380, 60), ("该评论已被删除", 120, 800)]
        )

        self.assertTrue(looks_like_deleted_post(deleted_post))
        self.assertFalse(looks_like_deleted_post(deleted_comment))

    def test_latest_tab_requires_the_detail_comment_tab_pair(self):
        valid = ocr_payload([('推荐', 50, 750), ('最新', 150, 750)])
        unrelated = ocr_payload([('最新', 500, 250)])

        self.assertIsNotNone(latest_tab_position(valid))
        self.assertIsNone(latest_tab_position(unrelated))

    def test_share_surfaces_are_classified_as_transient_overlays(self):
        share_sheet = ocr_payload([('分享至', 50, 900), ('生成分享图', 50, 1000)])
        share_card = ocr_payload([('保存图片', 50, 1100), ('长按扫码查看回复', 50, 1200)])

        self.assertTrue(looks_like_transient_overlay(share_sheet))
        self.assertTrue(looks_like_transient_overlay(share_card))

    def test_parse_detail_extracts_body_comment_and_comment_count(self):
        payload = ocr_payload(
            [
                ("详情", 380, 60),
                ("匿名用户", 130, 160),
                ("2天前", 130, 220),
                ("正文第一行", 30, 330),
                ("正文第二行", 30, 390),
                ("收藏", 450, 630),
                ("推荐", 60, 750),
                ("最新", 160, 750),
                ("全部评论•40条", 30, 860),
                ("评论用户", 130, 950),
                ("2天前", 130, 1010),
                ("评论正文", 130, 1080),
            ]
        )

        parsed = parse_detail_capture(
            [payload],
            captured_at=datetime.fromisoformat("2026-07-16T10:00:00+08:00"),
        )

        self.assertEqual(parsed["author_label"], "匿名用户")
        self.assertEqual(parsed["body_text"], "正文第一行\n正文第二行")
        self.assertEqual(parsed["comment_count"], 40)
        self.assertEqual(parsed["comments"][0]["body_text"], "评论正文")

    def test_detail_prefers_detail_author_and_merges_noisy_repeated_frames(self):
        first = ocr_payload(
            [("详情", 380, 60), ("真实作者", 130, 160), ("2天前", 130, 220),
             ("出售教材", 30, 330), ("北区自提", 30, 390)]
        )
        repeated = ocr_payload(
            [("详情", 380, 60), ("真实作者", 130, 160), ("2天前", 130, 220),
             ("出售教材", 30, 330), ("北区自取", 30, 390)]
        )

        parsed = parse_detail_capture(
            [first, repeated],
            captured_at=datetime.fromisoformat("2026-07-16T10:00:00+08:00"),
            author_hint="・・・",
        )

        self.assertEqual(parsed["author_label"], "真实作者")
        self.assertEqual(parsed["body_text"], "出售教材\n北区自提")

    def test_detail_tolerates_follow_button_and_ocr_comment_marker(self):
        payload = ocr_payload(
            [
                ("详情", 380, 60), ("真实作者", 130, 160), ("关注", 640, 188),
                ("2天前", 130, 220), ("求助正文", 30, 330),
                ("全部評・1条", 30, 700), ("评论者", 130, 780),
                ("2天前", 130, 840), ("有用回复", 130, 900),
                ("长按评论可赞赏，遇到热心猹友可以给TA一点鼓", 130, 1040),
                ("励", 400, 1090),
            ]
        )

        parsed = parse_detail_capture(
            [payload], captured_at=datetime.fromisoformat("2026-07-16T10:00:00+08:00")
        )

        self.assertEqual(parsed["author_label"], "真实作者")
        self.assertEqual(parsed["body_text"], "求助正文")
        self.assertEqual(parsed["comment_count"], 1)
        self.assertEqual(parsed["comments"][0]["body_text"], "有用回复")

    def test_empty_comment_state_is_not_part_of_post_body(self):
        payload = ocr_payload(
            [
                ("详情", 380, 60), ("真实作者", 130, 160), ("2天前", 130, 220),
                ("只有正文", 30, 330), ("这里空空如也哦~", 300, 800),
                ("长按评论可赞赏，遇到热心猹友可以给TA一点鼓", 130, 1040),
            ]
        )

        parsed = parse_detail_capture(
            [payload], captured_at=datetime.fromisoformat("2026-07-16T10:00:00+08:00")
        )

        self.assertEqual(parsed["body_text"], "只有正文")
        self.assertEqual(parsed["comments"], [])
        self.assertEqual(parsed["comment_count"], 0)
        self.assertTrue(parsed["capture_complete"])

    def test_detail_time_replaces_stale_feed_time_and_is_not_body_text(self):
        payload = ocr_payload(
            [
                ("详情", 380, 60), ("真实作者", 130, 160), ("51分钟前", 130, 220),
                ("完整正文", 30, 330), ("7收藏", 449, 630), ("V2", 712, 630),
                ("这里空空如也哦~", 300, 800),
                ("长按评论可赞赏，遇到热心猹友可以给TA一点鼓", 130, 1040),
                ("励", 400, 1090),
            ]
        )

        parsed = parse_detail_capture(
            [payload],
            captured_at=datetime.fromisoformat("2026-07-17T10:00:00+08:00"),
            display_time_hint="28分钟前",
        )

        self.assertEqual(parsed["display_time"], "51分钟前")
        self.assertEqual(parsed["body_text"], "完整正文")
        # Vision can read the collection icon as a leading digit (for example
        # "7收藏"). A leading number is not a displayed metric.
        self.assertIsNone(parsed["collect_count"])
        self.assertEqual(parsed["like_count"], 2)
        self.assertEqual(parsed["comment_count"], 0)

    def test_numeric_comment_body_is_not_treated_as_a_metric(self):
        payload = ocr_payload(
            [
                ("详情", 380, 60), ("真实作者", 130, 160), ("2天前", 130, 220),
                ("正文", 30, 330), ("全部评论•1条", 30, 700),
                ("评论者", 130, 780), ("2天前", 130, 840), ("666", 130, 900),
                ("1 ★", 560, 1480),
            ]
        )

        parsed = parse_detail_capture(
            [payload], captured_at=datetime.fromisoformat("2026-07-16T10:00:00+08:00")
        )

        self.assertEqual(parsed["comments"][0]["body_text"], "666")

    def test_relative_time_is_saved_as_range(self):
        captured = datetime.fromisoformat("2026-07-16T10:30:00+08:00")

        start, end = estimate_display_time("2天前", captured)

        self.assertEqual(start, "2026-07-14T00:00:00+08:00")
        self.assertEqual(end, "2026-07-15T00:00:00+08:00")

    def test_window_selection_prefers_largest_matching_wechat_window(self):
        selected = MacOSMiniProgramDriver.select_window(
            [
                {"owner": "微信", "title": "菜单", "width": 200, "height": 300},
                {"owner": "微信", "title": "校园论坛", "width": 414, "height": 780},
                {"owner": "Safari", "title": "微信文档", "width": 1200, "height": 800},
            ],
            r"猹话会|校园论坛",
        )

        self.assertEqual(selected["title"], "校园论坛")
        self.assertIsNone(
            MacOSMiniProgramDriver.select_window(
                [{"owner": "Safari", "title": "微信文档", "width": 1200, "height": 800}],
                r"Safari|微信",
            )
        )
        self.assertIsNone(
            MacOSMiniProgramDriver.select_window(
                [{"owner": "微信", "title": "图片和视频", "width": 825, "height": 908}],
                r"猹话会",
            )
        )

    def test_activation_targets_the_selected_wechat_window_title(self):
        driver = MacOSMiniProgramDriver()
        with patch.object(driver, "_interaction") as interaction, patch("time.sleep"):
            driver.activate({"pid": 1032, "title": "猹话会"})

        interaction.assert_called_once_with("activate", "1032", "猹话会")

    def test_window_geometry_is_refreshed_by_window_id_before_input(self):
        driver = MacOSMiniProgramDriver()
        window = {
            "window_id": 75888,
            "pid": 1032,
            "title": "猹话会",
            "x": 388,
            "y": 317,
            "width": 429,
            "height": 768,
        }
        with patch(
            "services.macos_miniprogram._ensure_native_helper",
            return_value=Path("/tmp/helper"),
        ), patch(
            "services.macos_miniprogram._run_json",
            return_value={
                "windows": [
                    {
                        "window_id": 75888,
                        "pid": 1032,
                        "title": "猹话会",
                        "x": 303,
                        "y": 218,
                        "width": 429,
                        "height": 768,
                    }
                ]
            },
        ):
            refreshed = driver.refresh_window(window)

        self.assertIs(refreshed, window)
        self.assertEqual((window["x"], window["y"]), (303, 218))


class ForumCaptureRepositoryTests(unittest.TestCase):
    def test_each_run_writes_one_incremental_markdown_with_post_separators(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            with patch.object(settings, "data_dir", data_dir), patch.object(
                settings, "obsidian_vault", data_dir / "obsidian"
            ):
                repository = ForumCaptureRepository()
                run = repository.create_run(
                    source_key="campus_forum",
                    mode="incremental",
                    window_pattern="猹话会",
                    options={},
                )
                self.assertTrue(run["content_item_id"])
                initial_state = get_markdown_state(run["content_item_id"])
                self.assertIn("# 微信小程序校园论坛采集", initial_state.markdown)
                with connect() as connection:
                    item = ContentRepository(connection).get_content_item(run["content_item_id"])
                    folder = connection.execute(
                        "SELECT name FROM library_folders WHERE id = ?",
                        (item.library_folder_id,),
                    ).fetchone()
                self.assertEqual(item.source_provider, "wechat_miniprogram")
                self.assertEqual(item.content_type, "forum_capture")
                self.assertEqual(item.source_name, "猹话会")
                self.assertEqual(folder["name"], "微信小程序")
                self.assertFalse(inspect_content_text_readiness(item).can_ask_ai)
                first = {
                    "id": "post-1",
                    "author_label": "匿名甲",
                    "display_time": "2小时前",
                    "body_text": "第一篇正文",
                    "tags": ["#校内求助"],
                    "category": "校园日常",
                    "collect_count": 2,
                    "comment_count": 1,
                    "like_count": 3,
                    "capture_complete": True,
                    "comments": [{"author_label": "评论者", "body_text": "第一条评论"}],
                }
                second = {
                    **first,
                    "id": "post-2",
                    "author_label": "匿名乙",
                    "body_text": "第二篇正文",
                    "comments": [],
                }

                repository.append_run_post(
                    run["id"], first, ordinal=1, captured_at="2026-07-17T08:00:00+08:00"
                )
                repository.append_run_post(
                    run["id"], second, ordinal=2, captured_at="2026-07-17T08:01:00+08:00"
                )
                repository.append_run_post(
                    run["id"], first, ordinal=3, captured_at="2026-07-17T08:02:00+08:00"
                )

                markdown_path = Path(str(run["markdown_path"]))
                document = markdown_path.read_text(encoding="utf-8")
                self.assertIn("采集开始：", document)
                self.assertIn("第一篇正文", document)
                self.assertIn("第一条评论", document)
                self.assertIn("第二篇正文", document)
                self.assertEqual(document.count("<!-- post-id:"), 2)
                self.assertEqual(document.count("\n---\n"), 1)
                tree_document = get_markdown_state(run["content_item_id"]).markdown
                self.assertEqual(tree_document, document)
                self.assertTrue(inspect_content_text_readiness(item).can_ask_ai)
                source = load_content_source_text(run["content_item_id"])
                self.assertEqual(source.source_kind, "forum_capture")
                self.assertIn("第一篇正文", source.text)
                self.assertIn("第二篇正文", source.text)

    def test_historical_run_markdown_is_backfilled_into_the_file_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            with patch.object(settings, "data_dir", data_dir), patch.object(
                settings, "obsidian_vault", data_dir / "obsidian"
            ):
                repository = ForumCaptureRepository()
                run = repository.create_run(
                    source_key="campus_forum",
                    mode="backfill",
                    window_pattern="猹话会",
                    options={},
                )
                repository.append_run_post(
                    run["id"],
                    {
                        "id": "historical-post",
                        "author_label": "匿名用户",
                        "display_time": "昨天",
                        "body_text": "历史采集正文",
                        "comments": [],
                    },
                    ordinal=1,
                    captured_at="2026-07-16T08:00:00+08:00",
                )
                original_content_id = run["content_item_id"]
                with connect() as connection:
                    connection.execute(
                        "DELETE FROM obsidian_sync WHERE content_item_id = ?",
                        (original_content_id,),
                    )
                    connection.execute(
                        "UPDATE miniprogram_capture_runs SET content_item_id = NULL, posts_seen = 1 WHERE id = ?",
                        (run["id"],),
                    )
                    connection.commit()

                self.assertEqual(repository.backfill_run_documents(), 1)
                backfilled = repository.get_run(run["id"])
                self.assertEqual(backfilled["content_item_id"], original_content_id)
                self.assertIn(
                    "历史采集正文",
                    get_markdown_state(original_content_id).markdown,
                )

    def test_post_is_promoted_to_searchable_content_item(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            with patch.object(settings, "data_dir", data_dir):
                initialize_database()
                repository = ForumCaptureRepository()
                parsed = {
                    "fingerprint": "a" * 64,
                    "author_label": "匿名用户",
                    "display_time": "2天前",
                    "estimated_from": "2026-07-14T00:00:00+08:00",
                    "estimated_to": "2026-07-15T00:00:00+08:00",
                    "body_text": "校园停水通知，请提前储水。",
                    "tags": ["#校内求助"],
                    "category": "校园日常",
                    "collect_count": 2,
                    "comment_count": 1,
                    "like_count": 3,
                    "capture_complete": True,
                    "comments": [
                        {
                            "fingerprint": "b" * 64,
                            "author_label": "评论者",
                            "display_time": "1小时前",
                            "body_text": "宿舍群已经确认。",
                            "like_count": 1,
                            "images": [],
                        }
                    ],
                    "raw_ocr_frames": [],
                }

                post, created = repository.upsert_post(
                    source_key="campus_forum",
                    parsed=parsed,
                    detail_frame_path=str(data_dir / "frame.png"),
                )

                self.assertTrue(created)
                self.assertTrue(post["capture_complete"])
                self.assertEqual(post["stored_comment_count"], 1)
                source = load_content_source_text(post["content_item_id"])
                self.assertIn("校园停水通知", source.text)
                self.assertIn("宿舍群已经确认", source.text)
                with connect() as connection:
                    item = connection.execute(
                        "SELECT content_type, source_provider FROM content_items WHERE id = ?",
                        (post["content_item_id"],),
                    ).fetchone()
                self.assertEqual(item["content_type"], "forum_post")
                self.assertEqual(item["source_provider"], "wechat_miniprogram")

    def test_similar_visual_recapture_updates_instead_of_duplicating(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(settings, "data_dir", Path(temporary)):
                initialize_database()
                repository = ForumCaptureRepository()
                base = {
                    "author_label": "・・・", "display_time": "2天前",
                    "estimated_from": None, "estimated_to": None,
                    "body_text": (
                        "真实作者\n出售教材\n北区自提\n联系方式1200720065\n"
                        "教材资料高等数学线性代数\n真实作者\n出售教材\n北区自提"
                    ),
                    "tags": [], "category": "", "collect_count": None,
                    "comment_count": None, "like_count": None,
                    "capture_complete": False, "comments": [],
                }
                first, created = repository.upsert_post(
                    source_key="campus_forum",
                    parsed={**base, "fingerprint": "c" * 64},
                    detail_frame_path="first.png",
                )
                refreshed, refreshed_created = repository.upsert_post(
                    source_key="campus_forum",
                    parsed={
                        **base,
                        "fingerprint": "d" * 64,
                        "author_label": "真实作者",
                        "body_text": "出售教材\n北区自提\n联系方式1200720065\n教材资料高等数学线性代数",
                    },
                    detail_frame_path="second.png",
                )

                self.assertTrue(created)
                self.assertFalse(refreshed_created)
                self.assertEqual(first["id"], refreshed["id"])
                self.assertEqual(
                    refreshed["body_text"],
                    "出售教材\n北区自提\n联系方式1200720065\n教材资料高等数学线性代数",
                )

    def test_incomplete_short_recapture_does_not_erase_fuller_body(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(settings, "data_dir", Path(temporary)):
                initialize_database()
                repository = ForumCaptureRepository()
                common = {
                    "fingerprint": "e" * 64, "author_label": "作者", "display_time": "2天前",
                    "estimated_from": None, "estimated_to": None, "tags": [], "category": "",
                    "collect_count": None, "comment_count": None, "like_count": None,
                    "capture_complete": False, "comments": [],
                }
                full, _ = repository.upsert_post(
                    source_key="campus_forum",
                    parsed={**common, "body_text": "第一段完整正文\n第二段重要正文\n第三段补充正文\n第四段结束正文"},
                    detail_frame_path="full.png",
                )
                refreshed, _ = repository.upsert_post(
                    source_key="campus_forum",
                    parsed={**common, "body_text": "第一段完整正文"},
                    detail_frame_path="short.png",
                )

                self.assertEqual(refreshed["body_text"], full["body_text"])


class ForumCollectorNavigationTests(unittest.TestCase):
    def test_green_feed_top_button_detector_excludes_lower_search_slot(self):
        width, height = 214, 384
        up_x, up_y = int(width * 0.925), int(height * 0.81)
        search_x, search_y = int(width * 0.925), int(height * 0.91)

        def pixel_at(x, y):
            in_up = (x - up_x) ** 2 + (y - up_y) ** 2 <= 13 ** 2
            in_search = (x - search_x) ** 2 + (y - search_y) ** 2 <= 13 ** 2
            return (84, 188, 128) if in_up or in_search else (255, 255, 255)

        position = _find_feed_top_button(width, height, pixel_at)

        self.assertIsNotNone(position)
        self.assertAlmostEqual(position[0], 0.925, delta=0.02)
        self.assertAlmostEqual(position[1], 0.81, delta=0.02)

    def test_absent_top_button_confirms_top_without_wheel_event(self):
        driver = MagicMock()
        collector = MiniProgramForumCollector(driver=driver, repository=MagicMock())
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            settings, "data_dir", Path(temporary)
        ), patch(
            "services.miniprogram_forum_collector.feed_top_button_position",
            return_value=None,
        ):
            reached_top = collector._scroll_feed_to_top({"height": 780}, 1.2)

        self.assertTrue(reached_top)
        driver.click_normalized.assert_not_called()
        driver.scroll.assert_not_called()

    def test_return_to_top_clicks_button_and_never_scrolls_up(self):
        driver = MagicMock()
        collector = MiniProgramForumCollector(driver=driver, repository=MagicMock())
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            settings, "data_dir", Path(temporary)
        ), patch("time.sleep"), patch(
            "services.miniprogram_forum_collector.feed_top_button_position",
            side_effect=[(0.925, 0.81), None],
        ):
            reached_top = collector._scroll_feed_to_top({"height": 780}, 1.2)

        self.assertTrue(reached_top)
        driver.click_normalized.assert_called_once_with({"height": 780}, 0.925, 0.81)
        driver.scroll.assert_not_called()

    def test_persistent_top_button_fails_without_wheel_fallback(self):
        driver = MagicMock()
        collector = MiniProgramForumCollector(driver=driver, repository=MagicMock())
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            settings, "data_dir", Path(temporary)
        ), patch("time.sleep"), patch(
            "services.miniprogram_forum_collector.feed_top_button_position",
            return_value=(0.925, 0.81),
        ):
            reached_top = collector._scroll_feed_to_top({"height": 780}, 1.2)

        self.assertFalse(reached_top)
        self.assertEqual(driver.click_normalized.call_count, 3)
        driver.scroll.assert_not_called()

    def test_feed_recaptures_after_each_post_then_requests_verified_scroll(self):
        driver = MagicMock()
        repository = MagicMock()
        repository.upsert_post.side_effect = [
            ({"id": "post-1", "comments": []}, True),
            ({"id": "post-2", "comments": []}, True),
        ]
        collector = MiniProgramForumCollector(driver=driver, repository=repository)
        candidates = [
            FeedCandidate(
                display_time=f"{index + 1}分钟前",
                author_hint=f"作者{index + 1}",
                card_text=f"作者{index + 1}\n正文{index + 1}",
                signature=f"signature-{index + 1}",
                click_x=300,
                click_y=500 + index * 200,
                top=300,
                bottom=700,
                body_text=f"正文{index + 1}",
                needs_detail=False,
            )
            for index in range(2)
        ]
        feed_ocr = ocr_payload(
            [("本校", 420, 60), ("全部", 30, 220), ("避雷", 140, 220)]
        )
        frames = [
            {"id": f"frame-{index}", "path": Path(f"frame-{index}.png"), "hash": f"{index:016x}", "ocr": feed_ocr}
            for index in range(3)
        ]
        scrolled_frame = {
            "id": "frame-scrolled",
            "path": Path("frame-scrolled.png"),
            "hash": "f" * 16,
            "ocr": feed_ocr,
        }
        counters = {"posts_seen": 0, "posts_created": 0, "comments_captured": 0, "frames_captured": 0}
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            settings, "data_dir", Path(temporary)
        ), patch.object(collector, "_ensure_feed"), patch.object(
            collector, "_scroll_feed_to_top", return_value=True
        ), patch.object(
            collector, "_capture_frame", side_effect=frames
        ) as capture, patch(
            "services.miniprogram_forum_collector.detect_feed_candidates",
            side_effect=[candidates, candidates, []],
        ), patch.object(
            collector, "_scroll_down_verified", return_value=scrolled_frame
        ) as verified_scroll, patch(
            "time.sleep"
        ):
            collector._crawl_feed(
                "run-1",
                {
                    "max_posts": 3,
                    "max_feed_scrolls": 1,
                    "mode": "backfill",
                    "page_wait_seconds": 0.4,
                },
                {"height": 780},
                counters,
            )

        self.assertEqual(capture.call_count, 3)
        self.assertEqual(repository.upsert_post.call_count, 2)
        verified_scroll.assert_called_once()
        self.assertEqual(verified_scroll.call_args.kwargs["page"], "feed")
        self.assertEqual(verified_scroll.call_args.kwargs["scroll_index"], 1)
        driver.scroll.assert_not_called()
        driver.click_pixel.assert_not_called()

    def test_deleted_post_is_marked_processed_without_counting_as_an_error(self):
        driver = MagicMock()
        repository = MagicMock()
        collector = MiniProgramForumCollector(driver=driver, repository=repository)
        candidate = FeedCandidate(
            display_time="2小时前",
            author_hint="信使猹在喝冷饮",
            card_text="信使猹在喝冷饮\n为啥教务系统打不开了",
            signature="deleted-signature",
            click_x=300,
            click_y=1200,
            top=1000,
            bottom=1400,
            body_text="为啥教务系统打不开了",
            needs_detail=True,
        )
        feed_ocr = ocr_payload(
            [("本校", 420, 60), ("全部", 30, 220), ("避雷", 140, 220)]
        )
        frames = [
            {"id": f"frame-{index}", "path": Path(f"frame-{index}.png"), "hash": str(index), "ocr": feed_ocr}
            for index in range(2)
        ]
        counters = {
            "posts_seen": 0,
            "posts_created": 0,
            "comments_captured": 0,
            "frames_captured": 0,
        }
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            settings, "data_dir", Path(temporary)
        ), patch.object(collector, "_ensure_feed"), patch.object(
            collector, "_scroll_feed_to_top", return_value=True
        ), patch.object(
            collector, "_capture_frame", side_effect=frames
        ), patch(
            "services.miniprogram_forum_collector.detect_feed_candidates",
            side_effect=[[candidate], [candidate]],
        ), patch.object(
            collector, "_capture_post_detail", side_effect=DeletedForumPost("deleted")
        ) as capture_detail, patch.object(
            collector, "_scroll_down_verified", return_value=frames[-1]
        ) as verified_scroll, patch("time.sleep"):
            collector._crawl_feed(
                "run-1",
                {
                    "max_posts": 3,
                    "max_feed_scrolls": 1,
                    "mode": "backfill",
                    "page_wait_seconds": 0.4,
                },
                {"height": 780},
                counters,
            )

        capture_detail.assert_called_once()
        verified_scroll.assert_called_once()
        repository.upsert_post.assert_not_called()
        self.assertEqual(counters["posts_seen"], 0)

    def test_failed_post_is_skipped_instead_of_retried_at_same_coordinates(self):
        driver = MagicMock()
        repository = MagicMock()
        collector = MiniProgramForumCollector(driver=driver, repository=repository)
        candidate = FeedCandidate(
            display_time="3小时前",
            author_hint="不",
            card_text="不\n3小时前",
            signature="failed-signature",
            click_x=300,
            click_y=1300,
            top=1100,
            bottom=1400,
            body_text="",
            needs_detail=True,
        )
        feed_ocr = ocr_payload(
            [("本校", 420, 60), ("全部", 30, 220), ("避雷", 140, 220)]
        )
        frames = [
            {"id": f"frame-{index}", "path": Path(f"frame-{index}.png"), "hash": str(index), "ocr": feed_ocr}
            for index in range(2)
        ]
        counters = {
            "posts_seen": 0,
            "posts_created": 0,
            "comments_captured": 0,
            "frames_captured": 0,
        }
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            settings, "data_dir", Path(temporary)
        ), patch.object(collector, "_ensure_feed"), patch.object(
            collector, "_scroll_feed_to_top", return_value=True
        ), patch.object(
            collector, "_capture_frame", side_effect=frames
        ), patch(
            "services.miniprogram_forum_collector.detect_feed_candidates",
            side_effect=[[candidate], [candidate]],
        ), patch.object(
            collector,
            "_capture_post_detail",
            side_effect=MiniProgramDriverError("点击帖子后未识别到详情页"),
        ) as capture_detail, patch.object(
            collector, "_scroll_down_verified", return_value=frames[-1]
        ) as verified_scroll, patch("time.sleep"):
            collector._crawl_feed(
                "run-1",
                {
                    "max_posts": 3,
                    "max_feed_scrolls": 1,
                    "mode": "backfill",
                    "page_wait_seconds": 0.4,
                },
                {"height": 780},
                counters,
            )

        capture_detail.assert_called_once()
        verified_scroll.assert_called_once()
        repository.upsert_post.assert_not_called()
        self.assertEqual(counters["posts_seen"], 0)

    def test_detail_body_enriches_dedupe_identity_after_partial_feed_card(self):
        driver = MagicMock()
        repository = MagicMock()
        repository.upsert_post.return_value = (
            {"id": "post-1", "comments": []},
            True,
        )
        collector = MiniProgramForumCollector(driver=driver, repository=repository)
        partial = FeedCandidate(
            display_time="2小时前",
            author_hint="爱吃车厘子",
            card_text="爱吃车厘子\n2小时前",
            signature="partial-signature",
            click_x=300,
            click_y=1200,
            top=1000,
            bottom=1400,
            body_text="",
            needs_detail=True,
        )
        revealed = replace(
            partial,
            signature="revealed-signature",
            body_text="蹲形策3对分易刷",
            needs_detail=False,
        )
        feed_ocr = ocr_payload(
            [("本校", 420, 60), ("全部", 30, 220), ("避雷", 140, 220)]
        )
        frames = [
            {"id": f"frame-{index}", "path": Path(f"frame-{index}.png"), "hash": str(index), "ocr": feed_ocr}
            for index in range(2)
        ]
        parsed = {
            "author_label": "爱吃车厘子",
            "body_text": "蹲形策3对分易刷",
            "comments": [],
        }
        counters = {
            "posts_seen": 0,
            "posts_created": 0,
            "comments_captured": 0,
            "frames_captured": 0,
        }
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            settings, "data_dir", Path(temporary)
        ), patch.object(collector, "_ensure_feed"), patch.object(
            collector, "_scroll_feed_to_top", return_value=True
        ), patch.object(
            collector, "_capture_frame", side_effect=frames
        ), patch(
            "services.miniprogram_forum_collector.detect_feed_candidates",
            side_effect=[[partial], [revealed]],
        ), patch.object(
            collector,
            "_capture_post_detail",
            return_value=(parsed, ["detail-1"], "detail.png"),
        ) as capture_detail, patch.object(
            collector, "_scroll_down_verified", return_value=frames[-1]
        ), patch("time.sleep"):
            collector._crawl_feed(
                "run-1",
                {
                    "max_posts": 3,
                    "max_feed_scrolls": 1,
                    "mode": "backfill",
                    "page_wait_seconds": 0.4,
                },
                {"height": 780},
                counters,
            )

        capture_detail.assert_called_once()
        repository.upsert_post.assert_called_once()
        self.assertEqual(counters["posts_seen"], 1)

    def test_deleted_detail_returns_to_feed_with_expected_skip_signal(self):
        driver = MagicMock()
        collector = MiniProgramForumCollector(driver=driver, repository=MagicMock())
        candidate = FeedCandidate(
            display_time="2小时前",
            author_hint="信使猹在喝冷饮",
            card_text="信使猹在喝冷饮\n为啥教务系统打不开了",
            signature="deleted-signature",
            click_x=300,
            click_y=1200,
            top=1000,
            bottom=1400,
            body_text="为啥教务系统打不开了",
            needs_detail=True,
        )
        deleted_frame = {
            "id": "detail-deleted",
            "path": Path("detail-deleted.png"),
            "hash": "deleted",
            "ocr": ocr_payload(
                [
                    ("详情", 380, 60),
                    ("哦哦，来晚了，帖子已经被删", 120, 800),
                    ("除", 400, 850),
                    ("这里空空如也哦~", 300, 1050),
                ]
            ),
        }
        counters = {
            "posts_seen": 0,
            "posts_created": 0,
            "comments_captured": 0,
            "frames_captured": 0,
        }
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            settings, "data_dir", Path(temporary)
        ), patch.object(
            collector, "_capture_frame", return_value=deleted_frame
        ), patch.object(
            collector, "_return_to_feed"
        ) as return_to_feed, patch("time.sleep"):
            with self.assertRaises(DeletedForumPost):
                collector._capture_post_detail(
                    "run-1",
                    {"max_detail_scrolls": 10},
                    {"height": 780},
                    candidate,
                    counters,
                    0.4,
                )

        return_to_feed.assert_called_once()

    def test_detail_scroll_stops_only_on_bottom_phrase_and_uses_verified_scroll(self):
        driver = MagicMock()
        collector = MiniProgramForumCollector(driver=driver, repository=MagicMock())
        candidate = FeedCandidate(
            display_time="2天前",
            author_hint="真实作者",
            card_text="真实作者\n求助正文…",
            signature="candidate",
            click_x=300,
            click_y=500,
            top=300,
            bottom=700,
            body_text="求助正文…",
            truncated=True,
            needs_detail=True,
        )

        def frame(identifier, lines):
            return {
                "id": identifier,
                "path": Path(f"{identifier}.png"),
                "hash": identifier,
                "ocr": ocr_payload(lines),
            }

        first = frame(
            "detail-1",
            [("详情", 380, 60), ("真实作者", 130, 160), ("2天前", 130, 220),
             ("求助正文完整内容", 30, 330), ("推荐", 50, 750), ("最新", 150, 750)],
        )
        after_latest = frame(
            "detail-2",
            [("详情", 380, 60), ("真实作者", 130, 160), ("2天前", 130, 220),
             ("求助正文完整内容", 30, 330), ("全部评论•0条", 30, 860)],
        )
        bottom = frame(
            "detail-3",
            [("详情", 380, 60), ("全部评论•0条", 30, 860),
             ("这里空空如也哦~", 300, 1050),
             ("长按评论可赞赏，遇到热心猹友可以给TA一点鼓", 100, 1300), ("励", 400, 1350)],
        )
        counters = {"posts_seen": 0, "posts_created": 0, "comments_captured": 0, "frames_captured": 0}
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            settings, "data_dir", Path(temporary)
        ), patch.object(
            collector, "_capture_frame", side_effect=[first, after_latest]
        ), patch.object(
            collector, "_scroll_down_verified", return_value=bottom
        ) as verified_scroll, patch.object(
            collector, "_return_to_feed"
        ), patch("time.sleep"):
            parsed, frame_ids, _ = collector._capture_post_detail(
                "run-1",
                {"max_detail_scrolls": 10},
                {"height": 780},
                candidate,
                counters,
                0.4,
            )

        self.assertTrue(parsed["capture_complete"])
        self.assertEqual(frame_ids, ["detail-1", "detail-2", "detail-3"])
        verified_scroll.assert_called_once()
        self.assertEqual(verified_scroll.call_args.kwargs["page"], "detail")
        driver.scroll.assert_not_called()

    @staticmethod
    def _scroll_frame(identifier: str, offset: int) -> dict:
        return {
            "id": identifier,
            "path": Path(f"{identifier}.png"),
            "hash": identifier,
            "ocr": ocr_payload(
                [
                    ("本校", 420, 60),
                    ("全部", 30, 220),
                    ("避雷", 140, 220),
                    ("匿名用户甲", 130, 900 + offset),
                    ("宿舍搬迁求助正文", 45, 1000 + offset),
                ]
            ),
        }

    def test_verified_scroll_uses_small_wheel_ticks_and_accepts_measured_movement(self):
        driver = MagicMock()
        collector = MiniProgramForumCollector(driver=driver, repository=MagicMock())
        before = self._scroll_frame("before", 0)
        after = self._scroll_frame("after", -96)
        counters = {
            "posts_seen": 0,
            "posts_created": 0,
            "comments_captured": 0,
            "frames_captured": 0,
        }
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            settings, "data_dir", Path(temporary)
        ), patch.object(
            collector, "_capture_frame", return_value=after
        ), patch("time.sleep"):
            result = collector._scroll_down_verified(
                "run-1",
                {"height": 780},
                counters,
                0.4,
                page="feed",
                before=before,
                scroll_index=1,
            )

        self.assertIs(result, after)
        driver.scroll.assert_called_once_with({"height": 780}, 4)

    def test_verified_scroll_retries_more_wheel_ticks_when_page_does_not_move(self):
        driver = MagicMock()
        collector = MiniProgramForumCollector(driver=driver, repository=MagicMock())
        before = self._scroll_frame("before", 0)
        counters = {
            "posts_seen": 0,
            "posts_created": 0,
            "comments_captured": 0,
            "frames_captured": 0,
        }
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            settings, "data_dir", Path(temporary)
        ), patch.object(
            collector, "_capture_frame", return_value=before
        ), patch("time.sleep"):
            with self.assertRaisesRegex(MiniProgramDriverError, "未产生有效向下位移"):
                collector._scroll_down_verified(
                    "run-1",
                    {"height": 780},
                    counters,
                    0.4,
                    page="feed",
                    before=before,
                    scroll_index=1,
                )

        self.assertEqual(
            [call.args[1] for call in driver.scroll.call_args_list],
            [4, 5, 6],
        )

    def test_verified_scroll_stops_immediately_on_reverse_movement(self):
        driver = MagicMock()
        collector = MiniProgramForumCollector(driver=driver, repository=MagicMock())
        before = self._scroll_frame("before", 0)
        reversed_frame = self._scroll_frame("reversed", 80)
        counters = {
            "posts_seen": 0,
            "posts_created": 0,
            "comments_captured": 0,
            "frames_captured": 0,
        }
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            settings, "data_dir", Path(temporary)
        ), patch.object(
            collector, "_capture_frame", return_value=reversed_frame
        ), patch("time.sleep"):
            with self.assertRaisesRegex(MiniProgramDriverError, "反向位移"):
                collector._scroll_down_verified(
                    "run-1",
                    {"height": 780},
                    counters,
                    0.4,
                    page="feed",
                    before=before,
                    scroll_index=1,
                )

        driver.scroll.assert_called_once_with({"height": 780}, 4)

    def test_detail_verified_scroll_uses_smaller_detail_profile(self):
        driver = MagicMock()
        collector = MiniProgramForumCollector(driver=driver, repository=MagicMock())
        before = self._scroll_frame("before", 0)
        after = self._scroll_frame("after", -120)
        counters = {
            "posts_seen": 0,
            "posts_created": 0,
            "comments_captured": 0,
            "frames_captured": 0,
        }
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            settings, "data_dir", Path(temporary)
        ), patch.object(
            collector, "_capture_expected_page_frame", return_value=after
        ), patch("time.sleep"):
            collector._scroll_down_verified(
                "run-1",
                {"height": 780},
                counters,
                0.4,
                page="detail",
                before=before,
                scroll_index=1,
            )

        driver.scroll.assert_called_once_with({"height": 780}, 3)

    def test_expected_page_capture_retries_a_blank_transient_frame(self):
        driver = MagicMock()
        collector = MiniProgramForumCollector(driver=driver, repository=MagicMock())
        blank = {
            "id": "blank",
            "path": Path("blank.png"),
            "hash": "blank",
            "ocr": ocr_payload([]),
        }
        valid = self._scroll_frame("valid", 0)
        counters = {
            "posts_seen": 0,
            "posts_created": 0,
            "comments_captured": 0,
            "frames_captured": 0,
        }
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            settings, "data_dir", Path(temporary)
        ), patch.object(
            collector, "_capture_frame", side_effect=[blank, valid]
        ) as capture, patch("time.sleep"):
            result = collector._capture_expected_page_frame(
                "run-1",
                {"height": 780},
                "feed",
                counters,
                0.4,
                page="feed",
            )

        self.assertIs(result, valid)
        self.assertEqual(capture.call_count, 2)

    def test_return_to_feed_waits_through_a_blank_transition_frame(self):
        driver = MagicMock()
        collector = MiniProgramForumCollector(driver=driver, repository=MagicMock())
        driver.recognize.side_effect = [
            ocr_payload([]),
            self._scroll_frame("valid", 0)["ocr"],
        ]

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            settings, "data_dir", Path(temporary)
        ), patch("time.sleep"):
            collector._return_to_feed(
                {"height": 780},
                0.4,
                run_id="run-1",
            )

        driver.click_normalized.assert_called_once_with(
            {"height": 780}, 0.065, 0.055
        )
        self.assertEqual(driver.capture_window.call_count, 2)
        driver.escape.assert_not_called()

    def test_return_to_feed_retries_back_when_detail_page_persists(self):
        driver = MagicMock()
        collector = MiniProgramForumCollector(driver=driver, repository=MagicMock())
        detail = ocr_payload([("详情", 380, 60), ("帖子正文", 45, 500)])
        valid = self._scroll_frame("valid", 0)["ocr"]
        driver.recognize.side_effect = [detail, detail, valid]

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            settings, "data_dir", Path(temporary)
        ), patch("time.sleep"):
            collector._return_to_feed(
                {"height": 780},
                0.4,
                run_id="run-1",
            )

        self.assertEqual(driver.click_normalized.call_count, 2)
        self.assertEqual(driver.capture_window.call_count, 3)
        driver.escape.assert_not_called()


class ForumCaptureSchedulerTests(unittest.TestCase):
    def test_release_gate_prevents_scheduler_activity(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            settings, "data_dir", Path(temporary)
        ), patch.object(settings, "miniprogram_forum_capture_enabled", False):
            update_miniprogram_forum_settings({"enabled": True, "interval_minutes": 60})
            scheduler = MiniProgramForumScheduler()
            with patch.object(miniprogram_forum_collector, "permission_status") as permission_status:
                self.assertFalse(scheduler.run_once())

            permission_status.assert_not_called()

    def test_settings_are_local_and_validated(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(settings, "data_dir", Path(temporary)):
            updated = update_miniprogram_forum_settings({"enabled": True, "interval_minutes": 60})

            self.assertTrue(updated["enabled"])
            self.assertEqual(load_miniprogram_forum_settings()["interval_minutes"], 60)
            with self.assertRaises(ValueError):
                update_miniprogram_forum_settings({"interval_minutes": 7})
            migrated = update_miniprogram_forum_settings({"window_pattern": "微信|WeChat"})
            self.assertEqual(migrated["window_pattern"], "猹话会")

    def test_scheduler_starts_only_after_user_is_idle(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(settings, "data_dir", Path(temporary)):
            update_miniprogram_forum_settings({"enabled": True, "interval_minutes": 60})
            scheduler = MiniProgramForumScheduler()
            with (
                patch.object(settings, "miniprogram_forum_capture_enabled", True),
                patch.object(miniprogram_forum_collector, "is_active", return_value=False),
                patch.object(
                    miniprogram_forum_collector,
                    "permission_status",
                    return_value={
                        "selected_window": {"window_id": 1},
                        "accessibility_granted": True,
                        "screen_capture_granted": True,
                        "user_idle_seconds": 300,
                    },
                ),
                patch.object(miniprogram_forum_collector, "start", return_value={"id": "run"}) as start,
            ):
                started = scheduler.run_once()

            self.assertTrue(started)
            start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
