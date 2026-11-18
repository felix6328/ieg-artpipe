"""Verify the documented 0 A.D. cases against the recorded commits."""
from collections import defaultdict
from contextlib import closing
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import random
import statistics
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artpipe.catalog import connect  # noqa: E402
from artpipe.git_source import GitSource  # noqa: E402
from artpipe.metrics import milestones  # noqa: E402
from artpipe.precheck import CORE_RULES, check  # noqa: E402
from artpipe.radar import candidates, comments_for, make_card  # noqa: E402
from artpipe.rules import inspect_file  # noqa: E402

SNAPSHOT = "14b258b1026030c3c44e49e092a2771f3bff5245"
EXPECTED_DUPLICATES = {
    "textures/skins/gaia/bamboo.png",
    *(f"textures/skins/props/head/pers_face_{suffix}.png" for suffix in "abij"),
}
PORTRAIT = "textures/ui/session/portraits/units/kush_hero_arakamani.png"
ISSUES = {"6326", "6738", "7649"}


def main():
    spec = yaml.safe_load((ROOT / "configs/precheck.yaml").read_text())
    git = GitSource(ROOT / "data/0ad")
    hits = defaultdict(list)

    def examine(rev, rule, scope=""):
        report = check(git, rev, {rule}, spec, cache=ROOT / "data/blobs", scope=scope)
        assert not report.unavailable, report.unavailable
        hits[rule].extend((report.revision, item) for item in report.findings)
        return report

    before = examine("eafacb6e2^", "R1")
    assert {item.path for item in before.findings} == EXPECTED_DUPLICATES
    assert not examine("eafacb6e2", "R1").findings
    assert len(examine("0dd3bcc8e^", "R1").findings) == 13
    assert not examine(SNAPSHOT, "R1").findings
    before_rank = examine("3142b7cba^", "R2")
    assert len(before_rank.findings) == 2
    assert any("kushites/" in item.path for item in before_rank.findings)
    assert all("kushites/" not in item.path for item in examine("3142b7cba", "R2").findings)
    rank = examine(SNAPSHOT, "R2").findings
    assert len(rank) == 1 and rank[0].line == 47 and "achaemenids" in rank[0].path
    for path in ("textures/particles/hero_aura.png", "textures/skins/gaia/rice_paddy_norm.png"):
        assert len(examine(SNAPSHOT, "R3", path).findings) == 1
    non_pow2 = examine("7d180bcf1", "R4", PORTRAIT).findings
    assert len(non_pow2) == 1 and non_pow2[0].severity == "warn"
    assert not examine("2ec4abd03", "R4", PORTRAIT).findings
    reference_report = examine(SNAPSHOT, "R5")
    assert not reference_report.findings
    assert reference_report.references == {"mesh": 7362, "prop": 21447, "texture": 22747, "variant": 17567}
    replay = json.loads((ROOT / "data/replay.json").read_text())
    assert replay["revision"] == SNAPSHOT
    assert ISSUES <= {issue for row in replay["conditions"] for issue in row["issues"]}
    bamboo = next(row for row in replay["conditions"] if "6738" in row["issues"]
                  and row["finding"]["path"].endswith("bamboo.png"))
    assert "textures/skins/gaia/bamboo.png" not in git.tree(git.revision("89f6205d9"))
    assert "textures/skins/gaia/bamboo.dds" in git.tree(git.revision("89f6205d9"))
    assert bamboo["introduced_sha"].startswith("1a44e2790")
    for row in replay["conditions"]:
        item = row["finding"]
        hits[item["rule"]].append((row["introduced_sha"], item))
    with closing(connect(ROOT / "data/artpipe.sqlite")) as db:
        release_stats = milestones(db)
        expected_delays = dict(zip(("Alpha 21", "Alpha 22", "Alpha 23", "Alpha 24",
                                    "Alpha 25", "Alpha 26", "Alpha 27", "Release 28"),
                                   (43, 56, 287, 30, 62, 201, 5, 1)))
        assert expected_delays.items() <= {row["title"]: row["delay_days"] for row in release_stats["milestones"]}.items()
        issue = candidates(db, spec["radar"], number=8414)[0]
        comments = comments_for(db, 8414)
        card = make_card(issue, comments, spec["radar"], as_of=datetime.now(timezone.utc))
        by_id = {item["id"]: item for item in comments}
        assert {"dependency", "rework", "licensing", "duplicate_effort", "stalled"} <= {
            event.type for event in card.events}
        assert all(event.quote in by_id[event.comment_id]["body"] for event in card.events)
    rng = random.Random(731)
    names = sorted(git.tree(SNAPSHOT))
    latency = []
    for _ in range(20):
        report = check(git, SNAPSHOT, CORE_RULES, spec, cache=ROOT / "data/blobs",
                       offline=True, only_paths=set(rng.sample(names, 200)))
        assert report.scanned == 200
        latency.append(report.elapsed_ms)
    p95 = sorted(latency)[math.ceil(len(latency) * 0.95) - 1]
    lines = ["# 验收结果", "", f"0 A.D. 固定提交 `{SNAPSHOT}`。以下由脚本核验。", "",
             "- #6738 修复前 5 组，修复后 0 组。#6326 对应历史提交修复前 13 组。",
             "- #7649 修复前 2 处，指定问题修复后消失。固定提交仍有 1 处同类引用，报告定位到第 47 行。",
             "- #9156 的两张 PNG 分别命中色彩块规则。历史 UI 头像修复前提醒，修复后无命中。",
             f"- 当前版本引用完整性检查 {sum(reference_report.references.values()):,} 条，断引用 0 条。",
             f"- 回放 {replay['commits']:,} 次美术提交。竹子重复存在 {bamboo['days']:.1f} 天，"
             "开始时间以同名两种格式首次同时存在为准。",
             f"- #8414 {len(comments)} 条评论。风险历史、解除和停滞证据匹配原文。",
             f"- 已关闭美术事项 {release_stats['closed_art_issues']} 个。"
             f"里程碑实际延期值全部匹配审计用期望。",
             f"- 200 个文件的抽样批次运行 {len(latency)} 次，保留完整目录解析依赖，"
             f"中位耗时 {statistics.median(latency):.1f} ms，P95 {p95:.1f} ms。"
             "二进制下载与网络不计入本项。",
             "", "复核表保留抽样时的原始命中，以便追溯规则调整前的精确率。样本见 labels/precheck_review.csv。", ""]
    output = ROOT / "labels/precheck_review.csv"
    if not output.exists():
        with output.open("w", encoding="utf-8", newline="") as stream:
            csv_out = csv.writer(stream, lineterminator="\n")
            csv_out.writerow(("rule", "revision", "path", "line", "evidence", "verdict"))
            for rule, items in sorted(hits.items()):
                records = {}
                for rev, item in items:
                    row = item if isinstance(item, dict) else item.__dict__
                    records[(row["path"], row["target"])] = (rev, row)
                sample = rng.sample(list(records.values()), min(30, len(records)))
                for rev, row in sample:
                    csv_out.writerow((rule, rev, row["path"], row["line"], row["evidence"], "pending"))
    with output.open(encoding="utf-8-sig", newline="") as file:
        reviewed = list(csv.DictReader(file))
    lines += ["## 人工复核状态", "", "| 规则 | 已核对 | 全部样本 | 人工精确率 |", "| --- | ---: | ---: | ---: |"]
    for rule in sorted({item["rule"] for item in reviewed}):
        chosen = [item["verdict"] for item in reviewed if item["rule"] == rule]
        completed = [verdict for verdict in chosen if verdict in {"valid", "invalid"}]
        precision = f"{completed.count('valid')/len(completed):.1%}" if completed else "待复核"
        lines.append(f"| {rule} | {len(completed)} | {len(chosen)} | {precision} |")
    r6_review = [item for item in reviewed if item["rule"] == "R6"]
    retained = [item for item in r6_review if inspect_file(item["path"], {}, {"R6"}, spec)]
    old_false = sum(item["verdict"] == "invalid" for item in r6_review)
    new_false = sum(item["verdict"] == "invalid" for item in retained)
    removed_true = (sum(item["verdict"] == "valid" for item in r6_review)
                    - sum(item["verdict"] == "valid" for item in retained))
    if r6_review and all(item["verdict"] in {"valid", "invalid"} for item in r6_review):
        lines += ["", "## R6 命名规则修正", "",
                  "仅放行结构 AO 贴图目录及其子目录中的 `_AO.png` 命名。"
                  f"原复核样本回归中误报由 {old_false} 降至 {new_false}，移除的有效命中 {removed_true} 条。"
                  "样本曾用于定位规则问题，此处仅记录回归结果。"]
    (ROOT / "eval/acceptance.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"固定历史案例全部通过。200 文件批次 P95 {p95:.1f} ms。")


if __name__ == "__main__":
    main()
