from __future__ import annotations

from collections import defaultdict

from services.campus_source_settings import load_campus_source_settings, update_campus_source_setting
from services.campus_sources import get_campus_source
from services.content_index import ensure_content_index_ready
from services.database import connect, initialize_database, utc_now_iso
from services.wechat_reports import list_groups


def list_library_source_groups() -> list[dict]:
    """Expose report/source groups as stable, virtual library collections.

    The group stores source membership, never a second physical copy of a
    document.  Each source points at its bound library folder ID, so changing
    the source folder's name or position does not alter the group membership.
    """
    initialize_database()
    ensure_content_index_ready()
    groups = [dict(group) for group in list_groups()]
    by_id = {str(group["id"]): group for group in groups}
    sources_by_group: dict[str, list[dict]] = defaultdict(list)

    with connect() as connection:
        wechat_rows = connection.execute(
            """
            SELECT membership.group_id, subscription.id AS subscription_id,
                   subscription.mp_name, binding.folder_id
            FROM wechat_subscription_group_memberships AS membership
            JOIN wechat_subscriptions AS subscription ON subscription.id = membership.subscription_id
            LEFT JOIN library_source_folder_bindings AS binding
              ON binding.source_type = 'wechat_subscription'
             AND binding.source_key = subscription.id
            LEFT JOIN library_folders AS folder ON folder.id = binding.folder_id
            WHERE binding.folder_id IS NULL OR folder.deleted_at IS NULL
            ORDER BY subscription.mp_name COLLATE NOCASE
            """
        ).fetchall()
        for row in wechat_rows:
            group_id = str(row["group_id"])
            if group_id not in by_id:
                continue
            sources_by_group[group_id].append(
                {
                    "id": f"wechat:{row['subscription_id']}",
                    "source_id": str(row["subscription_id"]),
                    "label": str(row["mp_name"] or "未命名公众号"),
                    "kind": "wechat",
                    "folder_ids": [str(row["folder_id"])] if row["folder_id"] else [],
                }
            )

        rss_rows = connection.execute(
            """
            SELECT membership.group_id, source.id AS source_id, source.title,
                   binding.folder_id
            FROM rss_source_group_memberships AS membership
            JOIN rss_sources AS source ON source.id = membership.source_id
            LEFT JOIN library_source_folder_bindings AS binding
              ON binding.source_type = 'rss_source'
             AND binding.source_key = source.id
            LEFT JOIN library_folders AS folder ON folder.id = binding.folder_id
            WHERE binding.folder_id IS NULL OR folder.deleted_at IS NULL
            ORDER BY source.title COLLATE NOCASE
            """
        ).fetchall()
        for row in rss_rows:
            group_id = str(row["group_id"])
            if group_id not in by_id:
                continue
            sources_by_group[group_id].append(
                {
                    "id": f"rss:{row['source_id']}",
                    "source_id": str(row["source_id"]),
                    "label": str(row["title"] or "未命名 RSS 订阅"),
                    "kind": "rss",
                    "folder_ids": [str(row["folder_id"])] if row["folder_id"] else [],
                }
            )

        binding_rows = connection.execute(
            """
            SELECT binding.source_key, binding.folder_id
            FROM library_source_folder_bindings AS binding
            JOIN library_folders AS folder ON folder.id = binding.folder_id
            WHERE binding.source_type = 'campus_source_section'
              AND binding.folder_id IS NOT NULL AND folder.deleted_at IS NULL
            """
        ).fetchall()

    campus_folders_by_prefix: dict[str, list[str]] = defaultdict(list)
    for row in binding_rows:
        source_key = str(row["source_key"] or "")
        prefix = source_key.split("\x1f", 1)[0]
        if prefix:
            campus_folders_by_prefix[prefix].append(str(row["folder_id"]))

    for setting in load_campus_source_settings():
        source = get_campus_source(str(setting["slug"]))
        # GWT is stored by publication department under the 公文通 source
        # folder, whereas the other campus sources use their display name.
        prefix = "公文通" if source.slug == "gwt" else source.name
        folder_ids = list(dict.fromkeys(campus_folders_by_prefix.get(prefix, [])))
        for group_id in setting.get("group_ids", []):
            group_id = str(group_id)
            if group_id not in by_id:
                continue
            sources_by_group[group_id].append(
                {
                    "id": f"campus:{source.slug}",
                    "source_id": source.slug,
                    "label": source.name,
                    "kind": "campus",
                    "folder_ids": folder_ids,
                }
            )

    for group in groups:
        group["sources"] = sources_by_group.get(str(group["id"]), [])
    return groups


