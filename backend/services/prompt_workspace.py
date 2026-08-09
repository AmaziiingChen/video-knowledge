from __future__ import annotations

from dataclasses import asdict, dataclass
import sqlite3

from services.database import utc_now_iso
from services.prompt_templates import MULTI_ACTIVE_TASK_TYPES
from services.repository import new_id


@dataclass(frozen=True)
class PromptFolderRecord:
    id: str
    name: str
    task_type: str
    parent_folder_id: str | None
    sort_order: float
    deleted_at: str | None
    trash_batch_id: str | None
    created_at: str
    updated_at: str


class PromptWorkspaceRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def list_folders(self, task_type: str | None = None) -> list[PromptFolderRecord]:
        if task_type:
            rows = self.connection.execute(
                """
                SELECT * FROM prompt_folders
                WHERE task_type = ? AND deleted_at IS NULL
                ORDER BY sort_order ASC, name ASC
                """,
                (task_type,),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                SELECT * FROM prompt_folders
                WHERE deleted_at IS NULL
                ORDER BY task_type ASC, sort_order ASC, name ASC
                """
            ).fetchall()
        return [_folder_from_row(row) for row in rows]

    def get_folder(self, folder_id: str, *, include_deleted: bool = False) -> PromptFolderRecord:
        sql = "SELECT * FROM prompt_folders WHERE id = ?"
        if not include_deleted:
            sql += " AND deleted_at IS NULL"
        row = self.connection.execute(sql, (folder_id,)).fetchone()
        if row is None:
            raise LookupError(f"prompt folder not found: {folder_id}")
        return _folder_from_row(row)

    def create_folder(
        self,
        *,
        name: str,
        task_type: str,
        parent_folder_id: str | None = None,
        sort_order: float = 0,
    ) -> PromptFolderRecord:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("文件夹名称不能为空")
        self._validate_parent(task_type, parent_folder_id)
        self._ensure_unique_name(cleaned_name, task_type, parent_folder_id)
        now = utc_now_iso()
        folder_id = new_id()
        self.connection.execute(
            """
            INSERT INTO prompt_folders (
                id, name, task_type, parent_folder_id, sort_order,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (folder_id, cleaned_name, task_type, parent_folder_id, float(sort_order), now, now),
        )
        return self.get_folder(folder_id)

    def update_folder(
        self,
        folder_id: str,
        *,
        name: str | None = None,
        parent_folder_id: str | None = None,
        sort_order: float | None = None,
        update_parent: bool = False,
    ) -> PromptFolderRecord:
        current = self.get_folder(folder_id)
        next_name = name.strip() if name is not None else current.name
        if not next_name:
            raise ValueError("文件夹名称不能为空")
        next_parent_id = parent_folder_id if update_parent else current.parent_folder_id
        if next_parent_id == folder_id:
            raise ValueError("文件夹不能移动到自身")
        self._validate_parent(current.task_type, next_parent_id)
        if next_parent_id and next_parent_id in self._descendant_folder_ids(folder_id):
            raise ValueError("文件夹不能移动到自己的子文件夹")
        self._ensure_unique_name(next_name, current.task_type, next_parent_id, exclude_id=folder_id)
        self.connection.execute(
            """
            UPDATE prompt_folders
            SET name = ?, parent_folder_id = ?, sort_order = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                next_name,
                next_parent_id,
                float(sort_order) if sort_order is not None else current.sort_order,
                utc_now_iso(),
                folder_id,
            ),
        )
        return self.get_folder(folder_id)

    def trash_folder(self, folder_id: str) -> str:
        self.get_folder(folder_id)
        folder_ids = self._descendant_folder_ids(folder_id)
        template_rows = self._templates_in_folders(folder_ids)
        self._ensure_templates_remain(template_rows)
        batch_id = new_id()
        now = utc_now_iso()
        placeholders = ",".join("?" for _ in folder_ids)
        template_ids = [str(row["id"]) for row in template_rows]
        self._replace_active_templates(template_rows, set(template_ids), now)
        if template_ids:
            template_placeholders = ",".join("?" for _ in template_ids)
            self.connection.execute(
                f"""
                UPDATE prompt_templates
                SET is_active = 0, deleted_at = ?, trash_batch_id = ?, updated_at = ?
                WHERE id IN ({template_placeholders})
                """,
                (now, batch_id, now, *template_ids),
            )
            self._ensure_active_templates({str(row["task_type"]) for row in template_rows}, now)
        self.connection.execute(
            f"""
            UPDATE prompt_folders
            SET deleted_at = ?, trash_batch_id = ?, updated_at = ?
            WHERE id IN ({placeholders})
            """,
            (now, batch_id, now, *folder_ids),
        )
        return batch_id

    def list_trash(self) -> list[dict]:
        folder_rows = self.connection.execute(
            """
            SELECT * FROM prompt_folders
            WHERE deleted_at IS NOT NULL
            ORDER BY deleted_at DESC, name ASC
            """
        ).fetchall()
        template_rows = self.connection.execute(
            """
            SELECT * FROM prompt_templates
            WHERE deleted_at IS NOT NULL
            ORDER BY deleted_at DESC, name ASC
            """
        ).fetchall()
        entries: list[dict] = []
        represented_batches: set[str] = set()
        folders_by_batch: dict[str, list[sqlite3.Row]] = {}
        for row in folder_rows:
            batch_id = str(row["trash_batch_id"] or row["id"])
            folders_by_batch.setdefault(batch_id, []).append(row)
        for batch_id, rows in folders_by_batch.items():
            row_ids = {str(row["id"]) for row in rows}
            root = next((row for row in rows if not row["parent_folder_id"] or str(row["parent_folder_id"]) not in row_ids), rows[0])
            item_count = len(rows) + sum(1 for row in template_rows if str(row["trash_batch_id"] or row["id"]) == batch_id)
            entries.append({
                "entry_type": "folder",
                "id": str(root["id"]),
                "name": str(root["name"]),
                "task_type": str(root["task_type"]),
                "deleted_at": str(root["deleted_at"]),
                "item_count": item_count,
            })
            represented_batches.add(batch_id)
        for row in template_rows:
            batch_id = str(row["trash_batch_id"] or row["id"])
            if batch_id in represented_batches:
                continue
            entries.append({
                "entry_type": "prompt",
                "id": str(row["id"]),
                "name": str(row["name"]),
                "task_type": str(row["task_type"]),
                "deleted_at": str(row["deleted_at"]),
                "item_count": 1,
            })
        entries.sort(key=lambda entry: entry["deleted_at"], reverse=True)
        return entries

    def restore_trash(self, entry_type: str, entry_id: str) -> dict:
        table = self._trash_table(entry_type)
        row = self.connection.execute(
            f"SELECT trash_batch_id FROM {table} WHERE id = ? AND deleted_at IS NOT NULL",
            (entry_id,),
        ).fetchone()
        if row is None:
            raise LookupError("提示词回收站项目不存在")
        batch_id = str(row["trash_batch_id"] or entry_id)
        now = utc_now_iso()
        restored_types = [
            str(row["task_type"])
            for row in self.connection.execute(
                "SELECT DISTINCT task_type FROM prompt_templates WHERE trash_batch_id = ?",
                (batch_id,),
            ).fetchall()
        ]
        self.connection.execute(
            """
            UPDATE prompt_folders
            SET deleted_at = NULL, trash_batch_id = NULL, updated_at = ?
            WHERE trash_batch_id = ?
            """,
            (now, batch_id),
        )
        self.connection.execute(
            """
            UPDATE prompt_templates
            SET deleted_at = NULL, trash_batch_id = NULL, updated_at = ?
            WHERE trash_batch_id = ?
            """,
            (now, batch_id),
        )
        for task_type in restored_types:
            active = self.connection.execute(
                """
                SELECT id FROM prompt_templates
                WHERE task_type = ? AND deleted_at IS NULL AND is_active = 1
                LIMIT 1
                """,
                (task_type,),
            ).fetchone()
            if active is None:
                replacement = self.connection.execute(
                    """
                    SELECT id FROM prompt_templates
                    WHERE task_type = ? AND deleted_at IS NULL
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT 1
                    """,
                    (task_type,),
                ).fetchone()
                if replacement:
                    self.connection.execute(
                        "UPDATE prompt_templates SET is_active = 1, updated_at = ? WHERE id = ?",
                        (now, replacement["id"]),
                    )
        return {"success": True, "entry_type": entry_type, "id": entry_id}

    def permanently_delete_trash(self, entry_type: str, entry_id: str) -> dict:
        table = self._trash_table(entry_type)
        row = self.connection.execute(
            f"SELECT trash_batch_id FROM {table} WHERE id = ? AND deleted_at IS NOT NULL",
            (entry_id,),
        ).fetchone()
        if row is None:
            raise LookupError("提示词回收站项目不存在")
        batch_id = str(row["trash_batch_id"] or entry_id)
        template_ids = [
            str(item["id"])
            for item in self.connection.execute(
                "SELECT id FROM prompt_templates WHERE trash_batch_id = ?",
                (batch_id,),
            ).fetchall()
        ]
        self.connection.execute("DELETE FROM prompt_templates WHERE trash_batch_id = ?", (batch_id,))
        folder_rows = self.connection.execute(
            "SELECT id FROM prompt_folders WHERE trash_batch_id = ?",
            (batch_id,),
        ).fetchall()
        folder_ids = [str(item["id"]) for item in folder_rows]
        if folder_ids:
            placeholders = ",".join("?" for _ in folder_ids)
            self.connection.execute(f"DELETE FROM prompt_folders WHERE id IN ({placeholders})", folder_ids)
        return {
            "success": True,
            "entry_type": entry_type,
            "id": entry_id,
            "deleted_template_ids": template_ids,
        }

    def _validate_parent(self, task_type: str, parent_folder_id: str | None) -> None:
        if not parent_folder_id:
            return
        parent = self.get_folder(parent_folder_id)
        if parent.task_type != task_type:
            raise ValueError("子文件夹必须与上级文件夹属于同一功能")

    def _ensure_unique_name(
        self,
        name: str,
        task_type: str,
        parent_folder_id: str | None,
        *,
        exclude_id: str | None = None,
    ) -> None:
        rows = self.connection.execute(
            """
            SELECT id FROM prompt_folders
            WHERE task_type = ? AND parent_folder_id IS ? AND name = ? AND deleted_at IS NULL
            """,
            (task_type, parent_folder_id, name),
        ).fetchall()
        if any(str(row["id"]) != exclude_id for row in rows):
            raise ValueError("同级文件夹名称已存在")

    def _descendant_folder_ids(self, folder_id: str) -> set[str]:
        ids = {folder_id}
        changed = True
        while changed:
            changed = False
            rows = self.connection.execute(
                "SELECT id, parent_folder_id FROM prompt_folders WHERE deleted_at IS NULL"
            ).fetchall()
            for row in rows:
                parent_id = str(row["parent_folder_id"]) if row["parent_folder_id"] else None
                row_id = str(row["id"])
                if parent_id in ids and row_id not in ids:
                    ids.add(row_id)
                    changed = True
        return ids

    def _templates_in_folders(self, folder_ids: set[str]) -> list[sqlite3.Row]:
        if not folder_ids:
            return []
        placeholders = ",".join("?" for _ in folder_ids)
        return self.connection.execute(
            f"SELECT * FROM prompt_templates WHERE folder_id IN ({placeholders}) AND deleted_at IS NULL",
            tuple(folder_ids),
        ).fetchall()

    def _ensure_templates_remain(self, rows: list[sqlite3.Row]) -> None:
        deleted_by_type: dict[str, int] = {}
        for row in rows:
            task_type = str(row["task_type"])
            deleted_by_type[task_type] = deleted_by_type.get(task_type, 0) + 1
        for task_type, deleted_count in deleted_by_type.items():
            total = int(self.connection.execute(
                "SELECT COUNT(*) FROM prompt_templates WHERE task_type = ? AND deleted_at IS NULL",
                (task_type,),
            ).fetchone()[0])
            if total - deleted_count < 1:
                raise ValueError("文件夹中包含该功能最后一个提示词，无法删除")

    def _replace_active_templates(self, rows: list[sqlite3.Row], deleted_ids: set[str], now: str) -> None:
        affected_types = {
            str(row["task_type"])
            for row in rows
            if bool(row["is_active"]) and str(row["task_type"]) not in MULTI_ACTIVE_TASK_TYPES
        }
        for task_type in affected_types:
            placeholders = ",".join("?" for _ in deleted_ids)
            replacement = self.connection.execute(
                f"""
                SELECT id FROM prompt_templates
                WHERE task_type = ? AND deleted_at IS NULL AND id NOT IN ({placeholders})
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                (task_type, *deleted_ids),
            ).fetchone()
            self.connection.execute(
                "UPDATE prompt_templates SET is_active = 0, updated_at = ? WHERE task_type = ? AND deleted_at IS NULL",
                (now, task_type),
            )
            if replacement:
                self.connection.execute(
                    "UPDATE prompt_templates SET is_active = 1, updated_at = ? WHERE id = ?",
                    (now, replacement["id"]),
                )

    def _ensure_active_templates(self, task_types: set[str], now: str) -> None:
        for task_type in task_types:
            active = self.connection.execute(
                """
                SELECT id FROM prompt_templates
                WHERE task_type = ? AND deleted_at IS NULL AND is_active = 1
                LIMIT 1
                """,
                (task_type,),
            ).fetchone()
            if active:
                continue
            replacement = self.connection.execute(
                """
                SELECT id FROM prompt_templates
                WHERE task_type = ? AND deleted_at IS NULL
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                (task_type,),
            ).fetchone()
            if replacement:
                self.connection.execute(
                    "UPDATE prompt_templates SET is_active = 1, updated_at = ? WHERE id = ?",
                    (now, replacement["id"]),
                )

    @staticmethod
    def _trash_table(entry_type: str) -> str:
        if entry_type == "folder":
            return "prompt_folders"
        if entry_type == "prompt":
            return "prompt_templates"
        raise ValueError("不支持的提示词回收站项目")


def folder_to_dict(record: PromptFolderRecord) -> dict:
    return asdict(record)


def _folder_from_row(row: sqlite3.Row) -> PromptFolderRecord:
    return PromptFolderRecord(
        id=str(row["id"]),
        name=str(row["name"]),
        task_type=str(row["task_type"]),
        parent_folder_id=str(row["parent_folder_id"]) if row["parent_folder_id"] else None,
        sort_order=float(row["sort_order"] or 0),
        deleted_at=str(row["deleted_at"]) if row["deleted_at"] else None,
        trash_batch_id=str(row["trash_batch_id"]) if row["trash_batch_id"] else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )
