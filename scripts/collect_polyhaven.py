"""Import the public Poly Haven model metadata into a separate project library."""
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
target = ROOT / "data/library/polyhaven.json"
if target.is_file():
    models = json.loads(target.read_text(encoding="utf-8"))["assets"]
else:
    req = Request("https://api.polyhaven.com/assets?t=models", headers={"User-Agent": "ArtPipe-Portfolio/0.1"})
    with urlopen(req, timeout=20) as stream:
        response = json.load(stream)
    models = []
    for slug, item in sorted(response.items()):
        if not slug.replace("_", "").isalnum() or not isinstance(item, dict):
            continue
        models.append({"slug": slug, "name": item.get("name") or slug, "license": "CC0",
                       "tags": item.get("tags") or [], "categories": item.get("categories") or [],
                       "source": f"https://polyhaven.com/a/{slug}"})
    target.parent.mkdir(parents=True, exist_ok=True)
    data = {"collected_at": datetime.now(timezone.utc).isoformat(), "assets": models}
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"Poly Haven 独立目录 · {len(models)} 个模型 · CC0")
