# Task 01 — Game Art Asset Platform on real 0 A.D. data (merges ArtGate + PipeSched)

> Working name: **ArtPipe｜游戏美术资产入库预检与风险雷达** (feel free to keep the name).
> Owner: the author. Builder: Codex. Effort: MVP ≈ 12 person-days, phase 2 ≈ 8–10 days.
> Language: code/comments in English; README, DEMO, 面试讲法 and UI labels in Chinese (with English terms in brackets where useful).

---

## 0. Why this exists (read first)

The author is applying for AI product manager internships at Tencent IEG (game platform / AI game). His earlier prototypes **ArtGate** (asset search + intake precheck) and **PipeSched** (production schedule risk agent) were technically solid but used **synthetic or CC0 toy data**, so interviewers could not see a real scenario. This project rebuilds both ideas on **the real art repository, commit history, issues, milestones and review comments of the open-source RTS game 0 A.D.** (Wildfire Games, 20+ years of production history). Every rule must be validated by replaying 0 A.D.'s own history.

### User scenario (场景, keep this wording in README first screen)
**一句话：** 开源游戏 0 A.D. 的美术审核者每次合并贡献前，工具先告诉他「这批文件里有没有断引用、用错等级的部件、重复贴图、不合规 PNG」；制作人在版本冻结前看到「哪些必须有的美术任务卡在等动画、等授权、等返工」。在腾讯项目里，对应的是外包交付验收和版本排期会（这是类比，不要声称接入了腾讯任何系统）。

**Personas【示意】**
- 「老陈」，TA 或美术审核者：周五晚上外包或社区贡献者交来一批文件，他想在 5 分钟内拿到一张带原因的退回清单，而不是导入引擎才报错。
- 「Lily」，制作人：版本冻结前的周一例会，她想要一张「必须有」美术任务的风险卡，每张卡附原评论链接。

**Job stories**
- 当一批美术文件准备合并时，我想立刻看到哪些文件有确定性问题、为什么、在哪一行，这样贡献者能当天修好，问题不会进版本。
- 当版本冻结临近时，我想知道哪些必须有的美术任务的评论里出现了依赖、返工、授权或长时间停滞，这样我能在会上直接协调，而不是延期后才知道。

---

## 1. Repository

