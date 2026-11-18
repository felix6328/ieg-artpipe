"""Compare keyword and model extraction with an auditable comment review sample."""
from __future__ import annotations

import argparse
from contextlib import closing
import csv
import json
from pathlib import Path
import random
import re
import sqlite3
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from artpipe.catalog import connect  # noqa: E402
from artpipe.radar import RadarModel, TYPES, baseline, validate  # noqa: E402

NEAR_MISS = re.compile(r"\b(already|resolved|waiting|issue|fixed|licen[cs]e|texture)\b", re.I)
STATS = ROOT / "eval/radar.json"


def select(db: sqlite3.Connection, options: dict, size: int = 60) -> list[sqlite3.Row]:
    rows = list(db.execute("SELECT * FROM comment WHERE body != '' ORDER BY id"))
    rng = random.Random(8414)
    rng.shuffle(rows)
    predicted, near, random_rows = [], [], []
    for comment in rows:
        if baseline([comment], options):
            predicted.append(comment)
        elif NEAR_MISS.search(comment["body"]):
            near.append(comment)
        else:
            random_rows.append(comment)
    selected = predicted[:size // 3] + near[:size // 3]
    selected.extend(random_rows[:size - len(selected)])
    if len(selected) != size:
        raise ValueError("可供复核的评论不足")
    rng.shuffle(selected)
    return selected


def by_comment(items):
    index = {}
    for item in items:
        if item.state == "raised":
            index.setdefault(item.comment_id, set()).add(item.type)
    return index


def write_labels(path, rows, options):
    if path.exists():
        raise ValueError("复核文件已存在，请使用 --labels 指定另一个路径")
    labeler = RadarModel({**options, "model": "Qwen/Qwen3.5-27B", "batch_comments": 16,
                          "token_cost_cny_per_million": {"input": 1, "output": 4}},
                         ROOT / "data/review_cache")
    raw = labeler.extract("Independent art-production comments sampled from different issues. "
                          "Judge each as independent evidence.", rows)
    evidence, rejected = validate(raw, rows, extractor="provisional")
    labels = by_comment(evidence)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv_out = csv.writer(stream, lineterminator="\n")
        csv_out.writerow(("comment_id", "issue", "source_url", "labels", "review_status"))
        for row in rows:
            cid = row["id"]
            csv_out.writerow((cid, row["issue_number"], row["url"], "|".join(sorted(labels.get(cid, ()))),
                              "provisional"))
    return {"model": labeler.model, "cost_cny": labeler.usage, "rejected_quotes": rejected}


def compare(targets, result):
    tp = sum(len(targets[cid] & result.get(cid, set())) for cid in targets)
    fp = sum(len(result.get(cid, set()) - targets[cid]) for cid in targets)
    fn = sum(len(targets[cid] - result.get(cid, set())) for cid in targets)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall}


