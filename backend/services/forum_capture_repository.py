from __future__ import annotations

from datetime import datetime
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
from typing import Any

from config import settings
from services.content_index import ensure_default_provider_folder
from services.database import connect, initialize_database, utc_now_iso
from services.markdown_sync import save_markdown_draft_and_sync
from services.obsidian_settings import content_library_root, default_content_library_root
from services.repository import ContentRepository, new_id
from services.search_index import upsert_source_text_document


FORUM_CAPTURE_CONTENT_TYPE = "forum_capture"


def repair_forum_capture_document_types() -> int:
    """Detach historical capture batches from the generated-report reader."""
    initialize_database()
    with connect() as connection:
        cursor = connection.execute(
            """UPDATE content_items
               SET content_type=?, updated_at=?
               WHERE source_provider='wechat_miniprogram'
                 AND content_type='report'
                 AND canonical_source_id LIKE 'forum-capture-run:%'""",
            (FORUM_CAPTURE_CONTENT_TYPE, utc_now_iso()),
        )
        connection.commit()
    return max(0, int(cursor.rowcount or 0))


class ForumCaptureRepository:
    def create_run(
        self,
        *,
        source_key: str,
        mode: str,
        window_pattern: str,
        options: dict[str, Any],
    ) -> dict[str, Any]:
        initialize_database()
        now = utc_now_iso()
        run_id = new_id()
        with connect() as connection:
            connection.execute(
                """
                INSERT INTO miniprogram_capture_runs (
                    id, source_key, status, mode, window_pattern, current_stage,
                    options_json, checkpoint_json, started_at, updated_at
                ) VALUES (?, ?, 'running', ?, ?, 'preparing', ?, '{}', ?, ?)
                """,
                (run_id, source_key, mode, window_pattern, _json(options), now, now),
            )
            connection.commit()
        try:
            self.initialize_run_markdown(
                run_id,
                source_key=source_key,
                mode=mode,
                started_at=now,
            )
            self.ensure_run_document(run_id)
        except Exception as exc:
            self.update_run(
                run_id,
                status="failed",
                current_stage="failed",
                last_error=f"无法创建文件树采集文档：{str(exc)[:300]}",
                finished_at=utc_now_iso(),
            )
            raise
        return self.get_run(run_id)

    def initialize_run_markdown(
        self,
        run_id: str,
        *,
        source_key: str,
        mode: str,
        started_at: str,
    ) -> Path:
        path = _run_markdown_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            mode_label = "增量采集" if mode == "incremental" else "完整采集"
            path.write_text(
                "\n".join(
                    [
                        "# 微信小程序校园论坛采集",
                        "",
                        f"采集开始：{_display_timestamp(started_at)}",
                        f"采集模式：{mode_label}",
                        f"内容源：{source_key}",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        return path

    def append_run_post(
        self,
        run_id: str,
        post: dict[str, Any],
        *,
        ordinal: int,
        captured_at: str,
    ) -> Path:
        path = _run_markdown_path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            run = self.get_run(run_id)
            self.initialize_run_markdown(
                run_id,
                source_key=str(run.get("source_key") or "campus_forum"),
                mode=str(run.get("mode") or "incremental"),
                started_at=str(run.get("started_at") or captured_at),
            )
        marker = f"<!-- post-id:{post.get('id', '')} -->"
        existing = path.read_text(encoding="utf-8")
        if marker in existing:
            self.sync_run_document(run_id)
            return path
        separator = "\n---\n\n" if "<!-- post-id:" in existing else "\n"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(separator)
            handle.write(_run_post_markdown(post, ordinal=ordinal, captured_at=captured_at))
        self.sync_run_document(run_id)
        return path

    def ensure_run_document(self, run_id: str) -> str:
        """Create or reconnect the file-tree document representing one capture run."""
        run = self.get_run(run_id)
        content_item_id = str(run.get("content_item_id") or "")
        if not content_item_id:
            canonical_id = f"forum-capture-run:{run_id}"
            title = _run_document_title(str(run.get("started_at") or ""))
            with connect() as connection:
                repository = ContentRepository(connection)
                item = repository.find_by_canonical_id(
                    source_provider="wechat_miniprogram",
                    canonical_source_id=canonical_id,
                )
                if item is None:
                    folder_id = ensure_default_provider_folder(connection, "wechat_miniprogram")
                    item = repository.create_content_item(
                        source_provider="wechat_miniprogram",
                        content_type=FORUM_CAPTURE_CONTENT_TYPE,
                        canonical_source_id=canonical_id,
                        title=title,
                        status="to_read",
                        library_folder_id=folder_id,
                        published_at=str(run.get("started_at") or "") or None,
                        source_name="猹话会",
                        source_section="采集记录",
                    )
                elif item.content_type != FORUM_CAPTURE_CONTENT_TYPE:
                    connection.execute(
                        "UPDATE content_items SET content_type=?, updated_at=? WHERE id=?",
                        (FORUM_CAPTURE_CONTENT_TYPE, utc_now_iso(), item.id),
                    )
                content_item_id = item.id
                connection.execute(
                    "UPDATE miniprogram_capture_runs SET content_item_id = ?, updated_at = ? WHERE id = ?",
                    (content_item_id, utc_now_iso(), run_id),
                )
                connection.commit()
        self.sync_run_document(run_id)
        return content_item_id

    def sync_run_document(self, run_id: str) -> None:
        """Publish the current run Markdown to the app document and search index."""
        path = _run_markdown_path(run_id)
        if not path.exists():
            raise FileNotFoundError(f"采集文档不存在：{path}")
        with connect() as connection:
            row = connection.execute(
                """
                SELECT run.content_item_id, run.started_at, item.title, document.markdown_path
                FROM miniprogram_capture_runs AS run
                JOIN content_items AS item ON item.id = run.content_item_id
                LEFT JOIN content_documents AS document ON document.content_item_id = item.id
                WHERE run.id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                raise LookupError(f"采集任务尚未关联文件树文档：{run_id}")
            connection.execute(
                "UPDATE content_items SET updated_at = ? WHERE id = ?",
                (utc_now_iso(), row["content_item_id"]),
            )
            connection.commit()
        markdown = _compose_run_document(
            path.read_text(encoding="utf-8"),
            _read_markdown_file(row["markdown_path"]),
        )
        title = str(row["title"] or _run_document_title(str(row["started_at"] or "")))
        save_markdown_draft_and_sync(
            markdown=markdown,
            title=title,
            obsidian_path=(
                settings.obsidian_vault
                / "微信小程序"
                / _run_document_filename(str(row["started_at"] or ""), run_id)
            ),
            content_item_id=str(row["content_item_id"]),
        )
        upsert_source_text_document(
            content_key=str(row["content_item_id"]),
            title=title,
            transcript=markdown,
        )

    def replace_run_summary_and_sync(self, content_item_id: str, summary: str):
        """Write an AI summary into the app-owned, incrementally synced run document.

        Capture runs intentionally use one file as both canonical library file
        and external-library file.  They are continuously updated by the
        collector, so treating a changed hash as a user-edit conflict would
        incorrectly block summary generation.  Rebuild from the durable run
        source, preserve Q&A, and replace only the generated summary section.
        """
        initialize_database()
        with connect() as connection:
            row = connection.execute(
                """
                SELECT run.id, run.started_at, item.title, document.markdown_path
                FROM miniprogram_capture_runs AS run
                JOIN content_items AS item ON item.id = run.content_item_id
                LEFT JOIN content_documents AS document ON document.content_item_id = item.id
                WHERE run.content_item_id = ?
                ORDER BY run.started_at DESC
                LIMIT 1
                """,
                (content_item_id,),
            ).fetchone()
        if row is None:
            raise LookupError("未找到对应的小程序采集任务")
        source_path = _run_markdown_path(str(row["id"]))
        if not source_path.is_file():
            raise FileNotFoundError("小程序采集原文不存在")
        markdown = _compose_run_document(
            source_path.read_text(encoding="utf-8"),
            _read_markdown_file(row["markdown_path"]),
            summary_override=summary,
        )
        title = str(row["title"] or _run_document_title(str(row["started_at"] or "")))
        state = save_markdown_draft_and_sync(
            markdown=markdown,
            title=title,
            obsidian_path=(
                settings.obsidian_vault
                / "微信小程序"
                / _run_document_filename(str(row["started_at"] or ""), str(row["id"]))
            ),
            content_item_id=content_item_id,
        )
        upsert_source_text_document(content_key=content_item_id, title=title, transcript=markdown)
        return state

    def backfill_run_documents(self) -> int:
        """Promote readable historical captures that predate file-tree documents."""
        initialize_database()
        with connect() as connection:
            rows = connection.execute(
                """
                SELECT run.id
                FROM miniprogram_capture_runs AS run
                LEFT JOIN obsidian_sync AS sync ON sync.content_item_id = run.content_item_id
                WHERE run.posts_seen > 0
                  AND (run.content_item_id IS NULL OR sync.id IS NULL)
                ORDER BY run.started_at
                """
            ).fetchall()
        promoted = 0
        for row in rows:
            run_id = str(row["id"])
            path = _run_markdown_path(run_id)
            if not path.exists() or "<!-- post-id:" not in path.read_text(encoding="utf-8"):
                continue
            self.ensure_run_document(run_id)
            promoted += 1
        return promoted

    def consolidate_posts_into_run_documents(self) -> int:
        """Hide per-post implementation records and remove their Markdown copies.

        The post rows remain intact for dedupe, comments and screenshot evidence.
        A capture run's incrementally synced Markdown is the only document that
        appears in the library, search index and AI workspace.
        """
        initialize_database()
        with connect() as connection:
            rows = connection.execute(
                """
                SELECT post.id AS post_id, post.content_item_id,
                       document.markdown_path, sync.obsidian_path, asset.path AS source_path
                FROM forum_posts AS post
                LEFT JOIN content_documents AS document
                  ON document.content_item_id = post.content_item_id
                LEFT JOIN obsidian_sync AS sync
                  ON sync.content_item_id = post.content_item_id
                LEFT JOIN text_assets AS asset
                  ON asset.content_item_id = post.content_item_id
                 AND asset.asset_type = 'source_text'
                 AND asset.source = 'visual_capture'
                WHERE 1 = 1
                """
            ).fetchall()
            if not rows:
                return 0

            content_ids = [str(row["content_item_id"]) for row in rows]
            placeholders = ",".join("?" for _ in content_ids)
            v2_chunk_rows = connection.execute(
                f"SELECT id FROM knowledge_v2_chunks WHERE content_item_id IN ({placeholders})",
                content_ids,
            ).fetchall()
            if v2_chunk_rows:
                connection.executemany(
                    "DELETE FROM knowledge_v2_search WHERE chunk_id = ?",
                    [(str(row["id"]),) for row in v2_chunk_rows],
                )
            connection.execute(
                f"DELETE FROM knowledge_v2_chunks WHERE content_item_id IN ({placeholders})",
                content_ids,
            )
            connection.execute(
                f"DELETE FROM content_search WHERE content_item_id IN ({placeholders})",
                content_ids,
            )
            connection.execute(
                f"DELETE FROM text_assets WHERE content_item_id IN ({placeholders}) AND source = 'visual_capture'",
                content_ids,
            )
            connection.execute(
                f"DELETE FROM content_documents WHERE content_item_id IN ({placeholders})",
                content_ids,
            )
            connection.execute(
                f"DELETE FROM obsidian_sync WHERE content_item_id IN ({placeholders})",
                content_ids,
            )
            connection.execute(
                f"UPDATE content_items SET library_visible = 0, library_folder_id = NULL, updated_at = ? WHERE id IN ({placeholders})",
                (utc_now_iso(), *content_ids),
            )
            connection.commit()

        for row in rows:
            self._remove_managed_document(row["markdown_path"])
            self._remove_managed_document(row["obsidian_path"])
            source_path = Path(str(row["source_path"] or ""))
            if source_path.is_file() and _is_under(source_path, settings.data_dir / "miniprogram_forum" / "posts"):
                source_path.unlink(missing_ok=True)
        return len(rows)

    def update_run(self, run_id: str, **values: Any) -> dict[str, Any]:
        allowed = {
            "status", "current_stage", "posts_seen", "posts_created",
            "comments_captured", "frames_captured", "checkpoint_json",
            "last_error", "finished_at",
        }
        assignments = []
        parameters = []
        for key, value in values.items():
            if key not in allowed:
                continue
            if key == "checkpoint_json" and not isinstance(value, str):
                value = _json(value)
            assignments.append(f"{key} = ?")
            parameters.append(value)
        if not assignments:
            return self.get_run(run_id)
        assignments.append("updated_at = ?")
        parameters.extend((utc_now_iso(), run_id))
        initialize_database()
        with connect() as connection:
            connection.execute(
                f"UPDATE miniprogram_capture_runs SET {', '.join(assignments)} WHERE id = ?",
                parameters,
            )
            connection.commit()
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        initialize_database()
        with connect() as connection:
            row = connection.execute(
                "SELECT * FROM miniprogram_capture_runs WHERE id = ?", (run_id,)
            ).fetchone()
        if not row:
            raise LookupError(f"采集任务不存在：{run_id}")
        return _run_dict(dict(row))

    def latest_run(self) -> dict[str, Any] | None:
        initialize_database()
        with connect() as connection:
            row = connection.execute(
                "SELECT * FROM miniprogram_capture_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        return _run_dict(dict(row)) if row else None

    def list_runs(self, *, limit: int = 20) -> list[dict[str, Any]]:
        initialize_database()
        with connect() as connection:
            rows = connection.execute(
                "SELECT * FROM miniprogram_capture_runs ORDER BY started_at DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [_run_dict(dict(row)) for row in rows]

    def save_frame(
        self,
        *,
        run_id: str,
        frame_kind: str,
        sequence: int,
        image_path: str,
        image_hash: str,
        ocr: dict[str, Any],
        post_id: str | None = None,
    ) -> str:
        initialize_database()
        frame_id = new_id()
        with connect() as connection:
            connection.execute(
                """
                INSERT INTO miniprogram_capture_frames (
                    id, run_id, post_id, frame_kind, sequence, image_path,
                    image_hash, ocr_json, captured_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    frame_id, run_id, post_id, frame_kind, sequence, image_path,
                    image_hash, _json(ocr), utc_now_iso(),
                ),
            )
            connection.commit()
        return frame_id

    def attach_frames(self, frame_ids: list[str], post_id: str) -> None:
        if not frame_ids:
            return
        placeholders = ",".join("?" for _ in frame_ids)
        initialize_database()
        with connect() as connection:
            connection.execute(
                f"UPDATE miniprogram_capture_frames SET post_id = ? WHERE id IN ({placeholders})",
                (post_id, *frame_ids),
            )
            connection.commit()

    def upsert_post(
        self,
        *,
        source_key: str,
        parsed: dict[str, Any],
        detail_frame_path: str,
    ) -> tuple[dict[str, Any], bool]:
        initialize_database()
        now = utc_now_iso()
        fingerprint = str(parsed.get("fingerprint") or "").strip()
        if not fingerprint:
            raise ValueError("帖子缺少稳定指纹")
        title = _post_title(parsed)
        source_url = f"wechat-mini://{source_key}/{fingerprint}"
        compact_raw = {key: value for key, value in parsed.items() if key != "raw_ocr_frames"}
        created = False
        with connect() as connection:
            existing = connection.execute(
                "SELECT * FROM forum_posts WHERE source_key = ? AND fingerprint = ?",
                (source_key, fingerprint),
            ).fetchone()
            if not existing:
                existing = _find_similar_visual_post(connection, source_key, parsed)
            if existing:
                post_id = str(existing["id"])
                content_item_id = str(existing["content_item_id"])
                preferred_body = _preferred_body(existing["body_text"], parsed.get("body_text"))
                compact_raw["body_text"] = preferred_body
                title = _post_title(compact_raw)
                connection.execute(
                    """
                    UPDATE forum_posts
                    SET author_label = COALESCE(NULLIF(?, ''), author_label),
                        display_time = COALESCE(NULLIF(?, ''), display_time),
                        estimated_from = COALESCE(?, estimated_from),
                        estimated_to = COALESCE(?, estimated_to),
                        body_text = CASE WHEN LENGTH(TRIM(?)) > 0 THEN ? ELSE body_text END,
                        tags_json = ?, category = COALESCE(NULLIF(?, ''), category),
                        collect_count = COALESCE(?, collect_count),
                        comment_count = COALESCE(?, comment_count),
                        like_count = COALESCE(?, like_count),
                        capture_complete = MAX(capture_complete, ?),
                        detail_frame_path = COALESCE(NULLIF(?, ''), detail_frame_path),
                        raw_json = ?, last_seen_at = ?
                    WHERE id = ?
                    """,
                    (
                        parsed.get("author_label", ""), parsed.get("display_time", ""),
                        parsed.get("estimated_from"), parsed.get("estimated_to"),
                        preferred_body, preferred_body,
                        _json(parsed.get("tags", [])), parsed.get("category", ""),
                        parsed.get("collect_count"), parsed.get("comment_count"), parsed.get("like_count"),
                        int(bool(parsed.get("capture_complete"))), detail_frame_path,
                        _json(compact_raw), now, post_id,
                    ),
                )
                connection.execute(
                    """
                    UPDATE content_items
                    SET title = ?, published_at = COALESCE(?, published_at),
                        source_name = ?, status = 'to_read', library_visible = 0,
                        library_folder_id = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (title, parsed.get("estimated_to"), "校园论坛", now, content_item_id),
                )
            else:
                item = ContentRepository(connection).create_content_item(
                    source_provider="wechat_miniprogram",
                    source_url=source_url,
                    canonical_source_id=fingerprint,
                    title=title,
                    content_type="forum_post",
                    status="to_read",
                    library_visible=False,
                    published_at=parsed.get("estimated_to"),
                    source_name="校园论坛",
                    source_section=parsed.get("category") or "",
                )
                content_item_id = item.id
                post_id = new_id()
                connection.execute(
                    """
                    INSERT INTO forum_posts (
                        id, content_item_id, source_key, fingerprint, author_label,
                        display_time, estimated_from, estimated_to, body_text,
                        tags_json, category, collect_count, comment_count, like_count,
                        capture_complete, detail_frame_path, raw_json,
                        first_seen_at, last_seen_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        post_id, content_item_id, source_key, fingerprint,
                        parsed.get("author_label", ""), parsed.get("display_time", ""),
                        parsed.get("estimated_from"), parsed.get("estimated_to"), parsed.get("body_text", ""),
                        _json(parsed.get("tags", [])), parsed.get("category", ""),
                        parsed.get("collect_count"), parsed.get("comment_count"), parsed.get("like_count"),
                        int(bool(parsed.get("capture_complete"))), detail_frame_path,
                        _json(compact_raw), now, now,
                    ),
                )
                created = True

            if parsed.get("capture_complete"):
                connection.execute("DELETE FROM forum_comments WHERE post_id = ?", (post_id,))
            for comment in parsed.get("comments", []):
                self._upsert_comment(connection, post_id, comment, now)
            connection.execute(
                """
                INSERT INTO forum_metric_snapshots (
                    id, post_id, collect_count, comment_count, like_count, captured_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    new_id(), post_id, parsed.get("collect_count"),
                    parsed.get("comment_count"), parsed.get("like_count"), now,
                ),
            )
            connection.commit()

        self._write_post_capture_evidence(post_id, compact_raw)
        return self.get_post(post_id), created

    @staticmethod
    def _remove_managed_document(value: Any) -> None:
        if not value:
            return
        path = Path(str(value)).expanduser()
        roots = (content_library_root(), default_content_library_root())
        if path.is_file() and any(_is_under(path, root) for root in roots):
            path.unlink(missing_ok=True)

    def get_post(self, post_id: str) -> dict[str, Any]:
        initialize_database()
        with connect() as connection:
            row = connection.execute("SELECT * FROM forum_posts WHERE id = ?", (post_id,)).fetchone()
            if not row:
                raise LookupError(f"论坛帖子不存在：{post_id}")
            comments = connection.execute(
                "SELECT * FROM forum_comments WHERE post_id = ? ORDER BY first_seen_at, id", (post_id,)
            ).fetchall()
        return _post_dict(dict(row), [dict(item) for item in comments])

    def list_posts(self, *, source_key: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        initialize_database()
        where = "WHERE post.source_key = ?" if source_key else ""
        parameters: list[Any] = [source_key] if source_key else []
        parameters.append(max(1, min(limit, 500)))
        with connect() as connection:
            rows = connection.execute(
                f"""
                SELECT post.*, COUNT(comment.id) AS stored_comment_count
                FROM forum_posts post
                LEFT JOIN forum_comments comment ON comment.post_id = post.id
                {where}
                GROUP BY post.id
                ORDER BY post.last_seen_at DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [_post_dict(dict(row), None) for row in rows]

    @staticmethod
    def _upsert_comment(connection, post_id: str, comment: dict[str, Any], now: str) -> None:
        fingerprint = str(comment.get("fingerprint") or "").strip()
        if not fingerprint:
            return
        existing = connection.execute(
            "SELECT id FROM forum_comments WHERE post_id = ? AND fingerprint = ?",
            (post_id, fingerprint),
        ).fetchone()
        if existing:
            connection.execute(
                """
                UPDATE forum_comments
                SET body_text = CASE WHEN LENGTH(?) >= LENGTH(body_text) THEN ? ELSE body_text END,
                    like_count = COALESCE(?, like_count), raw_json = ?, last_seen_at = ?
                WHERE id = ?
                """,
                (
                    comment.get("body_text", ""), comment.get("body_text", ""),
                    comment.get("like_count"), _json(comment), now, existing["id"],
                ),
            )
            return
        connection.execute(
            """
            INSERT INTO forum_comments (
                id, post_id, fingerprint, author_label, display_time, body_text,
                like_count, images_json, raw_json, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id(), post_id, fingerprint, comment.get("author_label", ""),
                comment.get("display_time", ""), comment.get("body_text", ""),
                comment.get("like_count"), _json(comment.get("images", [])),
                _json(comment), now, now,
            ),
        )

    @staticmethod
    def _write_post_capture_evidence(post_id: str, parsed: dict[str, Any]) -> Path:
        """Keep structured capture evidence without creating one Markdown per post."""
        post_dir = settings.data_dir / "miniprogram_forum" / "posts" / post_id
        post_dir.mkdir(parents=True, exist_ok=True)
        json_path = post_dir / "capture.json"
        json_path.write_text(_json(parsed), encoding="utf-8")
        return json_path


def _run_dict(value: dict[str, Any]) -> dict[str, Any]:
    value["options"] = _loads(value.pop("options_json", "{}"), {})
    value["checkpoint"] = _loads(value.pop("checkpoint_json", "{}"), {})
    markdown_path = _run_markdown_path(str(value.get("id") or ""))
    value["markdown_path"] = str(markdown_path) if markdown_path.exists() else None
    return value


def _post_dict(value: dict[str, Any], comments: list[dict[str, Any]] | None) -> dict[str, Any]:
    value["tags"] = _loads(value.pop("tags_json", "[]"), [])
    value["raw"] = _loads(value.pop("raw_json", "{}"), {})
    value["capture_complete"] = bool(value.get("capture_complete"))
    if comments is not None:
        for comment in comments:
            comment["images"] = _loads(comment.pop("images_json", "[]"), [])
            comment["raw"] = _loads(comment.pop("raw_json", "{}"), {})
        value["comments"] = comments
        value["stored_comment_count"] = len(comments)
    return value


def _post_title(parsed: dict[str, Any]) -> str:
    body = " ".join(str(parsed.get("body_text") or "").split())
    if body:
        return body[:80]
    tags = parsed.get("tags") or []
    if tags:
        return " ".join(str(value) for value in tags)[:80]
    return f"校园论坛 · {parsed.get('author_label') or parsed.get('display_time') or '未命名帖子'}"


def _find_similar_visual_post(connection, source_key: str, parsed: dict[str, Any]):
    display_time = str(parsed.get("display_time") or "").strip()
    if not display_time:
        return None
    candidates = connection.execute(
        """
        SELECT * FROM forum_posts
        WHERE source_key = ? AND display_time = ?
        ORDER BY last_seen_at DESC
        LIMIT 40
        """,
        (source_key, display_time),
    ).fetchall()
    incoming = _visual_identity_text(parsed.get("author_label"), parsed.get("body_text"))
    if len(incoming) < 12:
        return None
    for candidate in candidates:
        stored = _visual_identity_text(candidate["author_label"], candidate["body_text"])
        if len(stored) < 12:
            continue
        common_length = min(130, len(incoming), len(stored))
        if common_length >= 32 and SequenceMatcher(
            None, incoming[:common_length], stored[:common_length]
        ).ratio() >= 0.95:
            return candidate
    return None


def _visual_identity_text(author: Any, body: Any) -> str:
    author_text = str(author or "").strip()
    if author_text in {"签到", "关注", "高校圈", "本校", "十大"}:
        author_text = ""
    value = f"{author_text}\n{body or ''}".lower()
    return re.sub(r"[^0-9a-z\u3400-\u9fff]", "", value)


def _preferred_body(stored: Any, incoming: Any) -> str:
    stored_text = str(stored or "").strip()
    incoming_text = str(incoming or "").strip()
    if not incoming_text:
        return stored_text
    if not stored_text or len(incoming_text) >= len(stored_text) * 0.7:
        return incoming_text
    lines = [
        re.sub(r"[^0-9a-z\u3400-\u9fff]", "", line.lower())
        for line in stored_text.splitlines()
        if line.strip()
    ]
    if len(lines) >= 6 and len(set(lines)) / len(lines) < 0.7:
        return incoming_text
    return stored_text


def _search_text(parsed: dict[str, Any]) -> str:
    parts = [str(parsed.get("body_text") or "")]
    parts.extend(str(value) for value in parsed.get("tags") or [])
    parts.extend(str(comment.get("body_text") or "") for comment in parsed.get("comments") or [])
    return "\n".join(value for value in parts if value.strip())


def _post_markdown(source_key: str, parsed: dict[str, Any]) -> str:
    lines = [
        "---",
        f"source: {json.dumps(source_key, ensure_ascii=False)}",
        f"author: {json.dumps(parsed.get('author_label', ''), ensure_ascii=False)}",
        f"display_time: {json.dumps(parsed.get('display_time', ''), ensure_ascii=False)}",
        f"captured_estimated_from: {json.dumps(parsed.get('estimated_from') or '', ensure_ascii=False)}",
        f"captured_estimated_to: {json.dumps(parsed.get('estimated_to') or '', ensure_ascii=False)}",
        f"tags: {json.dumps(parsed.get('tags') or [], ensure_ascii=False)}",
        "---",
        "",
        str(parsed.get("body_text") or "").strip(),
        "",
    ]
    comments = parsed.get("comments") or []
    if comments:
        lines.extend(["## 评论", ""])
        for comment in comments:
            heading = " · ".join(
                value for value in (comment.get("author_label", ""), comment.get("display_time", "")) if value
            )
            lines.extend([f"### {heading or '匿名评论'}", "", str(comment.get("body_text") or "").strip(), ""])
    return "\n".join(lines).strip() + "\n"


def _run_markdown_path(run_id: str) -> Path:
    return settings.data_dir / "miniprogram_forum" / "runs" / run_id / "capture.md"


def _read_markdown_file(value: Any) -> str:
    if not value:
        return ""
    path = Path(str(value)).expanduser()
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _compose_run_document(source_markdown: str, existing_markdown: str, *, summary_override: str | None = None) -> str:
    """Combine the immutable capture stream with the durable AI-owned sections."""
    source = str(source_markdown or "").rstrip()
    existing = str(existing_markdown or "")
    summary = str(summary_override).strip() if summary_override is not None else _latest_nonempty_summary(existing)
    qa_section = _latest_qa_section(existing)
    sections = [source]
    if summary:
        sections.append(f"## AI 摘要\n\n{summary}")
    if qa_section:
        sections.append(f"## 追问记录\n\n{qa_section}")
    return "\n\n".join(section for section in sections if section.strip()).rstrip() + "\n"


def _latest_nonempty_summary(markdown: str) -> str:
    matches = list(re.finditer(
        r"^## AI 摘要\s*$\n([\s\S]*?)(?=^## 追问记录\s*$|\Z)",
        markdown,
        re.MULTILINE,
    ))
    for match in reversed(matches):
        value = re.sub(r"^<!--.*?-->\s*", "", match.group(1).strip(), flags=re.DOTALL).strip()
        if value:
            return value
    return ""


def _latest_qa_section(markdown: str) -> str:
    matches = list(re.finditer(r"^## 追问记录\s*$\n([\s\S]*?)(?=^## AI 摘要\s*$|\Z)", markdown, re.MULTILINE))
    for match in reversed(matches):
        value = match.group(1).strip()
        if "**问：**" in value or "#### " in value:
            return value
    return ""


def _display_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return parsed.strftime("%Y-%m-%d %H:%M:%S %Z").strip()


def _run_document_title(started_at: str) -> str:
    timestamp = _display_timestamp(started_at)
    compact = timestamp.rsplit(" ", 1)[0] if timestamp else "时间未知"
    return f"猹话会采集 · {compact}"


def _run_document_filename(started_at: str, run_id: str) -> str:
    timestamp = _display_timestamp(started_at)
    try:
        parsed = datetime.strptime(timestamp.rsplit(" ", 1)[0], "%Y-%m-%d %H:%M:%S")
        date_part = parsed.strftime("%Y-%m-%d-%H-%M-%S")
    except ValueError:
        date_part = "时间未知"
    return f"猹话会采集-{date_part}-{run_id[:8]}.md"


def _metric(value: Any) -> str:
    return "未显示" if value is None else str(value)


def _run_post_markdown(post: dict[str, Any], *, ordinal: int, captured_at: str) -> str:
    tags = " ".join(str(value) for value in post.get("tags") or []) or "无"
    category = str(post.get("category") or "").strip()
    if category and category not in tags:
        tags = f"{tags} {category}" if tags != "无" else category
    lines = [
        f"<!-- post-id:{post.get('id', '')} -->",
        f"## 帖子 {ordinal}",
        "",
        f"采集时间：{_display_timestamp(captured_at)}  ",
        f"用户：{str(post.get('author_label') or '匿名')}  ",
        f"发布时间：{str(post.get('display_time') or '未识别')}  ",
        f"标签：{tags}  ",
        (
            f"互动：收藏 {_metric(post.get('collect_count'))} · "
            f"评论 {_metric(post.get('comment_count'))} · "
            f"点赞 {_metric(post.get('like_count'))}"
        ),
        "",
        str(post.get("body_text") or "").strip() or "（正文未识别）",
        "",
    ]
    comments = post.get("comments") or []
    if comments:
        lines.extend(["### 评论", ""])
        for comment in comments:
            heading = " · ".join(
                str(value)
                for value in (comment.get("author_label"), comment.get("display_time"))
                if value
            )
            lines.extend(
                [
                    f"**{heading or '匿名评论'}**",
                    "",
                    str(comment.get("body_text") or "").strip() or "（内容未识别）",
                    "",
                ]
            )
    if not post.get("capture_complete", False):
        lines.extend(["> 本帖可能仍有未展开或未采集完整的评论。", ""])
    return "\n".join(lines).rstrip() + "\n"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def _loads(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.expanduser().resolve().relative_to(root.expanduser().resolve())
        return True
    except ValueError:
        return False


__all__ = ["FORUM_CAPTURE_CONTENT_TYPE", "ForumCaptureRepository", "repair_forum_capture_document_types"]
