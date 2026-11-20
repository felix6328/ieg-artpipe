"""HTTP entry points for the local asset workspace."""
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .library import Library, MissingRecord
from .settings import load_settings, storage_root
from .storage import BadAsset

router = APIRouter(prefix="/api/assetgate")


@lru_cache(maxsize=1)
def workspace():
    config = load_settings()
    return Library(storage_root(config), config)


@router.get("/assets")
def assets():
    return workspace().asset_list()


@router.post("/assets", status_code=201)
def upload(file: Annotated[UploadFile, File()], name: Annotated[str, Form(max_length=150)] = "",
           asset_type: Annotated[str, Form(max_length=60)] = "model",
           model_entry: Annotated[str, Form(max_length=512)] = ""):
    try:
        return workspace().upload(file.file, file.filename, name, asset_type, model_entry.strip())
    except BadAsset as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        file.file.close()


@router.get("/assets/{asset_id}")
def asset(asset_id: str):
    try:
        return workspace().detail(asset_id)
    except MissingRecord as exc:
        raise HTTPException(404, str(exc)) from exc
