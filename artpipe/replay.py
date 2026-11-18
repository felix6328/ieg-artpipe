"""Incrementally replay deterministic checks over the art history."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
import re
from time import monotonic

from .git_source import Change, GitSource
from .precheck import CORE_RULES, UPSTREAM
from .rules import Finding, XmlDocument, inspect_file, is_art_xml, parse_xml, texture_pair

ISSUE = re.compile(r"(?<!\w)#(\d+)")


@dataclass
class Life:
    finding: Finding
    introduced_sha: str
    introduced_at: str
    resolved_sha: str | None = None
    resolved_at: str | None = None
    issues: tuple[str, ...] = ()

    @property
    def days(self) -> float | None:
        if self.resolved_at is None:
            return None
        days = (datetime.fromisoformat(self.resolved_at) - datetime.fromisoformat(self.introduced_at))
        return round(days.total_seconds() / 86_400, 1)


@dataclass
class ReplayReport:
    revision: str
    commits: int
    conditions: list[Life]
    elapsed_s: float

    def json(self) -> dict:
        return {"revision": self.revision, "commits": self.commits, "elapsed_s": self.elapsed_s,
                "conditions": [dict(asdict(item), days=item.days) for item in self.conditions]}

    def markdown(self) -> str:
        resolved = [item for item in self.conditions if item.resolved_at]
        counts = Counter(item.finding.rule for item in self.conditions)
        fixed = Counter(item.finding.rule for item in resolved)
        rows = [
            "# 美术资产历史回放", "",
            f"- 截止版本 `{self.revision}`，读取涉及美术路径的 {self.commits:,} 个提交",
            f"- 回放耗时 {self.elapsed_s:.2f} 秒，包含 git 数据读取",
            "- 持续天数来自引入与修复提交时间，表示规则本可提前指出的时间。"
            "统计覆盖规则自身的命中，含未人工复核的结果。", "",
            "| 规则 | 引入次数 | 后续修复 | 仍命中 | 已修复累计持续天数 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
        for rule in sorted(CORE_RULES):
            days = sum(item.days or 0 for item in resolved if item.finding.rule == rule)
            rows.append(f"| {rule} | {counts[rule]} | {fixed[rule]} | {counts[rule]-fixed[rule]} | {days:,.1f} |")
        rows += ["", "## 有关联 Issue 的重复格式和部件等级案例", "",
                 "| 规则 | 文件 | 引入 | 修复 | 持续天数 | Issue |",
                 "| --- | --- | --- | --- | ---: | --- |"]
        for item in resolved:
            if item.finding.rule not in {"R1", "R2"} or not item.issues:
                continue
            links = ", ".join(f"[#{number}]({UPSTREAM}/issues/{number})" for number in item.issues)
            rows.append(f"| {item.finding.rule} | `{item.finding.path}` | "
                        f"{_commit_link(item.introduced_sha)} | {_commit_link(item.resolved_sha)} | {item.days} | {links} |")
        return "\n".join(rows) + "\n"


class Index:
    def __init__(self, spec: dict):
        self.spec = spec
        self.tree: dict[str, str] = {}
        self.parsed: dict[str, XmlDocument] = {}
        self.reverse: dict[str, set[str]] = defaultdict(set)
        self.active: dict[str, dict[tuple, Life]] = {}
        self.timeline: list[Life] = []

    def apply(self, changes: list[Change], sha: str, stamp: str, subject: str) -> None:
        affected = {change.path for change in changes}
        for change in changes:
            affected.update(self.reverse.get(change.path, ()))
            if pair := texture_pair(change.path):
                affected.update(pair)
            if not is_art_xml(change.path) or not change.old:
                continue
            for target in {ref.target for ref in self.parsed[change.old].references}:
                self.reverse[target].discard(change.path)
                if not self.reverse[target]:
                    del self.reverse[target]
        for change in changes:
            if change.new is not None:
                self.tree[change.path] = change.new
                if is_art_xml(change.path):
                    for ref in self.parsed[change.new].references:
                        self.reverse[ref.target].add(change.path)
            else:
                self.tree.pop(change.path, None)
        ticket_ids = tuple(dict.fromkeys(ISSUE.findall(subject)))
        for path in sorted(affected):
            oid = self.tree.get(path)
            prior = self.active.pop(path, {})
            current = {}
            if oid:
                document = self.parsed[oid] if is_art_xml(path) else None
                for finding in inspect_file(path, self.tree, CORE_RULES, self.spec, document):
                    identity = finding.identity()
                    if identity in current:
                        continue
                    life = prior.pop(identity, None)
                    if life is None:
                        life = Life(finding, sha, stamp, issues=ticket_ids)
                        self.timeline.append(life)
                    current[identity] = life
            for life in prior.values():
                life.resolved_sha, life.resolved_at = sha, stamp
                life.issues = tuple(dict.fromkeys((*life.issues, *ticket_ids)))
            if current:
                self.active[path] = current


def replay(source: GitSource, rev: str, spec: dict) -> ReplayReport:
    start = monotonic()
    target = source.revision(rev)
    log = source.history(target)
    index = Index(spec)
    previous = None
    batch_size = 400
    for start_at in range(0, len(log), batch_size):
        batch = []
        missing = set()
        for sha, _, stamp, subject in log[start_at:start_at + batch_size]:
            changes = (source.changes(previous, sha) if previous else
                       [Change(path, None, oid) for path, oid in source.tree(sha).items()])
            previous = sha
            batch.append((changes, sha, stamp, subject))
            missing.update(change.new for change in changes
                           if is_art_xml(change.path) and change.new and change.new not in index.parsed)
        index.parsed.update((oid, parse_xml(blob)) for oid, blob in source.blobs(missing).items())
        for changes, sha, stamp, subject in batch:
            index.apply(changes, sha, stamp, subject)
    if index.tree != source.tree(target):
        raise ValueError("回放后的美术目录与目标提交不一致")
    return ReplayReport(target, len(log), index.timeline, monotonic() - start)


def _commit_link(sha: str) -> str:
    return f"[`{sha[:9]}`]({UPSTREAM}/commit/{sha})"
