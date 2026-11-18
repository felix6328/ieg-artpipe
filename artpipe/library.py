"""A bounded public mesh library for reuse, previews and content checks."""
from __future__ import annotations

from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
import json
import math
import re
from typing import Callable

from .git_source import GitSource
from .precheck import MediaCache

HAN = re.compile(r"(^|[/_.])han(?=[/_\.])")
SIEGE = re.compile(r"(^|[/_.])(siege|ram|battering|catapult|ballista|scorpio|archer_tower|trebuchet)(?=[/_.])")


@dataclass
class Asset:
    path: str
    oid: str
    category: str
    triangles: int
    uv_density_ratio: float | None
    thumbnail: str
    source: str = "0ad"
    license: str = "CC BY-SA 3.0"


def candidates(tree: dict[str, str], limit: int) -> list[tuple[str, str]]:
    special: dict[str, list[str]] = defaultdict(list)
    structural: dict[str, deque] = defaultdict(deque)
    for path in sorted(tree):
        if not path.startswith("meshes/") or not path.endswith(".dae"):
            continue
        if HAN.search(path):
            special["han"].append(path)
        elif SIEGE.search(path):
            special["siege"].append(path)
        elif path.startswith(("meshes/structural/", "meshes/props/structural/")):
            civ = PurePosixPath(path).name.partition("_")[0]
            structural[civ].append(path)
    ordered = [(path, name) for name in ("han", "siege") for path in special[name]]
    groups = deque(structural[key] for key in sorted(structural))
    while groups and len(ordered) < limit:
        group = groups.popleft()
        ordered.append((group.popleft(), "structure"))
        if group:
            groups.append(group)
    return ordered[:limit]


def extract_mesh(content: bytes):
    import collada
    from collada.common import DaeBrokenRefError, DaeUnsupportedError
    import numpy as np

    model = collada.Collada(BytesIO(content), ignore=[DaeUnsupportedError, DaeBrokenRefError], aux_file_loader=lambda path: b"")
    bound = list(model.scene.objects("geometry")) if model.scene else []
    geometries = bound or model.geometries
    patches = []
    density = []
    for geometry in geometries:
        primitives = geometry.primitives() if callable(geometry.primitives) else geometry.primitives
        for primitive in primitives:
            if hasattr(primitive, "triangleset"):
                primitive = primitive.triangleset()
            indices = getattr(primitive, "vertex_index", None)
            if indices is None or indices.ndim != 2 or indices.shape[1] != 3:
                continue
            triangles = np.asarray(primitive.vertex[indices], dtype=np.float32)
            if triangles.size and np.isfinite(triangles).all():
                patches.append(triangles)
            if not primitive.texcoordset:
                continue
            uv = primitive.texcoordset[0][primitive.texcoord_indexset[0]]
            world_edges = triangles[:, 1:] - triangles[:, :1]
            uv_edges = uv[:, 1:] - uv[:, :1]
            world_area = np.linalg.norm(np.cross(world_edges[:, 0], world_edges[:, 1]), axis=-1)
            uv_area = np.abs(uv_edges[:, 0, 0]*uv_edges[:, 1, 1] - uv_edges[:, 0, 1]*uv_edges[:, 1, 0])
            usable = (world_area > 1e-9) & (uv_area > 1e-10) & np.isfinite(world_area) & np.isfinite(uv_area)
            density.extend(np.sqrt(uv_area[usable] / world_area[usable]).tolist())
    if not patches:
        raise ValueError("DAE 文件未发现可渲染三角面")
    ratio = None
    if len(density) >= 12:
        p10, p90 = np.percentile(density, [10, 90])
        ratio = float(p90 / p10) if p10 > 0 else None
    up = getattr(model.assetInfo.upaxis, "value", model.assetInfo.upaxis)
    return np.concatenate(patches, axis=0), ratio, up


def thumbnail(triangles, up: str, path: Path, size: int = 256) -> None:
    import numpy as np
    from PIL import Image, ImageDraw

    if up == "Y_UP":
        triangles = triangles[:, :, [0, 2, 1]]
        triangles[:, :, 1] *= -1
    elif up == "X_UP":
        triangles = triangles[:, :, [1, 2, 0]]
    right = np.asarray([1.0, -1.0, 0.0]) / math.sqrt(2)
    depth = np.asarray([0.58, 0.58, 0.57])
    vertical = np.cross(depth, right)
    if vertical[2] < 0:
        vertical *= -1
    projected = np.stack((triangles @ right, -(triangles @ vertical)), axis=-1)
    min_xy = projected.min(axis=(0, 1))
    max_xy = projected.max(axis=(0, 1))
    scale = (size * 0.8) / max(float((max_xy-min_xy).max()), 1e-9)
    points = ((projected - (min_xy+max_xy)/2) * scale + size/2).astype(int)
    order = np.argsort((triangles @ depth).mean(axis=1))
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    length = np.maximum(np.linalg.norm(normals, axis=-1), 1e-7)
    light = np.abs((normals @ np.asarray([0.18, -0.38, 0.91])) / length)
    canvas = Image.new("RGB", (size, size), (242, 245, 238))
    painter = ImageDraw.Draw(canvas)
    for i in order:
        basic = 0.55 + light[i] * 0.40
        color = tuple(int(channel * basic) for channel in (133, 159, 142))
        painter.polygon([tuple(point) for point in points[i]], fill=color, outline=None)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path, format="PNG")


def build(source: GitSource, rev: str, spec: dict, data: Path, *, count: int, offline: bool,
          progress: Callable | None = None, workers: int = 4) -> dict:
    commit = source.revision(rev)
    tree = source.tree(commit)
    paths = candidates(tree, count)
    media = MediaCache(data / "blobs", commit, tree, spec["io"], offline)
    library = data / "library"
    library.mkdir(parents=True, exist_ok=True)
    index_path = library / "assets.json"
    cached = {}
    if index_path.is_file():
        cached = {item["path"]: item for item in json.loads(index_path.read_text(encoding="utf-8"))["assets"]}
    result = {"revision": commit, "requested": len(paths), "assets": [], "errors": []}
    def prepare(item):
        path, category = item
        oid = tree[path]
        preview = library / "thumbs" / f"{oid}.png"
        old = cached.get(path)
        try:
            if old and old["oid"] == oid and preview.is_file():
                return "assets", old
            content = media.load(path, True)
            triangles, uv_ratio, up = extract_mesh(content)
            thumbnail(triangles, up, preview)
            return "assets", asdict(Asset(path, oid, category, len(triangles), uv_ratio, preview.name))
        except Exception as exc:
            return "errors", {"path": path, "error": str(exc)[:250]}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, (bucket, item) in enumerate(pool.map(prepare, paths), 1):
            result[bucket].append(item)
            if index == len(paths) or index % 10 == 0 or index == 1:
                temporary = index_path.with_suffix(".tmp")
                temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(index_path)
                if progress:
                    progress(index, len(paths), len(result["assets"]), len(result["errors"]))
    return result
