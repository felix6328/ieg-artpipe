"""Fetch and render a selected 0 A.D. mesh subset."""
import argparse
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from artpipe.git_source import GitSource  # noqa: E402
from artpipe.library import build  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rev", default="HEAD")
    parser.add_argument("--limit", default=500, type=int)
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 800:
        parser.error("--limit 应在 1 与 800 之间")
    spec = yaml.safe_load((ROOT / "configs/precheck.yaml").read_text())
    def progress(done, total, available, errors):
        print(f"{done}/{total} · 渲染 {available} · 待核对 {errors}", flush=True)

    library = build(GitSource(ROOT / "data/0ad"), args.rev, spec, ROOT / "data",
                    count=args.limit, offline=args.offline, progress=progress)
    return 0 if library["assets"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
