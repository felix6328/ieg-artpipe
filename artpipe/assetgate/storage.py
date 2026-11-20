"""Immutable storage and validation for local model packages."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit
import json
import re
import shlex
import stat
import struct
import unicodedata
import zipfile
import zlib

MODELS = {".glb", ".gltf", ".fbx", ".obj"}
IMAGES = {".png", ".jpg", ".jpeg", ".jp2", ".webp", ".tif", ".tiff", ".tga", ".bmp", ".dds", ".exr", ".hdr", ".ktx2"}
DEPENDENCIES = IMAGES | {".bin", ".mtl", ".txt", ".md", ".json"}
IMAGE_MAPS = {"bump", "disp", "decal", "norm", "refl"}
FBX_MAGIC = b"Kaydara FBX Binary  \x00\x1a\x00"


class BadAsset(ValueError):
    """Input cannot be staged safely or does not have an accepted format."""


def confined(root: Path, name: str) -> Path:
    result = (root / name).resolve()
    if not result.is_relative_to(root.resolve()):
        raise BadAsset("文件路径超出资产存储范围")
    return result


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return sha256_stream(stream)


def sha256_stream(stream):
    checksum = sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        checksum.update(chunk)
    return checksum.hexdigest()


def copy_limited(stream, target: Path, limit: int):
    total = 0
    with target.open("xb") as output:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            total += len(chunk)
            if total > limit:
                raise BadAsset("文件超出配置的大小限制")
            output.write(chunk)
    if not total:
        raise BadAsset("文件为空")
    return total


def parts(name):
    path = PurePosixPath(name)
    raw = name.removesuffix("/").split("/")
    if (not name or path.is_absolute() or any(x in {"", ".", ".."} for x in raw)
            or re.search(r'[\\:\x00-\x1f<>|?*"]', name)
            or any(x.endswith((" ", ".")) for x in raw)):
        raise BadAsset("文件名或 ZIP 成员路径无效")
    return path


def unpack(archive, destination, limits):
    try:
        with zipfile.ZipFile(archive) as bundle:
            entries = bundle.infolist()
            if len(entries) > limits["max_members"] or sum(x.file_size for x in entries) > limits["unpacked_bytes"]:
                raise BadAsset("ZIP 超出成员数或解压大小限制")
            seen = {}
            extracted = 0
            for item in entries:
                path = parts(item.orig_filename)
                mode = stat.S_IFMT(item.external_attr >> 16)
                if mode not in (0, stat.S_IFREG, stat.S_IFDIR) or item.flag_bits & 1:
                    raise BadAsset("ZIP 包含链接、特殊文件或加密成员")
                if path.parts[0] == "__MACOSX" or path.name == ".DS_Store":
                    continue
                for prefix in (*reversed(path.parents[:-1]), path):
                    key = unicodedata.normalize("NFC", prefix.as_posix()).casefold()
                    if seen.setdefault(key, prefix) != prefix:
                        raise BadAsset("ZIP 包含大小写或 Unicode 重名路径")
                dest = confined(destination, str(path))
                if item.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                if path.suffix.lower() not in MODELS | DEPENDENCIES:
                    raise BadAsset(f"ZIP 成员类型不支持：{path.suffix}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not item.file_size:
                    dest.touch(exist_ok=False)
                    continue
                with bundle.open(item) as source:
                    extracted += copy_limited(source, dest, limits["unpacked_bytes"] - extracted)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, FileExistsError, NotADirectoryError,
            IsADirectoryError, RecursionError, EOFError, zlib.error) as exc:
        raise BadAsset("ZIP 无法读取或成员路径冲突") from exc


def gltf_document(model):
    try:
        with model.open("rb") as source:
            if model.suffix.lower() == ".glb":
                header = source.read(20)
                magic, version, length, json_size, kind = struct.unpack("<4sIII4s", header)
                if (magic != b"glTF" or version != 2 or kind != b"JSON"
                        or length != model.stat().st_size or json_size > length - 20):
                    raise BadAsset("GLB 文件头无效")
                doc = json.loads(source.read(json_size))
            else:
                doc = json.load(source)
        if not isinstance(doc, dict) or doc.get("asset", {}).get("version") != "2.0":
            raise BadAsset("需要 glTF 2.0 文件")
        return doc
    except (ValueError, TypeError, AttributeError, struct.error, RecursionError) as exc:
        if isinstance(exc, BadAsset):
            raise
        raise BadAsset("无法读取 GLB/glTF 文件结构") from exc


def dependency(model, root, raw, *, uri=False):
    if not isinstance(raw, str) or not raw.strip():
        raise BadAsset("模型包含无效的外部引用")
    if uri:
        url = urlsplit(raw)
        if url.scheme or url.netloc or url.query or url.fragment:
            raise BadAsset("模型引用必须使用资产包内相对路径")
        raw = unquote(url.path)
    else:
        raw = raw.replace("\\", "/")
    if raw.startswith("/") or re.search(r"[:\\\x00-\x1f]", raw):
        raise BadAsset("模型引用必须使用资产包内相对路径")
    result = (model.parent / raw).resolve()
    if not result.is_relative_to(root.resolve()):
        raise BadAsset("模型引用指向资产包外部")
    return result


def obj_references(model, root):
    mtl_paths = set()
    default = model.with_suffix(".mtl")
    if default.is_file():
        mtl_paths.add(default)
    with model.open(encoding="utf-8-sig", errors="replace") as stream:
        for line in stream:
            tokens = line.strip().split(maxsplit=1)
            if len(tokens) < 2 or tokens[0] != "mtllib":
                continue
            raw = tokens[1].split(" #", 1)[0].strip()
            candidates = [raw]
            if not dependency(model, root, raw).is_file():
                try:
                    candidates.extend(shlex.split(raw.replace("\\", "/"), comments=True))
                except ValueError as exc:
                    raise BadAsset("MTL 文件引用无效") from exc
            for entry in dict.fromkeys(candidates if len(candidates) <= 1 else candidates[1:]):
                mtl_paths.add(dependency(model, root, entry))
    for mtl in sorted(mtl_paths):
        yield mtl
        if mtl.is_file():
            with mtl.open(encoding="utf-8-sig", errors="replace") as materials:
                for statement in materials:
                    statement = statement.strip().split(maxsplit=1)
                    if len(statement) == 2 and (statement[0].lower().startswith("map_")
                                                or statement[0].lower() in IMAGE_MAPS):
                        raw = map_path(statement[1])
                        yield dependency(mtl, root, raw)
                        if mtl.parent != model.parent:
                            # Blender's legacy import looks up maps from the OBJ directory.
                            dependency(model, root, raw)


def map_path(statement):
    # MTL options precede the filename. Numeric vector options accept one to three values.
    tokens = statement.split(" #", 1)[0].split()
    fixed = {"-blendu": 1, "-blendv": 1, "-cc": 1, "-clamp": 1, "-mm": 2,
             "-boost": 1, "-texres": 1, "-bm": 1, "-imfchan": 1, "-type": 1, "-colorspace": 1}
    while tokens and tokens[0].startswith("-"):
        option = tokens.pop(0).lower()
        if option in {"-o", "-s", "-t"}:
            for _ in range(3):
                if not tokens or not re.fullmatch(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?", tokens[0], re.I):
                    break
                tokens.pop(0)
        elif option in fixed:
            del tokens[:fixed[option]]
        else:
            raise BadAsset(f"不支持的 MTL 贴图参数：{option}")
    return " ".join(tokens).strip('"`')


def references(model, root):
    paths = set()
    suffix = model.suffix.lower()
    if suffix in {".gltf", ".glb"}:
        document = gltf_document(model)
        for group in ("buffers", "images"):
            values = document.get(group, [])
            if not isinstance(values, list) or not all(isinstance(item, dict) for item in values):
                raise BadAsset("glTF 引用表无效")
            for item in values:
                if "uri" in item:
                    raw = item["uri"]
                    if not isinstance(raw, str) or not raw.startswith("data:"):
                        paths.add(dependency(model, root, raw, uri=True))
    elif suffix == ".obj":
        paths.update(obj_references(model, root))
    return {
        "present": sorted(p.relative_to(root).as_posix() for p in paths if p.is_file()),
        "missing": sorted(p.relative_to(root).as_posix() for p in paths if not p.is_file()),
    }


def validate_model(model, root):
    suffix = model.suffix.lower()
    if suffix == ".fbx":
        with model.open("rb") as stream:
            header = stream.read(128)
        if not (header.startswith(FBX_MAGIC) or re.match(rb"\s*;\s*FBX", header, re.I)):
            raise BadAsset("FBX 文件头无效")
    if suffix == ".obj":
        with model.open("rb") as stream:
            if not any(re.match(rb"\s*(?:v[npt]?|o|g|f|mtllib|l)\s+", line) for line in stream):
                raise BadAsset("OBJ 缺少可识别的模型记录")
    return references(model, root)
