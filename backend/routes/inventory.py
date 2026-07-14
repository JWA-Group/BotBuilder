"""Inventory API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.auth_deps import get_current_user_id_required
from backend.core.bot_access import require_bot_access
from backend.core.inventory_manager import (
    InventoryError,
    create_inventory_item,
    delete_inventory_items,
    detect_delimiter,
    fetch_inventory_items,
    import_inventory_txt,
    list_product_ids,
    preview_txt_import,
    preview_import_file,
    update_inventory_item,
)
from backend.db.database import get_db

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


class InventoryItemCreate(BaseModel):
    bot_id: int = Field(..., ge=1)
    product_id: str = Field(..., min_length=1, max_length=64)
    content: dict | str
    status: str = "in_stock"


class InventoryItemUpdate(BaseModel):
    bot_id: int = Field(..., ge=1)
    product_id: str | None = None
    content: dict | str | None = None
    status: str | None = None


class InventoryBulkDelete(BaseModel):
    bot_id: int = Field(..., ge=1)
    item_ids: list[int] = Field(default_factory=list)


class TxtParsePayload(BaseModel):
    bot_id: int = Field(..., ge=1)
    file_path: str = Field(..., min_length=1)
    delimiter: str | None = None


class TxtImportPayload(BaseModel):
    bot_id: int = Field(..., ge=1)
    file_path: str = Field(..., min_length=1)
    product_id: str = Field(..., min_length=1, max_length=64)
    delimiter: str = ":"
    column_map: list[str] = Field(default_factory=list)
    static_fields: dict = Field(default_factory=dict)


async def _guard(bot_id: int, user_id: int, db: AsyncSession) -> None:
    await require_bot_access(db, bot_id, user_id)


@router.get("/product-ids")
async def get_product_ids(
    bot_id: int = Query(..., ge=1),
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _guard(bot_id, user_id, db)
    try:
        return {"product_ids": list_product_ids(bot_id)}
    except InventoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/items")
async def get_inventory_items(
    bot_id: int = Query(..., ge=1),
    product_id: str | None = None,
    limit: int = Query(2000, ge=1, le=10000),
    offset: int = Query(0, ge=0),
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _guard(bot_id, user_id, db)
    try:
        return fetch_inventory_items(bot_id, product_id=product_id, limit=limit, offset=offset)
    except InventoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/items")
async def post_inventory_item(
    payload: InventoryItemCreate,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _guard(payload.bot_id, user_id, db)
    try:
        return create_inventory_item(
            payload.bot_id,
            product_id=payload.product_id,
            content=payload.content,
            status=payload.status,
        )
    except InventoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/items/{item_id}")
async def put_inventory_item(
    item_id: int,
    payload: InventoryItemUpdate,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _guard(payload.bot_id, user_id, db)
    try:
        return update_inventory_item(
            payload.bot_id,
            item_id,
            product_id=payload.product_id,
            content=payload.content,
            status=payload.status,
        )
    except InventoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/items")
async def delete_inventory_bulk(
    payload: InventoryBulkDelete,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _guard(payload.bot_id, user_id, db)
    try:
        return delete_inventory_items(payload.bot_id, payload.item_ids)
    except InventoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/parse-txt")
async def parse_txt(
    payload: TxtParsePayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _guard(payload.bot_id, user_id, db)
    try:
        return preview_import_file(payload.file_path.strip(), delimiter=payload.delimiter)
    except InventoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/import")
async def import_txt(
    payload: TxtImportPayload,
    user_id: int = Depends(get_current_user_id_required),
    db: AsyncSession = Depends(get_db),
):
    await _guard(payload.bot_id, user_id, db)
    try:
        return import_inventory_txt(
            payload.bot_id,
            file_path=payload.file_path.strip(),
            product_id=payload.product_id,
            delimiter=payload.delimiter,
            column_map=payload.column_map,
            static_fields=payload.static_fields,
        )
    except InventoryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
