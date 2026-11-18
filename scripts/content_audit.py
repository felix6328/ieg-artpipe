"""Compute category budgets and list content-level review items."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artpipe.git_source import GitSource  # noqa: E402
from artpipe.precheck import MediaCache  # noqa: E402
from artpipe.rules import read_image_header  # noqa: E402


def analyze(assets, spec):
    grouped = defaultdict(list)
    for item in assets:
        grouped[item["category"]].append(item["triangles"])
    caps = {kind: int(np.percentile(counts, spec["triangle_budget_percentile"], method="higher"))
            for kind, counts in grouped.items()}
    findings = []
    for item in assets:
        cap = caps[item["category"]]
        if item["triangles"] > cap:
            findings.append((item["path"], "面数预算", f"{item['triangles']} 三角面，高于 {cap}"))
        uv = item["uv_density_ratio"]
        if uv is not None and uv > spec["uv_density_warn_ratio"]:
            findings.append((item["path"], "UV 密度差", f"P90/P10 = {uv:.1f}"))
    return caps, findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--texture", action="append", default=[], help="要检查尺寸的贴图路径，可重复")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    spec = yaml.safe_load((ROOT / "configs/search.yaml").read_text())
    rules = yaml.safe_load((ROOT / "configs/precheck.yaml").read_text())
    catalog = json.loads((ROOT / "data/library/assets.json").read_text())
    budgets, review = analyze(catalog["assets"], spec)
    all_files = GitSource(ROOT / "data/0ad").tree(catalog["revision"])
    media = MediaCache(ROOT / "data/blobs", catalog["revision"], all_files, rules["io"], args.offline)
    missing = []
    for file in args.texture:
        try:
            width, height = read_image_header(file, media.load(file, False))
            cap = next((value for prefix, value in spec["texture_cap"].items() if file.startswith(prefix)),
                       spec["texture_cap"]["default"])
            if max(width, height) > cap:
                review.append((file, "贴图尺寸", f"{width} × {height}，上限 {cap}"))
        except (OSError, KeyError, ValueError) as exc:
            missing.append((file, str(exc)))
    lines = ["# 美术内容检查", "",
             f"检查 {len(catalog['assets'])} 个可解析网格和 {len(args.texture) - len(missing)} 张选定贴图。"
             "面数阈值来自本次目录内各类别的 P95。UV 密度用同一网格内局部 UV 面积相对空间面积的分布估算，"
             "可提示需复核的区域，贴图内容和风格仍由审核者确认。", "",
             "面数阈值 " + "，".join(f"{name} {cap:,}" for name, cap in budgets.items()), "",
             "| 资产 | 检查项 | 证据 |", "| --- | --- | --- |"]
    lines.extend(f"| {file} | {kind} | {evidence} |" for file, kind, evidence in review)
    if missing:
        lines.extend(["", "## 待核对", ""] + [f"- {file} · {cause}" for file, cause in missing])
    (ROOT / "eval/content-audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
