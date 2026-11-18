"""Collect public art pull reviews separately from issue duration metrics."""
from contextlib import closing
import json
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from artpipe.catalog import Gitea, LABEL, connect  # noqa: E402
from artpipe.precheck import UPSTREAM  # noqa: E402
from artpipe.radar import NAMES, baseline, validate  # noqa: E402


def main():
    spec = yaml.safe_load((ROOT / "configs/precheck.yaml").read_text())
    api = Gitea(ROOT / "data/api_cache", spec["io"])
    pulls = api.pages("/issues", type="pulls", state="all", labels=LABEL)
    findings = []
    counts = {"pulls": len(pulls), "issue_comments": 0, "reviews": 0, "inline_comments": 0}
    for pull in pulls:
        number = pull["number"]
        source = f"{UPSTREAM}/pulls/{number}"
        comments = api.pages(f"/issues/{number}/comments")
        counts["issue_comments"] += len(comments)
        reviews = api.pages(f"/pulls/{number}/reviews")
        counts["reviews"] += len(reviews)
        notes = [{"id": row["id"], "body": row["body"], "created_at": row["created_at"],
                  "url": f"{source}#issuecomment-{row['id']}"} for row in comments]
        for review in reviews:
            when = review.get("submitted_at") or review.get("created_at")
            if review.get("body") and when:
                notes.append({"id": -review["id"], "body": review["body"], "created_at": when,
                              "url": review.get("html_url") or source})
            if review.get("comments_count", 0):
                inline = api.pages(f"/pulls/{number}/reviews/{review['id']}/comments")
                counts["inline_comments"] += len(inline)
                notes.extend({"id": row["id"], "body": row["body"], "created_at": row["created_at"],
                              "url": row.get("html_url") or source} for row in inline)
        evidence, _ = validate(baseline(notes, spec["radar"]), notes)
        findings.extend((number, item) for item in evidence)
    summary = ["# 美术 PR 评审样本", "",
               f"美术标签 PR {counts['pulls']} 个，普通评论 {counts['issue_comments']} 条，"
               f"评审 {counts['reviews']} 条，行内评论 {counts['inline_comments']} 条。",
               "关键词匹配只用于核对协作风险。PR 样本单独保留，Issue 关闭时长与里程碑回测使用 Issue 数据。", ""]
    for number, item in findings:
        summary.append(f"- #{number} · {NAMES[item.type]} · {item.quote} [原文]({item.url})")
    (ROOT / "eval/pull-reviews.md").write_text("\n".join(summary).rstrip() + "\n", encoding="utf-8")
    print(json.dumps({**counts, "verified_findings": len(findings)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
