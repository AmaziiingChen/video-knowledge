from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.database import connect, initialize_database
from services.prompt_templates import (
    PromptTemplateRecord,
    PromptTemplateRepository,
    default_prompt_for_key,
)
from services.prompt_workspace import PromptWorkspaceRepository, folder_to_dict
from services.prompt_file_store import (
    prompt_file_path,
    remove_prompt_files,
    sync_prompt_files,
    write_prompt_file,
)
from services.campus_prompt_defaults import campus_default_for_key
from services.system_prompt_catalog import list_fixed_system_prompts


router = APIRouter()


class PromptTemplateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    task_type: str = Field(min_length=1, max_length=80)
    version: str = Field(min_length=1, max_length=40)
    template: str = Field(min_length=1)
    variables_schema: dict | str | None = None
    is_active: bool = False
    folder_id: str | None = None
    sort_order: float = 0


class PromptTemplateUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    template: str | None = Field(default=None, min_length=1)
    variables_schema: dict | str | None = None
    folder_id: str | None = None
    sort_order: float | None = None


class PromptTemplateResponse(BaseModel):
    id: str
    name: str
    task_type: str
    version: str
    template: str
    variables_schema: str | None = None
    is_active: bool
    folder_id: str | None = None
    sort_order: float = 0
    created_at: str
    updated_at: str
    local_path: str | None = None


class PromptFolderRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    task_type: str = Field(min_length=1, max_length=80)
    parent_folder_id: str | None = None
    sort_order: float = 0


class PromptFolderUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    parent_folder_id: str | None = None
    sort_order: float | None = None


class PromptFolderResponse(BaseModel):
    id: str
    name: str
    task_type: str
    parent_folder_id: str | None = None
    sort_order: float
    created_at: str
    updated_at: str


class PromptTrashEntryResponse(BaseModel):
    entry_type: str
    id: str
    name: str
    task_type: str
    deleted_at: str
    item_count: int = 1


class SystemPromptResponse(BaseModel):
    id: str
    category: str
    name: str
    description: str
    template: str


@router.get("/system-prompts", response_model=list[SystemPromptResponse])
async def list_system_prompts():
    """Return code-owned system messages for read-only inspection."""
    return [SystemPromptResponse(**item) for item in list_fixed_system_prompts()]


def _to_response(record: PromptTemplateRecord) -> PromptTemplateResponse:
    return PromptTemplateResponse(
        id=record.id,
        name=record.name,
        task_type=record.task_type,
        version=record.version,
        template=record.template,
        variables_schema=record.variables_schema,
        is_active=record.is_active,
        folder_id=record.folder_id,
        sort_order=record.sort_order,
        created_at=record.created_at,
        updated_at=record.updated_at,
        local_path=str(prompt_file_path(record.id) or "") or None,
    )


@router.get("/prompts", response_model=list[PromptTemplateResponse])
async def list_prompt_templates(task_type: str | None = None):
    initialize_database()
    with connect() as connection:
        sync_prompt_files(connection)
        connection.commit()
        repository = PromptTemplateRepository(connection)
        return [_to_response(record) for record in repository.list_templates(task_type)]


@router.post("/prompts", response_model=PromptTemplateResponse)
async def create_prompt_template(req: PromptTemplateRequest):
    initialize_database()
    with connect() as connection:
        repository = PromptTemplateRepository(connection)
        try:
            record = repository.create_template(
                name=req.name.strip(),
                task_type=req.task_type.strip(),
                version=req.version.strip(),
                template=req.template,
                variables_schema=req.variables_schema,
                is_active=req.is_active,
                folder_id=req.folder_id,
                sort_order=req.sort_order,
            )
            connection.commit()
            write_prompt_file(record)
        except Exception as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _to_response(record)


@router.patch("/prompts/{template_id}", response_model=PromptTemplateResponse)
async def update_prompt_template(template_id: str, req: PromptTemplateUpdateRequest):
    initialize_database()
    with connect() as connection:
        repository = PromptTemplateRepository(connection)
        try:
            record = repository.update_template(
                template_id,
                name=req.name,
                template=req.template,
                variables_schema=req.variables_schema,
                folder_id=req.folder_id,
                sort_order=req.sort_order,
                update_folder="folder_id" in req.model_fields_set,
            )
            connection.commit()
            write_prompt_file(record)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Prompt 模板不存在") from exc
        return _to_response(record)


