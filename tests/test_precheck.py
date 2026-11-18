from pathlib import Path
import struct
import subprocess

import pytest
import yaml

from artpipe.git_source import ART, GitSource
from artpipe.precheck import ROOT, check
from artpipe.radar import validate
from artpipe.replay import replay
from artpipe.rules import PNG_SIGNATURE, inspect_binary, inspect_file, parse_xml

SPEC = yaml.safe_load((ROOT / "configs/precheck.yaml").read_text())
ACTOR = "actors/units/example/archer_e_m.xml"
PROP = "actors/units/example/archer_a_r.xml"
TEXTURE = "textures/skins/example/archer.png"


def test_xml_reports_wrong_rank_and_missing_reference_with_exact_lines():
    blob = b"""<actor>
    <variant>
        <prop actor="units/example/archer_a_r.xml"/>
        <texture file="example/archer.png"/>
    </variant>
</actor>"""
    tree = {ACTOR: "a", PROP: "b"}
    findings = inspect_file(ACTOR, tree, {"R2", "R5"}, SPEC, parse_xml(blob))
    assert [(item.rule, item.target, item.line) for item in findings] == [
        ("R2", PROP, 3), ("R5", TEXTURE, 4)
    ]


def test_xml_ignores_reference_in_comments_and_refuses_doctype():
    xml = parse_xml(b'<actor><!-- <prop actor="bogus.xml"/> --></actor>')
    assert xml.references == ()
    rejected = parse_xml(b'<!DOCTYPE actor [<!ENTITY x SYSTEM "file:///tmp/test">]><actor>&x;</actor>')
    assert rejected.error


def test_png_reports_chunks_and_directory_specific_dimensions():
    def chunk(name, data):
        return struct.pack(">I", len(data)) + name + data + b"\0" * 4

    ihdr = struct.pack(">IIBBBBB", 250, 250, 8, 6, 0, 0, 0)
    png = PNG_SIGNATURE + chunk(b"IHDR", ihdr) + chunk(b"sRGB", b"\0") + chunk(b"iCCP", b"a") + chunk(b"IEND", b"")
    def load(*_):
        return png

    skin = inspect_binary("textures/skins/a.png", {"R3", "R4"}, SPEC, load)
    ui = inspect_binary("textures/ui/a.png", {"R3", "R4"}, SPEC, load)
    assert [(item.rule, item.severity) for item in skin] == [("R3", "warn"), ("R4", "block")]
    assert [(item.rule, item.severity) for item in ui] == [("R3", "warn"), ("R4", "warn")]


@pytest.fixture
def source(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", "-C", str(tmp_path), *args], text=True).strip()

    def put(path, content):
        file = tmp_path / ART / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)

    git("init", "-q", "-b", "main")
    git("config", "user.email", "fixture@example.test")
    git("config", "user.name", "Fixture")
    put(ACTOR, '<actor><texture file="example/archer.png"/></actor>')
    put(TEXTURE, "PNG fixture")
    git("add", ".")
    git("commit", "-m", "Add actor and texture")
    git("rm", f"{ART}/{TEXTURE}")
    git("commit", "-m", "Drop texture")
    put(TEXTURE, "PNG fixture")
    git("add", ".")
    git("commit", "-m", "Restore texture", "-m", "Fixes #1")
    return GitSource(tmp_path)


def test_range_rechecks_unchanged_dependant_after_texture_removal(source, tmp_path):
    result = check(source, "HEAD^", {"R5"}, SPEC, cache=tmp_path, base="HEAD^^")
    assert len(result.findings) == 1
    assert result.findings[0].path == ACTOR
    assert result.findings[0].target == TEXTURE


def test_replay_resolves_dependency_when_only_target_changes(source):
    history = replay(source, "HEAD", SPEC)
    items = [item for item in history.conditions if item.finding.rule == "R5"]
    assert len(items) == 1
    assert items[0].issues == ("1",)
    assert items[0].resolved_sha == source.revision("HEAD")


def test_radar_drops_invented_quotes_quoted_repetition_and_wrong_comment():
    comments = [{"id": 1, "body": "> Old text\nWaiting for the animator.", "url": "https://example.test/1",
                 "created_at": "2026-11-17T00:00:00+00:00"}]
    events = [{"type": "dependency", "state": "raised", "comment_id": cid, "quote": quote}
              for cid, quote in [(1, "Waiting for the animator."), (1, "Old text"), (2, "Waiting for the animator."),
                                 (1, "Invented response")]]
    evidence, discarded = validate(events, comments)
    assert [item.quote for item in evidence] == ["Waiting for the animator."]
    assert discarded == 3


def test_r6_respects_only_the_structural_ao_png_suffix():
    directory = "textures/skins/structural/ao/"
    assert not inspect_file(directory + "germans/blacksmith_AO.png", {}, {"R6"}, SPEC)

    for path in (
        directory + "black Smith_AO.png",
        directory + "Blacksmith_AO.png",
        directory + "blacksmith_AO.dds",
        "textures/skins/structural/blacksmith_AO.png",
    ):
        assert [item.rule for item in inspect_file(path, {}, {"R6"}, SPEC)] == ["R6"]
