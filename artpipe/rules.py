"""Deterministic rules with file-level and line-level evidence."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from collections import Counter
from typing import Callable
from xml.parsers import expat
import re
import struct

XML_DIRS = ("actors/", "variants/")
REF_PREFIX = {"mesh": "meshes/", "texture": "textures/skins/", "prop": "actors/", "variant": "variants/"}
REF_ATTRIBUTE = {"texture": "file", "prop": "actor", "variant": "file"}
RANK_EXPERT = re.compile(r"_e_[a-z]+\.xml$")
RANK_LOWER = re.compile(r"_(?:a|b)_[a-z]+\.xml$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True, order=True)
class Finding:
    rule: str
    path: str
    severity: str
    evidence: str
    fix: str
    line: int | None = None
    target: str | None = None

    def identity(self) -> tuple[str, str, str | None]:
        return self.rule, self.path, self.target


@dataclass(frozen=True)
class Reference:
    kind: str
    target: str
    line: int


@dataclass(frozen=True)
class XmlDocument:
    references: tuple[Reference, ...]
    error: str | None = None
    error_line: int | None = None


def is_art_xml(path: str) -> bool:
    return path.startswith(XML_DIRS) and path.endswith(".xml")


def parse_xml(content: bytes) -> XmlDocument:
    """Extract structured paths with exact lines and disable entity declarations."""
    parser = expat.ParserCreate()
    references = []
    mesh = None

    def start(name, attrs):
        nonlocal mesh
        if name == "mesh":
            mesh = (parser.CurrentLineNumber, [])
        attribute = REF_ATTRIBUTE.get(name)
        value = attrs.get(attribute) if attribute else None
        if value and value.strip():
            references.append(Reference(name, REF_PREFIX[name] + value.strip(), parser.CurrentLineNumber))

    def characters(text):
        if mesh is not None:
            mesh[1].append(text)

    def end(name):
        nonlocal mesh
        if name == "mesh" and mesh is not None:
            value = "".join(mesh[1]).strip()
            if value:
                references.append(Reference("mesh", REF_PREFIX["mesh"] + value, mesh[0]))
            mesh = None

    def reject_doctype(*_):
        raise ValueError("DOCTYPE is not supported")

    parser.StartElementHandler = start
    parser.CharacterDataHandler = characters
    parser.EndElementHandler = end
    parser.StartDoctypeDeclHandler = reject_doctype
    try:
        parser.Parse(content, True)
    except (expat.ExpatError, ValueError) as exc:
        return XmlDocument((), str(exc), parser.ErrorLineNumber or parser.CurrentLineNumber)
    return XmlDocument(tuple(references))


def texture_pair(path: str) -> tuple[str, str] | None:
    if path.startswith("textures/") and path.endswith((".png", ".dds")):
        stem = path[:-4]
        return stem + ".png", stem + ".dds"
    return None


def inspect_file(path: str, tree: dict[str, str], enabled: set[str], spec: dict,
                 xml: XmlDocument | None = None) -> list[Finding]:
    results = []
    severity = spec["rules"]

    def add(rule, evidence, fix, line=None, target=None):
        results.append(Finding(rule, path, severity[rule], evidence, fix, line, target))

    pair = texture_pair(path)
    if "R1" in enabled and pair and path == pair[0] and pair[1] in tree:
        add("R1", f"同时存在 {pair[0]} 和 {pair[1]}", "确认引用后保留一种贴图格式", target=pair[1])
    if "R6" in enabled:
        extension = PurePosixPath(path).suffix
        if not re.fullmatch(spec["allowed_name"], path) or extension not in spec["allowed_extensions"]:
            add("R6", "文件路径字符或扩展名不符合项目规范", "按项目规范重命名并同步所有引用")
    if xml is None:
        return results
    if xml.error and "R5" in enabled:
        add("R5", f"XML 无法解析：{xml.error}", "修正 XML 后重新预检", xml.error_line)
    expert = path.startswith("actors/units/") and RANK_EXPERT.search(path)
    for ref in xml.references:
        if ("R2" in enabled and expert and ref.kind == "prop"
                and ref.target.startswith("actors/units/") and RANK_LOWER.search(ref.target)):
            add("R2", f"专家级单位引用了较低等级的部件 {ref.target}",
                "确认该变体使用同等级部件", ref.line, ref.target)
        if "R5" in enabled and ref.target not in tree:
            add("R5", f"{ref.kind} 目标不存在：{ref.target}", "补充目标文件或修正引用路径", ref.line, ref.target)
    return results


def read_image_header(path: str, content: bytes) -> tuple[int, int]:
    if path.endswith(".png") and content.startswith(PNG_SIGNATURE) and len(content) >= 33:
        if content[8:16] == b"\x00\x00\x00\x0dIHDR":
            return struct.unpack(">II", content[16:24])
    if path.endswith(".dds") and content.startswith(b"DDS ") and len(content) >= 128:
        size, _, height, width = struct.unpack("<IIII", content[4:20])
        if size == 124:
            return width, height
    raise ValueError("无法读取 PNG/DDS 尺寸")


def png_metadata(content: bytes) -> Counter:
    if not content.startswith(PNG_SIGNATURE):
        raise ValueError("无效的 PNG 文件签名")
    counts = Counter()
    offset = len(PNG_SIGNATURE)
    while offset + 12 <= len(content):
        length, kind = struct.unpack(">I4s", content[offset:offset + 8])
        offset += 12 + length
        if offset > len(content):
            break
        counts[kind] += 1
        if kind == b"IEND":
            return counts
    raise ValueError("PNG 数据缺失或未找到 IEND")


def inspect_binary(path: str, enabled: set[str], spec: dict,
                   load: Callable[[str, bool], bytes]) -> list[Finding]:
    metadata = "R3" in enabled and path.startswith("textures/") and path.endswith(".png")
    dimensions = "R4" in enabled and path.startswith("textures/") and path.endswith((".png", ".dds"))
    if not metadata and not dimensions:
        return []
    content = load(path, metadata)
    results = []
    if metadata:
        chunks = png_metadata(content)
        if (chunks[b"sRGB"] and chunks[b"iCCP"]) or chunks[b"iCCP"] > 1:
            results.append(Finding("R3", path, spec["rules"]["R3"],
                                   f"sRGB × {chunks[b'sRGB']} / iCCP × {chunks[b'iCCP']}",
                                   "导出 PNG 时保留一组一致的色彩配置"))
    if dimensions:
        width, height = read_image_header(path, content)
        if any(size <= 0 or size & (size - 1) for size in (width, height)):
            severity = "block" if path.startswith(tuple(spec["r4_block_prefixes"])) else spec["rules"]["R4"]
            results.append(Finding("R4", path, severity, f"宽高为 {width} × {height}",
                                   "按目录用途调整尺寸，UI 资产可人工复核"))
    return results
