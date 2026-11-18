"""Read-only FastAPI workbench for asset review and release preparation."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
import json
import re
import subprocess

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import yaml

from .catalog import connect
from .git_source import ART, GitSource
from .metrics import milestones as milestone_metrics
from .precheck import CORE_RULES, ROOT, UPSTREAM, check
from .radar import NAMES, candidates, comments_for, make_card
from .rules import is_art_xml, parse_xml
from .search import Search, query_tokens, tokens

WEB = Path(__file__).resolve().parent
DB = ROOT / "data/artpipe.sqlite"
SOURCE = GitSource(ROOT / "data/0ad")
SPEC = yaml.safe_load((ROOT / "configs/precheck.yaml").read_text(encoding="utf-8"))
app = FastAPI(title="ArtPipe 工作台", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=WEB / "static"), name="static")
views = Jinja2Templates(directory=WEB / "templates")


def page(request, template, active, **context):
    return views.TemplateResponse(request=request, name=template,
                                  context={"active": active, "upstream": UPSTREAM, **context})


@app.get("/", response_class=HTMLResponse)
def intake(request: Request, rev: str = "eafacb6e2^", base: str = "", scope: str = "", rules: str = "R1",
           format: str = "", severity: str = ""):
    chosen = {value.strip() for value in rules.split(",") if value.strip()} or set(CORE_RULES)
    report = None
    error = ""
    try:
        if not chosen <= SPEC["rules"].keys():
            raise ValueError("规则应为 R1 至 R6，可用逗号分隔。")
        report = check(SOURCE, rev, chosen, SPEC, cache=ROOT / "data/blobs", offline=True,
                       base=base or None, scope=scope)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        error = str(exc)
    if report is not None and format == "json":
        return JSONResponse(report.json())
    if report is not None and format == "markdown":
        return PlainTextResponse(report.markdown())
    hits = [] if report is None else report.findings
    visible = [hit for hit in hits if not severity or hit.severity == severity]
    return page(request, "precheck.html", "intake", rev=rev, base=base, scope=scope,
                rules=rules, severity=severity, report=report, error=error, findings=visible[:200],
                match_count=len(visible), blocks=sum(hit.severity == "block" for hit in hits),
                warnings=sum(hit.severity == "warn" for hit in hits))


@app.get("/replay", response_class=HTMLResponse)
def history(request: Request, rule: str = "R1", q: str = ""):
    source = ROOT / "data/replay.json"
    result = json.loads(source.read_text(encoding="utf-8")) if source.is_file() else None
    rows = []
    if result:
        rows = [item for item in result["conditions"] if (not rule or item["finding"]["rule"] == rule)
                and q.casefold() in (item["finding"]["path"] + " " + " ".join(item["issues"])).casefold()]
        rows.sort(key=lambda item: (bool(item["issues"]), item["resolved_at"] or item["introduced_at"]), reverse=True)
    return page(request, "replay.html", "replay", report=result, entries=rows[:100], total=len(rows), rule=rule, q=q)


@app.get("/radar", response_class=HTMLResponse)
def radar(request: Request, milestone: str = "Release 29", issue: str = ""):
    number_filter = int(issue) if issue.isascii() and issue.isdecimal() and len(issue) <= 9 else None
    with closing(connect(DB)) as db:
        names = [row["title"] for row in db.execute("SELECT title FROM milestone ORDER BY id DESC")]
        available = {row["issue_number"] for row in db.execute("SELECT issue_number FROM issue_detail")}
        selected = candidates(db, SPEC["radar"], number=number_filter, milestone=milestone)
        reports = []
        model_cache = ROOT / "data/radar-release29.json"
        cached_release = {}
        if model_cache.is_file():
            cached = json.loads(model_cache.read_text(encoding="utf-8"))["cards"]
            cached_release = {card["number"]: card for card in cached}
        for row in selected:
            number = row["number"]
            cache = ROOT / f"data/radar-{number}.json"
            if cache.is_file():
                card = json.loads(cache.read_text(encoding="utf-8"))
                if "cards" in card:
                    card = card["cards"][0]
            elif number in cached_release:
                card = cached_release[number]
            else:
                card = make_card(row, comments_for(db, number), SPEC["radar"],
                                 as_of=datetime.now(timezone.utc)).json()
            if number_filter or card["events"]:
                reports.append(card)
        missing = sum(row["number"] not in available for row in selected)
    reports.sort(key=lambda item: (-len(item["events"]), -item["inactive_days"]))
    return page(request, "radar.html", "radar", cards=reports, issues=selected, skipped=missing,
                milestone=milestone, milestone_names=names, issue=issue, kinds=NAMES)


@app.get("/milestones", response_class=HTMLResponse)
def milestones(request: Request):
    with closing(connect(DB)) as db:
        report = milestone_metrics(db)
    return page(request, "milestones.html", "milestones", report=report)


@app.get("/assets", response_class=HTMLResponse)
def assets(request: Request, q: str = ""):
    with closing(connect(DB)) as db:
        results = db.execute("SELECT path, oid FROM asset WHERE instr(lower(path), lower(?)) > 0 "
                             "ORDER BY path LIMIT 100", (q.strip(),)).fetchall()
        total = db.execute("SELECT count(*) FROM asset WHERE instr(lower(path), lower(?)) > 0",
                           (q.strip(),)).fetchone()[0]
    return page(request, "assets.html", "assets", assets=results, total=total, q=q)


@lru_cache(maxsize=2)
def graph(rev: str):
    tree = SOURCE.tree(rev)
    xml = {path: oid for path, oid in tree.items() if is_art_xml(path)}
    blobs = SOURCE.blobs(set(xml.values()))
    documents = {oid: parse_xml(content) for oid, content in blobs.items()}
    incoming = {}
    for path, oid in xml.items():
        for ref in documents[oid].references:
            incoming.setdefault(ref.target, set()).add(path)
    return tree, documents, incoming


@app.get("/asset/{path:path}", response_class=HTMLResponse)
def asset_detail(request: Request, path: str):
    try:
        rev = SOURCE.revision("HEAD")
        tree, docs, incoming = graph(rev)
    except (OSError, subprocess.CalledProcessError):
        return page(request, "asset.html", "assets", asset=None, path=path)
    oid = tree.get(path)
    doc = docs.get(oid)
    source_paths = sorted(incoming.get(path, set()))
    return page(request, "asset.html", "assets", path=path, asset=oid, incoming=source_paths[:100],
                incoming_count=len(source_paths), outgoing=doc.references if doc else [], known=tree,
                asset_url=f"{UPSTREAM}/src/commit/{rev}/{ART}/{path}")


@lru_cache(maxsize=2)
def asset_search(manifest_stamp: int, visual: bool) -> Search:
    return Search(ROOT / "data", ROOT / "configs/search.yaml", use_visual=visual)


@app.get("/reuse", response_class=HTMLResponse)
def reuse(request: Request, q: str = "", category: str = "", max_faces: str = "",
          mode: str = "lexical", library: str = "0ad"):
    manifest = ROOT / "data/library/assets.json"
    visual = (ROOT / "data/library/vectors.npz").is_file()
    hits = []
    notice = ""
    poly = ROOT / "data/library/polyhaven.json"
    external = []
    if library == "polyhaven" and poly.is_file():
        items = json.loads(poly.read_text(encoding="utf-8"))["assets"]
        words, _ = query_tokens(q, yaml.safe_load((ROOT / "configs/search.yaml").read_text())["glossary"])
        ranked = [(len(set(words) & set(tokens(" ".join([item["name"], item["slug"],
                                                        *item["tags"], *item["categories"]])))), item)
                  for item in items]
        external = [item for score, item in sorted(ranked, key=lambda row: -row[0]) if score or not q.strip()][:30]
    elif q.strip() and manifest.is_file():
        try:
            budget = int(max_faces) if max_faces else None
            if budget is not None and budget <= 0:
                raise ValueError("面数上限需要为正整数")
            search = asset_search(manifest.stat().st_mtime_ns, visual)
            hits = search.rank(q.strip()[:200], limit=18, mode=mode,
                               category=category or None, max_faces=budget)
        except (ValueError, OSError, ImportError, RuntimeError) as exc:
            notice = f"资产检索暂不可用：{type(exc).__name__}"
    return page(request, "reuse.html", "reuse", q=q, category=category, max_faces=max_faces,
                manifest=manifest.is_file(), visual=visual, hits=hits, notice=notice, mode=mode,
                library=library, external=external, poly_available=poly.is_file())


@app.get("/thumbnail/{file}")
def render_preview(file: str):
    if not re.fullmatch(r"[0-9a-f]{40,64}\.png", file):
        raise HTTPException(404)
    path = ROOT / "data/library/thumbs" / file
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/png")
