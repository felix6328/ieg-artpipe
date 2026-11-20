"""HTTP entry points for the local asset workspace."""
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

from .blender import detect_blender, tail
from .database import record
from .workflow import Conflict, Workflow
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
        library = workspace()
        return library.upload(file.file, file.filename, name, asset_type, model_entry.strip(),
                              after_create=Workflow(library).queue_inspection)
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


@router.get("/system")
def system():
    limits = workspace().config["upload"]
    return {"mode": "BLENDER", "blender_detected": bool(detect_blender()), "max_upload_bytes": limits["max_bytes"],
            "ruleset_version": workspace().config["ruleset_version"]}


class ProcessRequest(BaseModel):
    operations: list[Literal["apply_transforms", "recalculate_normals", "smart_uv"]] = Field(default_factory=list,
                                                                                          max_length=3)
    target_format: Literal["GLB", "GLTF", "FBX", "OBJ"] | None = None
    uv_angle_degrees: float = Field(default=66, ge=1, le=89, allow_inf_nan=False)
    uv_island_margin: float = Field(default=0.02, ge=0, le=0.2, allow_inf_nan=False)


class ReviewRequest(BaseModel):
    report_id: str = Field(min_length=1, max_length=64)
    reviewer: str = Field(min_length=1, max_length=120, pattern=r"\S")
    decision: Literal["APPROVED", "REJECTED"]
    note: str = Field(default="", max_length=2000)


def action(method, *args):
    try:
        return getattr(Workflow(workspace()), method)(*args)
    except MissingRecord as exc:
        raise HTTPException(404, str(exc)) from exc
    except Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except BadAsset as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/versions/{version_id}/inspect", status_code=202)
def inspect(version_id: str):
    return action("submit", version_id, "inspect")


@router.post("/versions/{version_id}/process", status_code=202)
def process(version_id: str, settings: ProcessRequest):
    return action("submit", version_id, "process", settings.model_dump())


@router.post("/versions/{version_id}/select")
def select(version_id: str):
    return action("select", version_id)


@router.post("/versions/{version_id}/review", status_code=201)
def review(version_id: str, data: ReviewRequest):
    return action("review", version_id, data.report_id, data.reviewer.strip(), data.decision, data.note.strip())


@router.post("/versions/{version_id}/export", status_code=202)
def export(version_id: str):
    return action("submit", version_id, "export")


@router.get("/versions/{version_id}/preview")
def preview(version_id: str):
    library = workspace()
    try:
        version = library.version(version_id)
        path = library.path(version["preview_file"]) if version["preview_file"] else None
        if path is None or not path.is_file():
            raise MissingRecord("此版本尚未生成 GLB 预览")
    except MissingRecord as exc:
        raise HTTPException(404, str(exc)) from exc
    return FileResponse(path, media_type="model/gltf-binary", headers={"Cache-Control": "no-store"})


@router.get("/runs")
def runs():
    with workspace().db.connect() as db:
        return [record(row) for row in db.execute(
            """SELECT r.*, a.asset_id, a.name asset_name FROM runs r
               JOIN versions v ON r.asset_version_id = v.version_id
               JOIN assets a ON v.asset_id = a.asset_id
               ORDER BY r.status IN ('RUNNING','PENDING') DESC, r.created_at DESC LIMIT 200""")]


@router.get("/runs/{run_id}")
def run(run_id: str):
    return action("run", run_id)


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: str):
    return action("cancel", run_id)


@router.post("/runs/{run_id}/retry", status_code=202)
def retry(run_id: str):
    return action("retry", run_id)


@router.get("/runs/{run_id}/download")
def download(run_id: str):
    path = action("export_file", run_id)
    if not path.is_file():
        raise HTTPException(404, "导出文件已移除")
    return FileResponse(path, media_type="application/zip", filename=f"assetgate-{run_id[:8]}.zip")


@router.get("/runs/{run_id}/logs", response_class=PlainTextResponse)
def logs(run_id: str):
    row = action("run", run_id)
    folder = workspace().path(f"jobs/{row['run_id']}/logs")
    contents = [f"[{path.name}]\n{tail(path, limit=20000)}"
                for path in sorted(folder.glob("*.log")) if path.is_file()]
    return "\n\n".join(contents) or "暂无 Blender 子进程日志。"
