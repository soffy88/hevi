"""HEVI-V3 GOLIVE3 API Router — Asset Library CRUD & Style Snapshots."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from hevi.subjects.reference_store import ReferenceStore

router = APIRouter(prefix="/golive3", tags=["golive3"])

_STORE_FILE = Path(os.getenv("HEVI_GOLIVE3_STORE", "output/golive3_persistence.json"))
_REF_STORE = ReferenceStore()


def _load_store() -> dict[str, Any]:
    if _STORE_FILE.is_file():
        try:
            return json.loads(_STORE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"assets": {}, "snapshots": {}, "shot_groups": {}}


def _save_store(data: dict[str, Any]) -> None:
    _STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STORE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class AssetCreateRequest(BaseModel):
    project_id: str = "default_project"
    kind: str = Field(..., description="character / scene / prop")
    name: str = Field(..., min_length=1)
    description: str = ""
    reference_images: list[str] = Field(default_factory=list)
    voice_binding: str | None = None
    tags: list[str] = Field(default_factory=list)


@router.get("/assets")
async def list_assets(project_id: str | None = None) -> list[dict[str, Any]]:
    store = _load_store()
    assets = list(store.get("assets", {}).values())
    if project_id:
        assets = [a for a in assets if a.get("project_id", "default_project") == project_id]
    return assets


@router.post("/assets", status_code=status.HTTP_201_CREATED)
async def create_asset(body: AssetCreateRequest) -> dict[str, Any]:
    if body.kind not in {"character", "scene", "prop"}:
        raise HTTPException(status_code=422, detail=f"Invalid asset kind: {body.kind!r}")
    
    asset_id = str(uuid.uuid4())
    validated_refs = _REF_STORE.validate_refs(body.reference_images)
    
    record = {
        "id": asset_id,
        "project_id": body.project_id,
        "kind": body.kind,
        "name": body.name,
        "description": body.description,
        "reference_images": validated_refs,
        "voice_binding": body.voice_binding,
        "tags": body.tags,
    }
    
    store = _load_store()
    store.setdefault("assets", {})[asset_id] = record
    _save_store(store)
    return record


@router.get("/assets/{asset_id}")
async def get_asset(asset_id: str) -> dict[str, Any]:
    store = _load_store()
    asset = store.get("assets", {}).get(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_id!r}")
    return asset


@router.delete("/assets/{asset_id}")
async def delete_asset(asset_id: str) -> dict[str, Any]:
    store = _load_store()
    if asset_id not in store.get("assets", {}):
        raise HTTPException(status_code=404, detail=f"Asset not found: {asset_id!r}")
    del store["assets"][asset_id]
    _save_store(store)
    return {"status": "deleted", "id": asset_id}


@router.get("/snapshots/{snapshot_id}")
async def get_project_snapshot(snapshot_id: str) -> dict[str, Any]:
    store = _load_store()
    snapshot = store.get("snapshots", {}).get(snapshot_id)
    if not snapshot:
        raise HTTPException(status_code=404, detail=f"Snapshot not found: {snapshot_id!r}")
    return snapshot


@router.get("/snapshots")
async def list_project_snapshots(project_id: str | None = None) -> list[dict[str, Any]]:
    store = _load_store()
    snapshots = list(store.get("snapshots", {}).values())
    if project_id:
        snapshots = [s for s in snapshots if s.get("project_id") == project_id]
    return snapshots