@router.delete("/prompts/{template_id}", status_code=204)
async def delete_prompt_template(template_id: str):
    initialize_database()
    with connect() as connection:
        repository = PromptTemplateRepository(connection)
        try:
            repository.delete_template(template_id)
            connection.commit()
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Prompt 模板不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/prompts/{template_id}/activate", response_model=PromptTemplateResponse)
async def activate_prompt_template(template_id: str):
    initialize_database()
    with connect() as connection:
        repository = PromptTemplateRepository(connection)
        try:
            record = repository.activate_template(template_id)
            connection.commit()
            write_prompt_file(record)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Prompt 模板不存在") from exc
        return _to_response(record)


@router.post("/prompts/{template_id}/reset", response_model=PromptTemplateResponse)
async def reset_prompt_template(template_id: str):
    """Restore one built-in template without exposing its contract fields to editing."""
    initialize_database()
    with connect() as connection:
        repository = PromptTemplateRepository(connection)
        try:
            record = repository.get_template(template_id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="Prompt 模板不存在") from exc
        default = default_prompt_for_key(record.default_key)
        default = default or campus_default_for_key(record.default_key)
        if default is None:
            raise HTTPException(status_code=409, detail="自定义提示词没有可恢复的默认版本")
        record = repository.update_template(
            template_id,
            template=str(default["template"]),
            variables_schema=default.get("variables_schema", record.variables_schema),
        )
        connection.commit()
        write_prompt_file(record)
        return _to_response(record)


@router.get("/prompt-folders", response_model=list[PromptFolderResponse])
async def list_prompt_folders(task_type: str | None = None):
    initialize_database()
    with connect() as connection:
        repository = PromptWorkspaceRepository(connection)
        return [PromptFolderResponse(**folder_to_dict(record)) for record in repository.list_folders(task_type)]


@router.post("/prompt-folders", response_model=PromptFolderResponse)
async def create_prompt_folder(req: PromptFolderRequest):
    initialize_database()
    with connect() as connection:
        repository = PromptWorkspaceRepository(connection)
        try:
            record = repository.create_folder(
                name=req.name,
                task_type=req.task_type,
                parent_folder_id=req.parent_folder_id,
                sort_order=req.sort_order,
            )
            connection.commit()
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return PromptFolderResponse(**folder_to_dict(record))


@router.patch("/prompt-folders/{folder_id}", response_model=PromptFolderResponse)
async def update_prompt_folder(folder_id: str, req: PromptFolderUpdateRequest):
    initialize_database()
    with connect() as connection:
        repository = PromptWorkspaceRepository(connection)
        try:
            record = repository.update_folder(
                folder_id,
                name=req.name,
                parent_folder_id=req.parent_folder_id,
                sort_order=req.sort_order,
                update_parent="parent_folder_id" in req.model_fields_set,
            )
            connection.commit()
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="提示词文件夹不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return PromptFolderResponse(**folder_to_dict(record))


@router.delete("/prompt-folders/{folder_id}", status_code=204)
async def delete_prompt_folder(folder_id: str):
    initialize_database()
    with connect() as connection:
        repository = PromptWorkspaceRepository(connection)
        try:
            repository.trash_folder(folder_id)
            connection.commit()
        except LookupError as exc:
            raise HTTPException(status_code=404, detail="提示词文件夹不存在") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/prompts/trash", response_model=list[PromptTrashEntryResponse])
async def list_prompt_trash():
    initialize_database()
    with connect() as connection:
        return PromptWorkspaceRepository(connection).list_trash()


@router.post("/prompts/trash/{entry_type}/{entry_id}/restore", response_model=dict)
async def restore_prompt_trash(entry_type: str, entry_id: str):
    initialize_database()
    with connect() as connection:
        repository = PromptWorkspaceRepository(connection)
        try:
            result = repository.restore_trash(entry_type, entry_id)
            connection.commit()
            return result
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/prompts/trash/{entry_type}/{entry_id}", response_model=dict)
async def permanently_delete_prompt_trash(entry_type: str, entry_id: str):
    initialize_database()
    with connect() as connection:
        repository = PromptWorkspaceRepository(connection)
        try:
            result = repository.permanently_delete_trash(entry_type, entry_id)
            connection.commit()
            remove_prompt_files(result["deleted_template_ids"])
            result.pop("deleted_template_ids", None)
            return result
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
