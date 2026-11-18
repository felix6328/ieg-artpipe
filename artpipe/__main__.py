"""Command-line entry point."""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

import yaml

from .catalog import Gitea, connect, ingest
from .git_source import GitSource
from .metrics import markdown as milestone_markdown, milestones
from .radar import RadarModel, candidates, comments_for, make_card
from .precheck import CORE_RULES, ROOT, check
from .replay import replay


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="artpipe")
    parser.add_argument("--repo", type=Path, default=ROOT / "data/0ad")
    parser.add_argument("--spec", type=Path, default=ROOT / "configs/precheck.yaml")
    commands = parser.add_subparsers(dest="command", required=True)
    precheck = commands.add_parser("check", help="检查一个版本或一批美术变更")
    revision = precheck.add_mutually_exclusive_group()
    revision.add_argument("--rev", default="HEAD")
    revision.add_argument("--range", metavar="BASE..HEAD")
    precheck.add_argument("--rules", help="以逗号分隔，例如 R1,R2,R5。指定范围时默认执行全部规则。")
    precheck.add_argument("--scope", default="", help="art 下的文件或目录")
    precheck.add_argument("--offline", action="store_true", help="二进制检查只读本地缓存")
    precheck.add_argument("--format", choices=("markdown", "json"), default="markdown")
    precheck.add_argument("--output", type=Path)
    precheck.add_argument("--gate", action="store_true", help="命中拦截规则或检查不完整时返回非零退出码")
    history = commands.add_parser("replay", help="增量回放美术提交")
    history.add_argument("--rev", default="HEAD")
    history.add_argument("--format", choices=("markdown", "json"), default="markdown")
    history.add_argument("--output", type=Path)
    catalog = commands.add_parser("ingest", help="导入美术目录和上游项目数据")
    catalog.add_argument("--rev", default="HEAD")
    catalog.add_argument("--issue", type=int)
    catalog.add_argument("--details", action="store_true", help="抓取所有美术 Issue 的评论和时间线")
    catalog.add_argument("--snapshot", type=Path, help="用指定 Issue 快照代替 API 的列表")
    catalog.add_argument("--offline", action="store_true")
    catalog.add_argument("--refresh", action="store_true")
    radar = commands.add_parser("radar", help="生成带原评论证据的美术任务风险卡")
    selection = radar.add_mutually_exclusive_group(required=True)
    selection.add_argument("--milestone")
    selection.add_argument("--issue", type=int)
    radar.add_argument("--model", action="store_true", help="用硅基流动抽取评论，默认关键词基线")
    radar.add_argument("--format", choices=("markdown", "json"), default="markdown")
    radar.add_argument("--output", type=Path)
    stats = commands.add_parser("milestones", help="统计最终计划日与关闭日的差异")
    stats.add_argument("--format", choices=("markdown", "json"), default="markdown")
    stats.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        spec = yaml.safe_load(args.spec.read_text(encoding="utf-8"))
        source = GitSource(args.repo)
        if args.command == "ingest":
            api = Gitea(ROOT / "data/api_cache", spec["io"], offline=args.offline, refresh=args.refresh)
            counts = ingest(source, api, ROOT / "data/artpipe.sqlite", args.rev, snapshot=args.snapshot,
                            details=args.details, issue_number=args.issue, on_detail=_ingest_progress)
            print(json.dumps(counts, ensure_ascii=False, indent=2))
            return 0
        if args.command in ("milestones", "radar"):
            with closing(connect(ROOT / "data/artpipe.sqlite")) as db:
                if args.command == "milestones":
                    data = milestones(db)
                    write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n"
                               if args.format == "json" else milestone_markdown(data), args.output)
                else:
                    options = spec["radar"]
                    model = RadarModel(options, ROOT / "data/llm_cache") if args.model else None
                    issues = candidates(db, options, number=args.issue, milestone=args.milestone)
                    if not issues:
                        raise ValueError("没有符合条件的 Issue，请先运行 ingest")
                    as_of = datetime.now(timezone.utc)
                    cards = [make_card(issue, comments_for(db, issue["number"]), options, as_of=as_of,
                                       model=model) for issue in issues]
                    costs = {"estimate_cny": model.usage, "calls": model.billed,
                             "cache_hits": model.cache_hits} if model else None
                    data = {"as_of": as_of.isoformat(), "usage": costs, "cards": [card.json() for card in cards]}
                    md = "# 美术任务风险雷达\n\n" + "\n".join(card.markdown() for card in cards)
                    if costs:
                        md += f"\n本次模型调用 {costs['calls']}，费用估算 ¥{costs['estimate_cny']:.4f}。\n"
                    write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n"
                               if args.format == "json" else md, args.output)
            return 0
        if args.command == "replay":
            result = replay(source, args.rev, spec)
            write_report(result, args)
            return 0
        enabled = set(token.strip() for token in args.rules.split(",")) if args.rules else (
            set(spec["rules"]) if args.range or args.scope else set(CORE_RULES))
        if not enabled <= spec["rules"].keys():
            parser.error("未知规则：" + ", ".join(sorted(enabled - spec["rules"].keys())))
        base = None
        rev = args.rev
        if args.range:
            base, sep, rev = args.range.partition("..")
            if not sep or not base or not rev or rev.startswith("."):
                parser.error("--range 应使用 BASE..HEAD")
        report = check(source, rev, enabled, spec, cache=ROOT / "data/blobs", offline=args.offline,
                       base=base, scope=args.scope)
    except (OSError, ValueError, subprocess.CalledProcessError, yaml.YAMLError) as exc:
        print(f"预检失败：{exc}", file=sys.stderr)
        return 2
    write_report(report, args)
    if args.gate and report.unavailable:
        return 2
    return int(args.gate and any(item.severity == "block" for item in report.findings))


def _ingest_progress(done: int, total: int, number: int) -> None:
    if done == 1 or done % 25 == 0 or done == total:
        print(f"已导入 {done}/{total} 个 Issue 的详情，最近 #{number}", file=sys.stderr, flush=True)


def write_report(report, args) -> None:
    output = (json.dumps(report.json(), ensure_ascii=False, indent=2) + "\n"
              if args.format == "json" else report.markdown())
    write_text(output, args.output)


def write_text(content: str, output: Path | None) -> None:
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
    else:
        print(content, end="")


if __name__ == "__main__":
    raise SystemExit(main())