- **New repo**, suggested name `game-asset-pipeline` (the author decides public/private; do not push without the author's say-so).
- Copy `AGENTS.md` from this folder to the repo root and this file to `docs/TASK.md`.
- Old code for reference only (not on the author's machine, provided as git bundles in `reference_code/`):
  ```bash
  git clone reference_code/artgate.bundle   ref/artgate     # ArtGate v2
  git clone reference_code/pipesched.bundle ref/pipesched   # PipeSched v2
  ```
  Reuse ideas, not wholesale code. Key logic worth porting:
  - ArtGate: YAML "spec templates" per project; rules with severity `block` / `warn`; **only deterministic rule failures block**, model or visual judgements only `warn` into a human queue; tool crash → "工具失败，待人工", never replaced by an LLM; hybrid search = structured filter + BM25 (with a hand-written Chinese↔English synonym table) + OpenCLIP, fused with RRF (k=60); eval with Recall@10 / nDCG@10 / MRR on a gold query set with dev/test split.
  - PipeSched: rules first, then LLM reads free-text review comments to extract blockers **with mandatory comment id + verbatim quote** (reject output whose quote is not a substring of the comment); keyword baseline for comparison; shadow mode (only cards, never writes status); sarcasm and "historical mention" negatives (e.g. "重做记录见 v3，v4 已通过" is *not* a blocker).
- Starting evidence in `evidence/` (copy into `research/` in the new repo): `dupcheck.sh`, `rankcheck.py`, `refcheck.py`, `refcheck_head.json`, `art_issues.json` (see `evidence/README.md`).

## 2. Tech stack
- Python 3.11+, SQLite (via `sqlite3` stdlib), `httpx` (API), `lxml` (XML), `Pillow` (PNG), `PyYAML`, `pytest`, FastAPI + Jinja2 (workbench UI, server-rendered, no SPA), `rank-bm25` + `jieba` (phase 2 search), `open_clip_torch` CPU (phase 2), `trimesh` or `pycollada` for .dae (phase 2).
- LLM: OpenAI-compatible endpoint; default SiliconFlow `https://api.siliconflow.cn/v1`, model `deepseek-ai/DeepSeek-V3.2` (configurable). Only env var: `SILICONFLOW_API_KEY`.
- No GPU, no Docker required.

## 3. Data sources (all public, no login) — measured 2026-11-16

### 3.1 Git history (metadata only — never full-clone the 15 GB repo)
```bash
git clone --filter=blob:none --no-checkout https://gitea.wildfiregames.com/0ad/0ad.git data/0ad   # ~32 MB, ~1–3 min
cd data/0ad
git ls-tree -r --name-only HEAD -- binaries/data/mods/public/art > ../art_files.txt               # 22,028 files
git sparse-checkout init --no-cone
git sparse-checkout set 'binaries/data/mods/public/art/actors/**' 'binaries/data/mods/public/art/variants/**' 'binaries/data/mods/public/art/materials/**'
GIT_LFS_SKIP_SMUDGE=1 git checkout -q main      # ~6,900 XML files, ~30 MB (XML is not LFS)
```
Measured at HEAD `14b258b10` (2026-11-15):
- art files 22,028 (xml 7,789 · png 7,425 · dae 5,525 · dds 1,176 · tga 60); subdirs: textures 8,721, actors 5,705, meshes 4,305, animation 1,220, variants 1,167, terrains 719.
- commits total 26,122 (since 2003); commits touching `art/` 3,985 by 64 authors (2008–2026).
- `.png .dae .dds .pmd .psa` etc. are **Git LFS** (see `.gitattributes`); the box had no git-lfs, which is fine.
- Han civilisation: 301 art files, 59 unit templates under `simulation/templates/units/han/`.

### 3.2 Single binary files (LFS) over HTTP, on demand
`https://gitea.wildfiregames.com/0ad/0ad/media/branch/main/<repo-path>` (tested: `.../art/textures/skins/gaia/bamboo.png` → HTTP 200, ~342 KB). For historical versions use `/media/commit/<sha>/<path>`. Cache to `data/blobs/` (gitignored). MVP downloads only what a rule needs (e.g. PNGs for R3/R4 in a chosen subset, ≤ 2 GB total).

### 3.3 Gitea REST API (base `https://gitea.wildfiregames.com/api/v1/repos/0ad/0ad`)
| Endpoint | Use | Measured |
|---|---|---|
| `GET /issues?state=all&type=issues&limit=50&page=N` | all issues (`X-Total-Count` header) | 7,709 (1,595 open) |
| `GET /issues?state=all&type=issues&labels=Theme/Art%20%26%20Animation&limit=50&page=N` | art issues | 252 (212 closed, 155 `Closed/Fixed`) |
| `GET /issues/{n}/comments?limit=50` | comments | e.g. #8414 has 23 |
| `GET /issues/{n}/timeline?limit=50` | milestone/label change events | has `milestone` events |
| `GET /milestones?state=all&limit=50` | `due_on`, `closed_at`, open/closed counts | 37 milestones |
| `GET /labels?limit=100` | 46 labels incl. `Priority/1: Release Blocker` … `Priority/5: If Time Permits`, `Theme/*`, `Type/*`, `Closed/*` | |
| `GET /pulls?state=all&limit=50&page=N`, `GET /pulls/{n}/reviews`, `GET /issues/{n}/comments` for PR comments | PR review text | 1,589 PRs |
Paginate with `page`; respect ≤ 2 req/s; cache JSON to `data/api_cache/`.

### 3.4 Supplementary libraries (phase 2, cross-project reuse demo)
Poly Haven API `https://api.polyhaven.com/assets?t=models|textures` (522 models, 870 textures, CC0); Khronos `https://github.com/KhronosGroup/glTF-Sample-Assets` (150 models, per-model licences); Kenney `https://kenney.nl/assets` (CC0, ~250+ packs). Optional.

### 3.5 Licence (must implement)
0 A.D. art is **CC-BY-SA 3.0** (`binaries/data/mods/public/art/LICENSE.txt`), code GPL-2.0+. README + UI footer must say: "美术素材来自 0 A.D.，© Wildfire Games，CC BY-SA 3.0（https://creativecommons.org/licenses/by-sa/3.0/），https://www.wildfiregames.com/". **Do not commit 0 A.D. binary art into this repo**; store paths, hashes and generated thumbnails only (thumbnails are derivatives → mark CC-BY-SA). Quote issue comments briefly with link; never display emails; usernames only as the public handle already on the issue page, or omit.

## 4. Features

### MVP
**A. 入库预检 (intake precheck)** — rules run on a git revision or a commit range (= "a submitted batch").
| Rule | Severity | Needs blobs? | Logic |
|---|---|---|---|
| R1 duplicate format | block | no | same basename under `art/textures/` exists as both `.png` and `.dds` |
| R2 rank-consistent props | block | XML only | an expert actor `*_e_<x>.xml` under `actors/units/` must not reference a unit prop actor `units/**/*_(a|b)_<x>.xml` (any variant, incl. `gather_*`) |
| R3 PNG metadata | warn | PNG | PNG has both `sRGB` and `iCCP` chunks, or multiple `iCCP` (what pngcheck flags; read chunks directly, don't rely on Pillow's `info` alone) |
| R4 power-of-two | block for `textures/skins/**`, warn for `textures/ui/**` | PNG/DDS header | width and height must be powers of two (UI is exempt from blocking, like ArtGate's product decision) |
| R5 reference integrity | block | XML only | every `<mesh>`, `<texture file=>`, `<prop actor=>`, `<variant file=>` resolves to an existing file (prefixes `meshes/`, `textures/skins/`, `actors/`, `variants/`) |
| R6 naming convention | warn | no | lower-case, no spaces, allowed charset `[a-z0-9_./-]`, extension whitelist; derive allowed patterns from current tree statistics, put them in YAML |
Output: per-batch report (Markdown + JSON + UI page) listing file, rule, severity, evidence (line number / chunk / referenced path), suggested fix.

**B. 历史回放 (history replay)** — for every commit touching `art/`, run the blob-free rules (R1, R2, R5, R6) on the post-commit tree (incremental: only re-evaluate changed files and their dependants). Record when each violation first appears and when it disappears → "引入 → 修复" latency. Link to issues mentioned in commit messages (`#\d+`, `Fixes #n`).

**C. 隐性阻塞雷达 (hidden-blocker radar)** — for art issues (252) plus their comments (and later PR review comments): LLM extracts blocker events of types `dependency` (waiting on another person/skill, e.g. animator), `rework` (texture stretched, needs remodel), `licensing` (legal waiver / licence missing), `duplicate_effort`, `stalled` (computed, not LLM: no activity for > N days while milestone open), `question_unanswered`. Each extraction must include `comment_id` and a verbatim `quote` (validated as substring; otherwise discarded and logged). Keyword baseline for comparison. Risk card per issue: priority label, milestone, blockers with quotes/links, days since last activity. Shadow mode only.

**D. 里程碑视图** — table of milestones with `due_on`, `closed_at`, delay days, closed issue count; art issue time-to-close distribution. Caveat text: `due_on` is the final value after migration and may have been edited, so call it "最终计划日期", not "original plan".

**E. Workbench (FastAPI)** — pages: 预检报告 (pick revision or commit range), 历史回放 (timeline of violations), 风险卡 (by milestone), 资产详情 (file → referencing actors → referenced meshes/textures graph). Chinese UI.

### Phase 2
- 中文检索: thumbnails for ~500 `.dae` (Han + siege + structures) via trimesh/pyrender or Blender headless; Chinese glossary (~200 terms, e.g. 攻城锤 = battering ram / ram) + BM25 + OpenCLIP, RRF; 80–100 Chinese gold queries **reviewed by the author**; Recall@10 vs filename search. Scenario: issue #8414 needs a new Han battering ram — find existing rams/wooden siege parts first.
- Content rules: `.dae` triangle budget per category (YAML, derived from distribution p95), texture size caps, stretched-texture heuristic (UV texel density).
- Milestone risk backtest: snapshot as of Release 28 freeze (choose a date ~4 weeks before `closed_at` 2026-02-20), score open Must-Have art issues, compare with what was later moved out / closed late. Use timeline events.
- Optional supplementary library ingest (Poly Haven) to show "跨项目复用" with project isolation.

## 5. Milestones (commit at each)
1. **M1 Ingest (2 d)** — `artpipe ingest` CLI: blobless clone + sparse XML, art file list, commit log (art paths) into SQLite; Gitea issues/milestones/labels/comments/timelines for art issues into SQLite with cache. Tests use recorded fixtures (no network).
2. **M2 Rules R1–R6 (2.5 d)** — `artpipe check --rev <sha>` and `--range A..B`; YAML spec; unit tests with tiny fixture trees; R3/R4 download only needed blobs.
3. **M3 Replay (2 d)** — `artpipe replay` over all art commits for R1/R2/R5/R6; outputs `eval/replay.md` (violations found, lifetimes, linked issues).
4. **M4 Blocker radar (2.5 d)** — `artpipe radar --milestone "Release 29"`; LLM + keyword baseline; the author (or Codex, labelled as provisional) labels 60 comments → precision/recall; `eval/radar.md`.
5. **M5 Workbench (2 d)** — FastAPI pages above; `scripts/run_app.sh`.
6. **M6 Docs & eval (1 d)** — README (scenario first), DEMO.md, 面试讲法.md, COST.md, licence attribution, badcases.

## 6. Acceptance criteria (must all pass; paste command output in the PR/commit notes)
1. `pytest -q` passes offline.
2. **#6738 reproduction:** `artpipe check --rev eafacb6e2^ --rules R1` reports exactly these 5 basenames (paths under `art/textures/`):
   `skins/gaia/bamboo`, `skins/props/head/pers_face_a`, `skins/props/head/pers_face_b`, `skins/props/head/pers_face_i`, `skins/props/head/pers_face_j`. At `--rev eafacb6e2` and at `HEAD`, R1 reports 0. At `0dd3bcc8e^`, R1 reports 13 groups.
3. **#7649 reproduction:** `artpipe check --rev 3142b7cba^ --rules R2` reports `units/kushites/cavalry_spearman_e_m.xml → units/kushites/cavalry_spearman_a_r.xml` (and the sibling `persians/cavalry_javelinist_e_m.xml → units/persians/cavalry_javelinist_a_r.xml`); at `3142b7cba` the kushite hit is gone.
4. **Current finding:** `artpipe check --rev HEAD --rules R2` reports `units/achaemenids/cavalry_javelinist_e_m.xml` referencing `units/achaemenids/cavalry_javelinist_a_r.xml` in the `gather_meat` variant (verify line number in the report). (If upstream has fixed it by the time you run this, record the fixing commit instead.) **Do not file an upstream issue; the author decides.**
5. **#9156 reproduction:** R3 flags `art/textures/particles/hero_aura.png` (sRGB + iCCP) and `art/textures/skins/gaia/rice_paddy_norm.png` (multiple iCCP) at HEAD (unless fixed upstream; then show the fixing commit).
6. **NPOT history:** R4 flags `art/textures/ui/session/portraits/units/kush_hero_arakamani.png` at `7d180bcf1` (introduced 2020-08-20) and not at `2ec4abd03` (fixed 2020-09-20), with a "warn" severity because it's under `textures/ui/` — explain this in the report.
7. **R5 at HEAD:** 0 broken references over ≈69k references (counts printed: mesh ≈7,362, texture ≈22,747, prop ≈21,447, variant ≈17,567; small drift allowed if upstream changed).
8. **Replay:** `eval/replay.md` lists for R1/R2 at least: the 2021-12 duplicate clean-up (#6326 series, e.g. `0dd3bcc8e`), #6738 (`eafacb6e2`; `bamboo.dds` added 2019-11-23 in `89f6205d9` → lifetime > 3 years), #7649. Lifetimes computed from commit dates.
9. **Radar on #8414** ("Han Chinese need new Battering Ram model", Priority/2 Must Have, Release 29): card shows at least `dependency` (comment 2025-10-06 "does anyone know how to animate it?"), `rework` (2025-10-14 texture 512×512 → 512×1024 because stretched), `licensing` (2025-11-15 "you need to sign the legal waiver"), `duplicate_effort` (2025-11-14 another contributor's models), and `stalled` (no activity since 2026-05-09 at time of writing), each with a working link and verbatim quote. Zero quotes that fail substring validation in the final output.
10. **Milestones:** `eval/milestones.md` reproduces delays: Alpha 21 +43 d, Alpha 22 +56, Alpha 23 +287, Alpha 24 +30, Alpha 25 +62, Alpha 26 +201, Alpha 27 +5, Release 28 +1 (computed from API, not typed); art issue time-to-close median ≈ 92 d, P75 ≈ 434 d (n = 212 at 2026-11-16; drift allowed).
11. Fresh-clone Quick start in README works on a laptop without GPU in < 15 min (excluding optional phase-2 downloads).
12. Secret scan clean; no 0 A.D. binary art committed (`git ls-files | grep -Ei '\.(png|dds|dae|pmd|psa)$'` returns only your own UI assets, if any).

## 7. Evaluation & metrics (write to `eval/`)
- Precheck: per-rule hits at HEAD; replay counts; **"would have caught earlier" days** = sum of violation lifetimes for violations later fixed; precision via manual review of 30 random hits per rule (the author reviews; until then label as "未人工复核").
- Radar: precision/recall of LLM vs keyword baseline on ≥ 60 hand-labelled comments (label file `labels/radar_labels.csv`; if labelled by Codex, mark `provisional=true` and never call it human); quote-validation failure rate; cost per 100 comments.
- Latency: precheck on a 200-file batch P95; full replay wall time.
- Cost: `COST.md` from logged token usage.

## 8. Deliverables
- `README.md` (Chinese): first screen = 一句话场景 + 场景图 (mermaid) + 3 headline findings (e.g. "#6738 的 5 个重复贴图在修复前版本上被逐一复现" / "当前版本发现 1 处与 #7649 同类、尚未报告的问题" / "#8414 风险卡"). Then results tables, then architecture, honesty boundary, licence.
- `DEMO.md`: 4-minute demo: run check on `eafacb6e2^`, open replay timeline, open #8414 risk card.
- `面试讲法.md`: 30-second pitch + follow-ups (why rules not LLM for blocking; why shadow mode; data limits: volunteer project ≠ studio; due dates are final not original; no hours data so no person-day forecasting).
- `COST.md`, `eval/*.md`, `docs/TASK.md`.

## 9. DO NOT
- Do not full-clone or mirror the 15 GB repo; do not hammer the Gitea server (≤ 2 req/s, cache everything).
- Do not commit 0 A.D. binary art; always attribute CC-BY-SA.
- Do not invent effort hours or person-day estimates (0 A.D. has no such data); no synthetic tasks presented as real.
- Do not let the LLM block anything; LLM output is advisory and must quote its source.
- Do not file issues/PRs upstream or post anywhere on the author's behalf.
- Do not claim integration with any Tencent/company system; the Tencent outsourcing mapping is an analogy in prose only.
- Do not commit secrets; only `SILICONFLOW_API_KEY` is needed and it lives in `.env.local`.
