"""Backtest a freeze-date snapshot with comments available at the decision time."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artpipe.catalog import Gitea, connect  # noqa: E402
from artpipe.radar import baseline, comments_for, validate  # noqa: E402


def happened_at(value):
    return datetime.fromisoformat(value)


def timeline_snapshot(issue, timeline, cutoff):
    priority = set(json.loads(issue["labels"]))
    milestone = issue["milestone_id"]
    opened = issue["state"] == "open"
    future = sorted((item for item in timeline if happened_at(item["created_at"]) > cutoff),
                    key=lambda row: (happened_at(row["created_at"]), row["id"]), reverse=True)
    for row in future:
        kind = row["type"]
        if kind == "milestone":
            milestone = (row.get("old_milestone") or {}).get("id")
        elif kind in {"close", "reopen"}:
            opened = kind == "close"
        elif kind == "label" and row.get("label"):
            label = row["label"]["name"]
            if row["body"] == "1":
                priority.discard(label)
            elif row["body"] in {"", "0"}:
                priority.add(label)
    modified = happened_at(issue["updated_at"]) > cutoff
    has_milestone_history = any(row["type"] == "milestone" for row in timeline)
    reliable = not modified or has_milestone_history
    return opened, milestone, priority, reliable


def report(db, api, spec, title, freeze_days):
    release = db.execute("SELECT * FROM milestone WHERE title = ?", (title,)).fetchone()
    if release is None or not release["closed_at"] or not release["due_on"]:
        raise ValueError("里程碑需要有最终计划和实际关闭日期。")
    due = happened_at(release["due_on"])
    closed = happened_at(release["closed_at"])
    cutoff = closed - timedelta(days=freeze_days)
    collected = {row["issue_number"] for row in db.execute("SELECT issue_number FROM issue_detail")}
    potential = [row for row in db.execute("SELECT * FROM issue")
                 if happened_at(row["created_at"]) <= cutoff
                 and (not row["closed_at"] or happened_at(row["closed_at"]) > cutoff or row["state"] == "open")]
    cases = []
    excluded = {"missing": 0, "uncertain": 0}
    qualifying = set(spec["radar"]["priority_labels"])
    for issue in potential:
        number = issue["number"]
        if number not in collected:
            excluded["missing"] += 1
            continue
        timeline = api.pages(f"/issues/{number}/timeline")
        opened, milestone, priority, reliable = timeline_snapshot(issue, timeline, cutoff)
        if not reliable:
            excluded["uncertain"] += 1
            continue
        if not opened or milestone != release["id"] or not (priority & qualifying):
            continue
        visible = comments_for(db, number, cutoff)
        evidence, _ = validate(baseline(visible, spec["radar"]), visible)
        active = set()
        for event in evidence:
            if event.state == "resolved":
                active.discard(event.type)
            else:
                active.add(event.type)
        observed = [happened_at(row["created_at"]) for row in timeline if happened_at(row["created_at"]) <= cutoff]
        observed.extend(happened_at(row["created_at"]) for row in visible)
        stale_days = (cutoff - max(observed, default=happened_at(issue["created_at"]))).days
        moved = any(row["type"] == "milestone" and cutoff < happened_at(row["created_at"]) <= closed
                    and (row.get("old_milestone") or {}).get("id") == release["id"]
                    and (row.get("milestone") or {}).get("id") != release["id"] for row in timeline)
        late = not issue["closed_at"] or happened_at(issue["closed_at"]) > due
        cases.append({"number": number, "priority": sorted(priority & qualifying), "comments": len(visible),
                      "days_idle": stale_days, "active": sorted(active), "moved": moved, "late": late,
                      "outcome": moved or late, "alert": bool(active) or stale_days >= spec["radar"]["stale_days"]})
    cases.sort(key=lambda row: (-len(row["active"]), -row["days_idle"], row["number"]))
    return {"milestone": title, "cutoff": cutoff.isoformat(), "due": due.isoformat(), "closed": closed.isoformat(),
            "excluded": excluded, "cases": cases}


def markdown(data):
    cases = data["cases"]
    tp = sum(row["outcome"] and row["alert"] for row in cases)
    total_outcome = sum(row["outcome"] for row in cases)
    alerts = sum(row["alert"] for row in cases)
    rows = [f"# {data['milestone']} 冻结前回测", "",
            f"- 回看时点 {data['cutoff']}。只使用当时可见而且未在之后编辑的评论及当时已有的时间线。",
            f"- {len(cases)} 个当时开放的高优先级美术任务可回测，实际移出或晚于最终计划关闭 {total_outcome} 个。",
            f"- 缺少详情 {data['excluded']['missing']} 个，无法复原当时里程碑 {data['excluded']['uncertain']} 个，"
            "均未纳入。样本取自当前美术标签集合，迁移记录覆盖范围会影响结果。",
            f"- 证据与停滞规则命中 {alerts} 个，真阳性 {tp} 个。"
            + (f"精确率 {tp/alerts:.1%}。" if alerts else "精确率无分母。")
            + (f"召回率 {tp/total_outcome:.1%}。" if total_outcome else "召回率无分母。"),
            "", "| Issue | 冻结前评论 | 停滞天数 | 当时风险 | 后来移出 | 晚于最终计划关闭 |",
            "| --- | ---: | ---: | --- | --- | --- |"]
    for row in cases:
        link = f"[#{row['number']}](https://gitea.wildfiregames.com/0ad/0ad/issues/{row['number']})"
        rows.append(f"| {link} | {row['comments']} | {row['days_idle']} | {', '.join(row['active']) or '—'} | "
                    f"{'是' if row['moved'] else '否'} | {'是' if row['late'] else '否'} |")
    return "\n".join(rows) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--milestone", default="Release 28")
    parser.add_argument("--freeze-days", default=28, type=int)
    parser.add_argument("--output", type=Path, default=ROOT / "eval/milestone-backtest.md")
    args = parser.parse_args()
    spec = yaml.safe_load((ROOT / "configs/precheck.yaml").read_text())
    with closing(connect(ROOT / "data/artpipe.sqlite")) as db:
        data = report(db, Gitea(ROOT / "data/api_cache", spec["io"], offline=True), spec,
                      args.milestone, args.freeze_days)
    args.output.write_text(markdown(data), encoding="utf-8")
    args.output.with_suffix(".json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                                      encoding="utf-8")


if __name__ == "__main__":
    main()
