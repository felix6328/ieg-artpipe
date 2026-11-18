"""Check one revision, or the files and dependants affected by a submission."""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from time import monotonic, sleep
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from .git_source import ART, GitSource
from .rules import Finding, inspect_binary, inspect_file, is_art_xml, parse_xml, texture_pair

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "https://gitea.wildfiregames.com/0ad/0ad"
CORE_RULES = frozenset({"R1", "R2", "R5", "R6"})


@dataclass
class Report:
    revision: str
    base: str | None
    assets: int
    scanned: int
    rules: list[str]
    references: dict[str, int]
    findings: list[Finding]
    unavailable: list[tuple[str, str]]
    elapsed_ms: float

    def json(self) -> dict:
        return asdict(self)

    def markdown(self) -> str:
        rows = [
            "# 美术资产入库预检", "",
            f"- 版本 `{self.revision}`" + (f"，基准 `{self.base}`" if self.base else ""),
            f"- 资产 {self.assets:,} 个，检查 {self.scanned:,} 个文件，用时 {self.elapsed_ms:.1f} ms",
            f"- 规则 {', '.join(self.rules)}",
            "- 引用计数 " + (", ".join(f"{key} {n:,}" for key, n in self.references.items()) or "本次未扫描 XML 引用"),
            f"- 拦截 {sum(item.severity == 'block' for item in self.findings)} 项，"
            f"提醒 {sum(item.severity == 'warn' for item in self.findings)} 项，"
            f"待人工核对 {len(self.unavailable)} 项",
            "", "| 规则 | 严重级别 | 路径 | 行号 | 证据 | 建议 |",
            "| --- | --- | --- | ---: | --- | --- |",
        ]
        for finding in self.findings:
            cells = [finding.rule, finding.severity, finding.path, str(finding.line or ""),
                     finding.evidence, finding.fix]
            rows.append("| " + " | ".join(cell.replace("|", "\\|").replace("\n", " ") for cell in cells) + " |")
        if self.unavailable:
            rows.extend(["", "## 工具失败，待人工核对", ""])
            rows.extend(f"- `{path}`：{reason}" for path, reason in self.unavailable)
        return "\n".join(rows) + "\n"


class MediaCache:
    def __init__(self, root: Path, revision: str, tree: dict[str, str], io: dict, offline: bool):
        self.root, self.revision, self.tree = root, revision, tree
        self.offline = offline
        self.limit = io["binary_cache_limit_bytes"]
        self.timeout = io["timeout_seconds"]
        self.interval = 1 / io["requests_per_second"]
        self.used = sum(path.stat().st_size for path in root.glob("*") if path.is_file())
        self.next_request = 0.0
        self.lock = Lock()

    def load(self, path: str, full: bool) -> bytes:
        oid = self.tree[path]
        complete = self.root / f"{oid}.full"
        header = self.root / f"{oid}.header"
        hit = complete if complete.is_file() or full else header
        if hit.is_file():
            if full:
                return hit.read_bytes()
            with hit.open("rb") as stream:
                return stream.read(128)
        if self.offline:
            raise ValueError("离线缓存中没有所需的美术文件")
        url = f"{UPSTREAM}/media/commit/{self.revision}/{ART}/{quote(path)}"
        request = Request(url, headers={} if full else {"Range": "bytes=0-127"})
        for attempt in range(3):
            with self.lock:
                sleep(max(0.0, self.next_request - monotonic()))
                self.next_request = monotonic() + self.interval
                remaining = self.limit - self.used
            try:
                with urlopen(request, timeout=self.timeout) as response:
                    if remaining <= 0:
                        raise ValueError("美术文件缓存已达到容量上限")
                    data = response.read(remaining + 1 if full else min(128, remaining + 1))
                if len(data) > remaining:
                    raise ValueError("美术文件缓存已达到容量上限")
                if data.startswith(b"version https://git-lfs.github.com/spec/"):
                    raise ValueError("上游返回的是 Git LFS 指针")
                with self.lock:
                    if not hit.is_file():
                        if self.used + len(data) > self.limit:
                            raise ValueError("美术文件缓存已达到容量上限")
                        self.root.mkdir(parents=True, exist_ok=True)
                        temporary = hit.with_suffix(hit.suffix + ".tmp")
                        temporary.write_bytes(data)
                        temporary.replace(hit)
                        self.used += len(data)
                return data
            except HTTPError as exc:
                if attempt == 2 or exc.code not in {429, 500, 502, 503, 504}:
                    raise
            except URLError:
                if attempt == 2:
                    raise
            sleep(2**attempt)
        raise RuntimeError("Unreachable after the retry loop")


def check(source: GitSource, revision: str, enabled: set[str], spec: dict, *,
          cache: Path, offline: bool = False, base: str | None = None, scope: str = "",
          only_paths: set[str] | None = None) -> Report:
    start = monotonic()
    head = source.revision(revision)
    base = source.revision(base) if base else None
    tree = source.tree(head)
    changes = {change.path for change in source.changes(base, head)} if base else set()
    scope = scope.removeprefix(ART + "/").removeprefix("art/").rstrip("/")
    if scope and not any(path == scope or path.startswith(scope + "/") for path in tree.keys() | changes):
        raise ValueError(f"该版本与变更中均无指定路径：{scope}")
    selected = set(tree) if base is None else changes & tree.keys()
    if "R1" in enabled:
        for changed in tuple(selected | changes):
            if pair := texture_pair(changed):
                selected.update(set(pair) & tree.keys())

    if only_paths is not None and base is None:
        selected.intersection_update(only_paths)
    documents = {}
    if enabled & {"R2", "R5"}:
        xml_paths = [path for path in tree if is_art_xml(path) and
                     ((base and "R5" in enabled) or path in selected)]
        blobs = source.blobs({tree[path] for path in xml_paths})
        parsed = {}
        for path in xml_paths:
            oid = tree[path]
            if oid not in parsed:
                parsed[oid] = parse_xml(blobs[oid])
            document = documents[path] = parsed[oid]
            if base and any(ref.target in changes for ref in document.references):
                selected.add(path)

    if only_paths is not None:
        selected.intersection_update(only_paths)
    if scope:
        selected = {path for path in selected if path == scope or path.startswith(scope + "/")
                    or (texture_pair(path) and scope in texture_pair(path))}
    findings = []
    counts = Counter()
    unavailable = []
    media = MediaCache(cache, head, tree, spec["io"], offline)
    for path in sorted(selected):
        document = documents.get(path)
        if document:
            counts.update(ref.kind for ref in document.references)
        findings.extend(inspect_file(path, tree, enabled, spec, document))
        if enabled & {"R3", "R4"}:
            try:
                findings.extend(inspect_binary(path, enabled, spec, media.load))
            except (OSError, ValueError) as exc:
                unavailable.append((path, str(exc)))
    return Report(head, base, len(tree), len(selected), sorted(enabled), dict(sorted(counts.items())),
                  findings, unavailable, (monotonic() - start) * 1000)
