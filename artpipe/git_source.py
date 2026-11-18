"""Read trees and XML blobs without checking out binary assets."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import os
import subprocess

ART = "binaries/data/mods/public/art"


@dataclass(frozen=True)
class Change:
    path: str
    old: str | None
    new: str | None


class GitSource:
    def __init__(self, root: Path):
        self.root = root

    def _git(self, *args: str, stdin: bytes | None = None) -> bytes:
        return subprocess.run(
            ["git", "-C", str(self.root), *args], input=stdin, stdout=subprocess.PIPE,
            env={**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"},
            check=True,
        ).stdout

    def revision(self, rev: str) -> str:
        return self._git("rev-parse", "--verify", "--end-of-options", f"{rev}^{{commit}}").decode().strip()

    def tree(self, rev: str) -> dict[str, str]:
        entries = self._git("ls-tree", "-r", "-z", rev, "--", ART)
        files = {}
        for entry in entries.split(b"\0"):
            if entry:
                meta, path = entry.split(b"\t", 1)
                _, kind, oid = meta.split()
                if kind == b"blob":
                    files[path.decode(errors="surrogateescape").removeprefix(ART + "/")] = oid.decode()
        return files

    def changes(self, old: str, new: str) -> list[Change]:
        raw = self._git("diff-tree", "-r", "-z", "--raw", "--no-renames", "--no-commit-id",
                        "--no-abbrev", old, new, "--", ART).split(b"\0")
        result = []
        for entry, path in zip(raw[0::2], raw[1::2]):
            _, _, before, after, _ = entry.split()
            relative = path.decode(errors="surrogateescape").removeprefix(ART + "/")
            result.append(Change(relative, _oid(before), _oid(after)))
        return result

    def history(self, rev: str) -> list[tuple[str, str, str, str]]:
        raw = self._git("log", "--first-parent", "--full-history", "--reverse", "-z",
                        "--format=%H%x00%P%x00%cI%x00%B", rev, "--", ART)
        fields = raw.decode(errors="replace").split("\0")
        return list(zip(fields[0::4], fields[1::4], fields[2::4], fields[3::4]))

    def prefetch(self, ids: set[str]) -> None:
        """Fetch missing XMLs in one negotiated request on a promisor clone."""
        if not ids:
            return
        response = self._git("cat-file", "--batch-check", stdin=_requests(ids))
        missing = {line.split()[0].decode() for line in response.splitlines() if line.endswith(b" missing")}
        if missing:
            self._git("-c", "fetch.negotiationAlgorithm=noop", "fetch", "--quiet", "--no-tags",
                      "--no-write-fetch-head", "--filter=blob:none", "--stdin", "origin",
                      stdin=_requests(missing))

    def blobs(self, ids: set[str]) -> dict[str, bytes]:
        if not ids:
            return {}
        self.prefetch(ids)
        stream = BytesIO(self._git("cat-file", "--batch", stdin=_requests(ids)))
        result = {}
        while header := stream.readline():
            fields = header.split()
            if len(fields) != 3 or fields[1] != b"blob":
                raise ValueError(f"Git blob unavailable: {fields[0].decode()}")
            oid, _, length = fields
            size = int(length)
            content = stream.read(size)
            if len(content) != size or stream.read(1) != b"\n":
                raise ValueError("Incomplete Git blob response")
            result[oid.decode()] = content
        return result


def _requests(ids: set[str]) -> bytes:
    return "".join(f"{oid}\n" for oid in sorted(ids)).encode("ascii")


def _oid(value: bytes) -> str | None:
    return value.decode() if value.strip(b"0") else None