def remove_library_source_group_member(group_id: str, source_kind: str, source_id: str) -> dict:
    """Remove a source from one virtual group without deleting its content.

    Report groups are shared by WeChat, campus websites and RSS.  Keeping the
    mutation here gives the library UI one narrowly-scoped operation instead of
    making it reconstruct each provider's full settings object in the browser.
    """
    normalized_group_id = str(group_id).strip()
    normalized_source_id = str(source_id).strip()
    normalized_kind = str(source_kind).strip().lower()
    if normalized_kind not in {"wechat", "campus", "rss"}:
        raise ValueError("不支持的来源类型")
    if not normalized_group_id or not normalized_source_id:
        raise ValueError("缺少分组或来源标识")

    initialize_database()
    if normalized_kind == "campus":
        with connect() as connection:
            group = connection.execute(
                "SELECT id FROM wechat_subscription_groups WHERE id=?",
                (normalized_group_id,),
            ).fetchone()
        if not group:
            raise LookupError("分组不存在")
        setting = next(
            (item for item in load_campus_source_settings() if str(item["slug"]) == normalized_source_id),
            None,
        )
        if not setting:
            raise LookupError("校园来源不存在")
        current_group_ids = [str(item) for item in setting.get("group_ids", [])]
        if normalized_group_id not in current_group_ids:
            raise LookupError("该来源不在这个分组中")
        update_campus_source_setting(
            normalized_source_id,
            group_ids=[item for item in current_group_ids if item != normalized_group_id],
        )
        return {"success": True, "group_id": normalized_group_id, "source_kind": normalized_kind, "source_id": normalized_source_id}

    with connect() as connection:
        group = connection.execute(
            "SELECT id FROM wechat_subscription_groups WHERE id=?",
            (normalized_group_id,),
        ).fetchone()
        if not group:
            raise LookupError("分组不存在")
        if normalized_kind == "wechat":
            source = connection.execute(
                "SELECT id FROM wechat_subscriptions WHERE id=?",
                (normalized_source_id,),
            ).fetchone()
            if not source:
                raise LookupError("公众号来源不存在")
            deleted = connection.execute(
                "DELETE FROM wechat_subscription_group_memberships WHERE group_id=? AND subscription_id=?",
                (normalized_group_id, normalized_source_id),
            ).rowcount
            if not deleted:
                raise LookupError("该来源不在这个分组中")
            remaining = connection.execute(
                """SELECT group_id FROM wechat_subscription_group_memberships
                   WHERE subscription_id=? ORDER BY created_at, group_id LIMIT 1""",
                (normalized_source_id,),
            ).fetchone()
            connection.execute(
                "UPDATE wechat_subscriptions SET group_id=?, updated_at=? WHERE id=?",
                (str(remaining["group_id"]) if remaining else None, utc_now_iso(), normalized_source_id),
            )
        else:
            source = connection.execute("SELECT id FROM rss_sources WHERE id=?", (normalized_source_id,)).fetchone()
            if not source:
                raise LookupError("RSS 来源不存在")
            deleted = connection.execute(
                "DELETE FROM rss_source_group_memberships WHERE group_id=? AND source_id=?",
                (normalized_group_id, normalized_source_id),
            ).rowcount
            if not deleted:
                raise LookupError("该来源不在这个分组中")
        connection.commit()
    return {"success": True, "group_id": normalized_group_id, "source_kind": normalized_kind, "source_id": normalized_source_id}


__all__ = ["list_library_source_groups", "remove_library_source_group_member"]
