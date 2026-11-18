"""Build the OpenCLIP index or search public models with structured filters."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from artpipe.search import Search  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("query", nargs="?", default="")
parser.add_argument("--embed", action="store_true")
parser.add_argument("--visual", action="store_true")
parser.add_argument("--image", type=Path)
parser.add_argument("--category", choices=("han", "siege", "structure"))
parser.add_argument("--max-faces", type=int)
parser.add_argument("--mode", choices=("filename", "lexical", "hybrid"), default="hybrid")
parser.add_argument("--limit", default=10, type=int)
args = parser.parse_args()
if not (args.query or args.embed or args.image):
    parser.error("请提供搜索描述、检索图片或 --embed")
service = Search(ROOT / "data", ROOT / "configs/search.yaml", use_visual=args.visual or bool(args.image))
if args.embed:
    service.embed()
    print(f"已建立 {len(service.assets)} 个模型的向量索引")
if args.query or args.image:
    print(json.dumps(service.rank(args.query, limit=args.limit, mode=args.mode, category=args.category,
                                  max_faces=args.max_faces, image=args.image), ensure_ascii=False, indent=2))
