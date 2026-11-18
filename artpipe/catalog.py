"""Local catalog of upstream assets, issue snapshots and milestone events."""
from __future__ import annotations

from contextlib import closing
from hashlib import sha256
from pathlib import Path
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
import json
import sqlite3
import tempfile

from .git_source import GitSource
from .precheck import UPSTREAM

LABEL = "Theme/Art & Animation"
SCHEMA = """
CREATE TABLE IF NOT EXISTS asset (
    path TEXT PRIMARY KEY, oid TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS revision (
    sha TEXT PRIMARY KEY, parents TEXT NOT NULL, committed_at TEXT NOT NULL, message TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS milestone (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, due_on TEXT, closed_at TEXT,
    state TEXT, open_issues INTEGER, closed_issues INTEGER
);
CREATE TABLE IF NOT EXISTS label (id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS issue (
    number INTEGER PRIMARY KEY, title TEXT NOT NULL, state TEXT NOT NULL, milestone_id INTEGER,
    labels TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    closed_at TEXT, comment_count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS comment (
    id INTEGER PRIMARY KEY, issue_number INTEGER NOT NULL, body TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, url TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS comments_by_issue ON comment(issue_number, created_at);
CREATE TABLE IF NOT EXISTS event (
    id INTEGER PRIMARY KEY, issue_number INTEGER NOT NULL, kind TEXT NOT NULL,
    created_at TEXT NOT NULL, current_milestone INTEGER, previous_milestone INTEGER
);
CREATE TABLE IF NOT EXISTS issue_detail (
    issue_number INTEGER PRIMARY KEY, collected_at TEXT NOT NULL
);
"""


class Gitea:
    """Cache upstream pages by endpoint and paginate within the server's request limit."""

    def __init__(self, cache: Path, io: dict, offline: bool = False, refresh: bool = False):
        self.cache = cache
        self.offline, self.refresh = offline, refresh
        self.interval = 1 / io["requests_per_second"]
        self.timeout = io["timeout_seconds"]
        self.next_request = 0.0
        self.base = UPSTREAM.replace("/0ad/0ad", "/api/v1/repos/0ad/0ad")

    def pages(self, endpoint: str, **kwargs) -> list[dict]:
        result = []
        seen = set()
        for page in range(1, 1001):
            values = self.get(endpoint, **kwargs, limit=50, page=page)
            if not isinstance(values, list):
                raise ValueError(f"分页端点未返回列表：{endpoint}")
            fresh = [value for value in values if value["id"] not in seen]
            result.extend(fresh)
            seen.update(value["id"] for value in fresh)
            # Some Gitea comment endpoints return the whole list and ignore limit/page.
            if len(values) != 50 or not fresh:
                return result
        raise ValueError(f"分页超出上限：{endpoint}")

    def get(self, endpoint: str, **params):
        route = endpoint + "?" + urlencode(sorted(params.items()))
        key = sha256(route.encode("utf-8")).hexdigest()
        target = self.cache / f"{key}.json"
        if target.is_file() and (not self.refresh or self.offline):
            return json.loads(target.read_text(encoding="utf-8"))
        if self.offline:
            raise ValueError(f"离线缓存缺少请求：{route}")
        req = Request(self.base + route, headers={"Accept": "application/json", "User-Agent": "ArtPipe/0.1"})
        for attempt in range(3):
            sleep(max(0.0, self.next_request - monotonic()))
            self.next_request = monotonic() + self.interval
            try:
                with urlopen(req, timeout=self.timeout) as response:
                    value = json.load(response)
                self.cache.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=self.cache, mode="w", encoding="utf-8", delete=False) as stream:
                    json.dump(value, stream, ensure_ascii=False)
                Path(stream.name).replace(target)
                return value
            except HTTPError as exc:
                if attempt == 2 or exc.code not in {429, 500, 502, 503, 504}:
                    raise
                retry_after = exc.headers.get("Retry-After", "")
                if retry_after.isdigit():
                    self.next_request = max(self.next_request, monotonic() + float(retry_after))
            except URLError:
                if attempt == 2:
                    raise
            sleep(2**attempt)
        raise RuntimeError("Unreachable after the retry loop")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    return connection


def ingest(source: GitSource, api: Gitea, database: Path, revision: str, *,
           snapshot: Path | None = None, details: bool = False,
           issue_number: int | None = None, on_detail=None) -> dict:
    head = source.revision(revision)
    files = source.tree(head)
    revisions = source.history(head)
    issues = (json.loads(snapshot.read_text(encoding="utf-8")) if snapshot else
              api.pages("/issues", state="all", type="issues", labels=LABEL))
    milestones = api.pages("/milestones", state="all")
    labels = api.pages("/labels")
    with closing(connect(database)) as db:
        with db:
            db.execute("DELETE FROM asset")
            db.executemany("INSERT INTO asset VALUES (?, ?)", files.items())
            db.execute("DELETE FROM revision")
            db.executemany("INSERT INTO revision VALUES (?, ?, ?, ?)", revisions)
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('head', ?)", (head,))
            db.execute("DELETE FROM label")
            db.executemany("INSERT INTO label VALUES (?, ?)", ((row["id"], row["name"]) for row in labels))
            db.execute("DELETE FROM milestone")
            db.executemany("INSERT INTO milestone VALUES (?, ?, ?, ?, ?, ?, ?)", (
                (row["id"], row["title"], row.get("due_on"), row.get("closed_at"), row["state"],
                 row["open_issues"], row["closed_issues"]) for row in milestones
            ))
            db.executemany("INSERT OR REPLACE INTO issue VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", map(_issue, issues))
        collected = 0
        if details or issue_number is not None:
            numbers = [issue_number] if issue_number is not None else [row["number"] for row in issues]
            for number in numbers:
                comments = api.pages(f"/issues/{number}/comments")
                events = api.pages(f"/issues/{number}/timeline")
                with db:
                    db.execute("DELETE FROM comment WHERE issue_number = ?", (number,))
                    db.executemany("INSERT INTO comment VALUES (?, ?, ?, ?, ?, ?)", (
                        (row["id"], number, row["body"], row["created_at"], row.get("updated_at") or row["created_at"],
                         f"{UPSTREAM}/issues/{number}#issuecomment-{row['id']}") for row in comments
                    ))
                    db.execute("DELETE FROM event WHERE issue_number = ?", (number,))
                    db.executemany("INSERT INTO event VALUES (?, ?, ?, ?, ?, ?)", (
                        (row["id"], number, row.get("type", ""), row["created_at"],
                         (row.get("milestone") or {}).get("id"), (row.get("old_milestone") or {}).get("id"))
                        for row in events
                    ))
                    db.execute("""INSERT OR REPLACE INTO issue_detail VALUES (?, datetime('now'))""", (number,))
                collected += 1
                if on_detail:
                    on_detail(collected, len(numbers), number)
        summary = {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in
                   ("asset", "revision", "issue", "comment", "event", "milestone", "label", "issue_detail")}
    return {"head": head, "issues_source": "package_snapshot" if snapshot else "gitea_api", **summary}


def _issue(row: dict) -> tuple:
    return (row["number"], row["title"], row["state"], (row.get("milestone") or {}).get("id"),
            json.dumps([label["name"] for label in row["labels"]], ensure_ascii=False),
            row["created_at"], row["updated_at"], row.get("closed_at"), row["comments"])
