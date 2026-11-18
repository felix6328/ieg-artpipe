"""Create provisional Chinese queries and compare filename, BM25, and hybrid retrieval."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import re
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from artpipe.search import Search  # noqa: E402

QUERIES = [
    ("han", "han_arsenal(?:\\.dae|_)", "找汉朝军械库模型", "汉代武备存放建筑和组件"),
    ("han", "han_barracks(?:\\.dae|_)", "汉朝兵营", "汉代军营主体和里面的东西"),
    ("han", "han_chariot\\.dae", "汉朝战车", "汉代可作战的轮式车原型"),
    ("han", "han_forge_wheel", "汉朝锻造场车轮", "找汉代铁匠作坊的圆轮模型"),
    ("han", "han_bireme_tent", "汉代划船罩棚", "汉船上的帐篷组件"),
    ("han", "han_dockprops", "汉朝码头附件", "汉船停泊建筑里的小道具"),
    ("han", "han_market_props", "汉代集市摊位组件", "找汉朝市场陈列道具"),
    ("han", "han_civic_center\\.dae", "汉朝市政中心主体", "找汉代聚落的主城建筑"),
    ("han", "han_bixie(?:\\.dae|_)", "汉朝辟邪雕像", "可放在汉代建筑门前的石兽"),
    ("han", "han_crossbow_quiver", "汉军弩兵箭筒", "汉代弩手用的弹药容器"),
    ("han", "han_bow_composite", "汉朝复合弓", "汉代反曲的远射兵器模型"),
    ("han", "han_juezhang", "汉代脚踏弩", "找汉弩步兵的大型弩具"),
    ("han", "han_liannu", "汉朝连发弩", "能连续发射的汉弩模型"),
    ("han", "han_nu\\.dae", "汉朝普通手弩", "汉代单发远射的机械弓"),
    ("han", "han_qiang", "汉朝长枪", "汉代带枪尖的长柄兵器"),
    ("han", "han_curved_dao", "汉代弯刀", "找汉朝曲刃短兵器"),
    ("han", "han_sword_han_xin", "韩信佩剑", "找给汉代将领韩信用的剑"),
    ("han", "han_quiver_hip(?:\\.dae|_)", "汉代腰间箭袋", "找挂在弓手腰侧的箭筒附件"),
    ("han", "peytral_han", "汉朝战马马铠", "找护住骑兵马胸的装甲"),
    ("han", "han_merchant_sail", "汉代商船船帆", "找汉朝经商船只上的帆布"),
    ("siege", "/(?:[^/]+_)?(?:siege_)?ram\\.dae$", "找攻城锤的整体模型", "想给城门做一台带木架的冲车"),
    ("siege", "rome_(?:siege_)?ram\\.dae", "罗马攻城锤", "找罗马城门攻坚用的撞门车"),
    ("siege", "iber_ram\\.dae", "伊比利亚攻城锤", "找伊比利亚用的重型撞门器"),
    ("siege", "celt_siege_ram_shields", "凯尔特攻城锤护盾", "找可装在凯尔特撞城车上的侧面防护板"),
    ("siege", "hele_siege_tower\\.dae", "找希腊攻城塔", "需要希腊系能接近城墙的移动高塔"),
    ("siege", "rome_ballista(?:[0-9_]*\\.dae)", "古罗马弩炮", "找罗马远程攻城巨弩模型"),
    ("siege", "lithobolos", "石弩投石机", "找可以连续往城墙扔石弹的砲"),
    ("siege", "siege_onager(?:\\.dae|_)", "扭力投石机", "找罗马野驴式的抛石器"),
    ("siege", "ammo_stone_(?:lrg|med|sml)", "投石机石弹", "找形状接近圆石的攻城弹丸"),
    ("siege", "projectile_bolt|ammo_bolt", "大型攻城弩矢", "找弩炮发射出去的长箭"),
    ("siege", "rome_scorp|scorpio_", "罗马蝎弩", "找长臂罗马弩具参考件"),
    ("siege", "polybolos", "连射式弩炮", "想对比能快速发射弩矢的攻城器械"),
    ("siege", "rome_siege_gate_door", "罗马攻城门板组件", "找罗马城墙通行口可开合的门"),
    ("siege", "trunk_ram(?:\\.dae|_)", "木桩撞城原型", "找一根木头制成的简单攻城槌"),
    ("structure", "(?:palisade|pallisade).*wood|wood.*(?:palisade|pallisade)", "木栅栏结构件", "找可拼成围栏的木墙组件"),
    ("structure", "bamboo_(?:gate|tower|wall)|(?:gate|tower|wall).*bamboo", "竹制城防资产", "找竹木搭出来的可围合门塔"),
    ("structure", "rome_blacksmith", "罗马铁匠铺", "找罗马生产钢铁兵器的作坊"),
    ("structure", "brit_barracks", "不列颠兵营", "找不列颠训练步兵的营房"),
    ("structure", "kush_barracks", "库施军营", "找库施用的步兵训练建筑"),
    ("structure", "gaul_barracks", "高卢兵营模型", "找高卢的兵力征募用房"),
    ("structure", "celt_(?:house|hall)|/celt.*_house", "凯尔特民居", "找凯尔特村子里住人的房子"),
    ("structure", "athen_(?:civic|cc)", "雅典城镇中心", "雅典聚落最重要的行政建筑"),
    ("structure", "spart_(?:civic|cc)", "斯巴达主城", "斯巴达用于聚落管理的中心建筑"),
    ("structure", "parthenos.*pedestal", "雅典娜雕像基座", "找有顶层承托石像的台座"),
    ("structure", "colossus_.*(?:roof|door|mural|cover)", "巨像建筑装饰部件", "找巨像奇观上可单独重用的建筑附件"),
    ("structure", "mausoleum", "纪念陵墓", "找适合作为大型石制墓葬的模型"),
    ("structure", "brit_wonder_(?:roof|turf|ground)", "不列颠奇观附件", "找不列颠大型地标的顶面和底座模型"),
    ("structure", "mace_blacksmith", "马其顿锻造厂", "找马其顿铁匠制兵器的作坊"),
]


def prepare(assets, path):
    if path.exists():
        raise ValueError(f"已有标注文件，请另选路径：{path}")
    rows = []
    for group, (category, match, direct, natural) in enumerate(QUERIES, 1):
        targets = [asset["path"] for asset in assets if asset["category"] == category
                   and re.search(match, asset["path"])]
        if not targets:
            continue
        for position, query in enumerate((direct, natural), 1):
            rows.append({"id": f"q{group:02d}-{position}", "split": "dev" if group % 4 == 0 else "test",
                         "query": query, "expected_paths": "|".join(targets),
                         "review_status": "provisional"})
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print("准备待人审查询", len(rows))


def scores(results, targets):
    ranks = [position for position, path in enumerate(results, 1) if path in targets]
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(len(targets), 10) + 1))
    return (len(ranks) / len(targets), sum(1 / math.log2(i + 1) for i in ranks) / ideal,
            1 / ranks[0] if ranks else 0.0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--visual", action="store_true")
    parser.add_argument("--labels", type=Path, default=ROOT / "labels/search_queries.csv")
    args = parser.parse_args()
    service = Search(ROOT / "data", ROOT / "configs/search.yaml", use_visual=args.visual)
    if args.prepare:
        prepare(service.assets, args.labels)
    with args.labels.open(encoding="utf-8-sig", newline="") as source:
        labels = list(csv.DictReader(source))
    known_paths = {asset["path"] for asset in service.assets}
    ids = [row["id"] for row in labels]
    if len(set(ids)) != len(ids):
        raise ValueError("中文查询复核表存在重复 ID")
    for row in labels:
        if row["split"] not in {"dev", "test"} or row["review_status"] not in {"human", "provisional"}:
            raise ValueError(f"{row['id']} 的 split 或 review_status 无效")
        targets = set(filter(None, map(str.strip, row["expected_paths"].split("|"))))
        if not targets <= known_paths:
            raise ValueError(f"{row['id']} 有资产路径未收入当前检索目录")
        row["expected_paths"] = "|".join(sorted(targets))
    methods = ["filename", "lexical"] + (["hybrid_equal", "dev_selected"] if args.visual else [])
    selected_weight = 0.0
    candidates = {}
    if args.visual:
        dev = [label for label in labels if label["split"] == "dev" and label["expected_paths"]]
        for weight in (0.0, 0.1, 0.25, 0.5, 0.75, 1.0):
            measured = []
            for row in dev:
                paths = [asset["path"] for asset in service.rank(row["query"], visual_weight=weight)]
                measured.append(scores(paths, set(row["expected_paths"].split("|")))[1])
            candidates[weight] = statistics.mean(measured) if measured else 0.0
        selected_weight = max(candidates, key=lambda value: (candidates[value], -value))
    data = {}
    human_data = {}
    human_sizes = {}
    missed = []
    for split in ("dev", "test"):
        selected = [row for row in labels if row["split"] == split and row["expected_paths"]]
        data[split] = {}
        human_data[split] = {}
        human_sizes[split] = sum(row["review_status"] == "human" for row in selected)
        for mode in methods:
            runs = []
            human_runs = []
            for row in selected:
                targets = set(row["expected_paths"].split("|"))
                weight = selected_weight if mode == "dev_selected" else 1.0
                engine = "hybrid" if mode in {"hybrid_equal", "dev_selected"} else mode
                hits = [asset["path"] for asset in service.rank(row["query"], mode=engine, visual_weight=weight)]
                score = scores(hits, targets)
                runs.append(score)
                if row["review_status"] == "human":
                    human_runs.append(score)
                if mode == methods[-1] and score[2] == 0:
                    missed.append((row["query"], hits[0] if hits else "无"))
            data[split][mode] = [statistics.mean(col) for col in zip(*runs)] if runs else [0, 0, 0]
            if human_runs:
                human_data[split][mode] = [statistics.mean(col) for col in zip(*human_runs)]
    unreviewed = sum(row["review_status"] != "human" for row in labels)
    lines = ["# 中文资产检索评测", "",
             f"当前目录 {len(service.assets)} 个网格，术语表 {len(service.options['glossary'])} 条。"
             f"{len(labels)} 条中文查询，{unreviewed} 条待人工复核（provisional）。",
             "相关资产基于从真实资产名和用途整理的候选标签。文件名基线直接匹配原始文字，词法方案增加中文术语映射。"
             "同一意图的两种问法放在相同划分中。开发集选择视觉权重，测试集仅用于报告。", "",
             "| 划分 | 检索 | Recall@10 | nDCG@10 | MRR@10 |", "| --- | --- | ---: | ---: | ---: |"]
    for split, results in data.items():
        for name, row in results.items():
            lines.append(f"| {split} | {name} | {row[0]:.3f} | {row[1]:.3f} | {row[2]:.3f} |")
    if any(human_sizes.values()):
        lines += ["", "## 仅人工复核且有相关资产的查询", "",
                  "没有相关资产的查询不计入召回率、nDCG 与 MRR。", "",
                  "| 划分 | 查询数 | 检索 | Recall@10 | nDCG@10 | MRR@10 |",
                  "| --- | ---: | --- | ---: | ---: | ---: |"]
        for split, results in human_data.items():
            for name, row in results.items():
                lines.append(f"| {split} | {human_sizes[split]} | {name} | "
                             f"{row[0]:.3f} | {row[1]:.3f} | {row[2]:.3f} |")
    if args.visual:
        breakdown = "，".join(f"{weight:g}: {metric:.3f}" for weight, metric in candidates.items())
        lines += ["", f"开发集 nDCG 选择的视觉 RRF 权重为 {selected_weight:g}，词法权重为 1。"
                  f"候选权重与开发集 nDCG@10 为 {breakdown}。"]
    if missed:
        lines += ["", "## 未命中例", ""] + [f"- {query} → `{top}`" for query, top in missed[:12]]
    (ROOT / "eval/search.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = {"splits": data, "selected_weight": selected_weight, "dev_grid": candidates,
              "human_splits": human_data, "human_queries_with_targets": human_sizes}
    (ROOT / "eval/search.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8")


if __name__ == "__main__":
    main()