def fmt(value):
    return "—" if value is None else f"{value:.1%}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--labels", type=Path, default=ROOT / "labels/radar_labels.csv")
    args = parser.parse_args()
    options = yaml.safe_load((ROOT / "configs/precheck.yaml").read_text())["radar"]
    label_run = None
    with closing(connect(ROOT / "data/artpipe.sqlite")) as db:
        if args.prepare:
            label_run = write_labels(args.labels, select(db, options), options)
        with args.labels.open(encoding="utf-8-sig", newline="") as stream:
            labels = list(csv.DictReader(stream))
        ids = [int(row["comment_id"]) for row in labels]
        if len(set(ids)) != len(ids):
            raise ValueError("标签文件包含重复评论")
        rows = []
        for cid in ids:
            row = db.execute("SELECT * FROM comment WHERE id = ?", (cid,)).fetchone()
            if row is None:
                raise ValueError(f"评论 #{cid} 未导入")
            rows.append(row)
    if any(row["review_status"] not in {"human", "provisional"} for row in labels):
        raise ValueError("review_status 应为 human 或 provisional")
    targets = {int(row["comment_id"]): set(filter(None, map(str.strip, row["labels"].split("|"))))
               for row in labels}
    if any(not value <= set(TYPES) for value in targets.values()):
        raise ValueError("标签文件包含未知事件类型")
    model = RadarModel(options, ROOT / "data/llm_cache")
    raw = model.extract("Independent sampled 0 A.D. art comments. Do not combine commenters across issues.", rows)
    evidence, rejected = validate(raw, rows, extractor="model")
    keyword, _ = validate(baseline(rows, options), rows)
    predictions = {"关键词": by_comment(keyword), "LLM": by_comment(evidence),
                   "并集": by_comment(keyword + evidence)}
    scored = {key: compare(targets, values) for key, values in predictions.items()}
    human_targets = {int(row["comment_id"]): targets[int(row["comment_id"])]
                     for row in labels if row["review_status"] == "human"}
    reviewed = len(human_targets)
    human = {key: compare(human_targets, values) for key, values in predictions.items()} if reviewed else {}
    rejected_rate = rejected / len(raw) if raw else None
    cost_per_100 = model.usage * 100 / len(labels) if labels else 0
    data = {"comments": len(labels), "human_reviewed": reviewed, "model_candidates": len(raw),
            "rejected_quotes": rejected, "quote_validation_rejection_rate": rejected_rate,
            "model_calls": model.billed, "model_cache_hits": model.cache_hits, "estimated_cost_cny": model.usage,
            "estimated_cost_per_100_comments_cny": cost_per_100, "methods": scored, "human_methods": human}
    if label_run:
        data["label_generation"] = label_run
    STATS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output = ["# 阻塞雷达评测", "",
              f"{len(labels)} 条公开评论。{len(labels)-reviewed} 条 provisional，{reviewed} 条人工复核。",
              "样本包含关键词候选、容易误报的近似表达和随机对照。标签按评论与事件类别评估，"
              "停滞由时间戳计算，排除在文本分类指标之外。", "",
              "| 方案 | 真阳性 | 假阳性 | 假阴性 | 精确率 | 召回率 |",
              "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for method, row in scored.items():
        output.append(f"| {method} | {row['tp']} | {row['fp']} | {row['fn']} | {fmt(row['precision'])} | {fmt(row['recall'])} |")
    if human:
        output += ["", f"## 仅人工复核样本（{reviewed} 条）", "",
                   "| 方案 | 真阳性 | 假阳性 | 假阴性 | 精确率 | 召回率 |",
                   "| --- | ---: | ---: | ---: | ---: | ---: |"]
        for method, row in human.items():
            output.append(f"| {method} | {row['tp']} | {row['fp']} | {row['fn']} | "
                          f"{fmt(row['precision'])} | {fmt(row['recall'])} |")
    output += ["", f"模型候选中 {rejected}/{len(raw)} 条因引用验证被拒绝（{fmt(rejected_rate)}）。"
               f"本轮实际请求 {model.billed} 次，命中缓存 {model.cache_hits} 次。"
               f"费用估算 ¥{model.usage:.4f}，每 100 条评论 ¥{cost_per_100:.4f}。", "",
               "## 预测与复核标签的分歧", ""]
    disagreements = []
    for row in rows:
        cid = row["id"]
        reference = targets[cid]
        actual = predictions["并集"].get(cid, set())
        if actual != reference:
            disagreements.append(f"- [评论 {cid}]({row['url']}) · 参照 {', '.join(sorted(reference)) or '无'} · "
                                 f"结果 {', '.join(sorted(actual)) or '无'}")
    output.extend(disagreements[:20])
    (ROOT / "eval/radar.md").write_text("\n".join(output) + "\n", encoding="utf-8")
    print(f"已评测 {len(labels)} 条评论，{reviewed} 条人工复核")


if __name__ == "__main__":
    main()
