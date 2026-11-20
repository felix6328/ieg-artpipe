"""Blender-backed acceptance suite. Enable with ASSETGATE_REAL_TESTS=1."""
from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile
import json
import os
import subprocess

import pytest

from artpipe.assetgate.blender import BlenderAdapter, detect_blender
from artpipe.assetgate.library import Library
from artpipe.assetgate.settings import load_settings
from artpipe.assetgate.worker import Worker
from artpipe.assetgate.workflow import Conflict, Workflow

pytestmark = pytest.mark.skipif(os.environ.get("ASSETGATE_REAL_TESTS") != "1", reason="real Blender opt-in")
ROOT = Path(__file__).resolve().parents[1]
OPTIONS = {"uv_angle_degrees": 66, "uv_island_margin": 0.02}


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    executable = detect_blender()
    assert executable, "Install Blender or set ASSETGATE_BLENDER before running real tests"
    fixtures = tmp_path_factory.mktemp("assetgate-models")
    cmd = [str(executable), "--background", "--factory-startup", "--disable-autoexec", "--python-exit-code", "7",
           "--python", str(ROOT / "scripts/create_assetgate_fixtures.py"), "--", str(fixtures)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    return fixtures


@pytest.fixture
def workspace(tmp_path):
    config = load_settings()
    library = Library(tmp_path, config)
    return library, Workflow(library), Worker(library, BlenderAdapter(detect_blender(), config))


def upload(workspace, file):
    library, _, _ = workspace
    with file.open("rb") as stream:
        return library.upload(stream, file.name, "", "model")


def execute(workspace, version, operation, settings=None):
    _, flow, worker = workspace
    run = flow.submit(version, operation, settings)
    assert worker.run_one()
    result = flow.run(run["run_id"])
    assert result["status"] == "SUCCEEDED", result["error_message"]
    return result


def finding(report, code):
    return next(row for row in report["findings"] if row["rule_id"] == code)


@pytest.mark.parametrize("sample, rule, expected", [
    ("normal.glb", "UV_LAYER", "PASS"),
    ("missing_uv.glb", "UV_LAYER", "WARNING"),
    ("no_geometry.glb", "TRIANGLES", "FAIL"),
    ("missing_texture.zip", "FILE_REFERENCES", "FAIL"),
    ("over_budget.glb", "TRIANGLES", "FAIL"),
    ("multiple_meshes.glb", "MESH_OBJECTS", "PASS"),
])
def test_real_blender_inspects_each_fixture(workspace, samples, sample, rule, expected):
    library, _, _ = workspace
    asset = upload(workspace, samples / sample)
    version = asset["current_version_id"]
    execute(workspace, version, "inspect")
    report = library.detail(asset["asset_id"])["reports"][0]
    assert report["summary"]["adapter_mode"] == "BLENDER"
    issue = finding(report, rule)
    assert issue["status"] == expected, issue
    if sample == "over_budget.glb":
        assert issue["actual_value"] > issue["expected_value"]["max"]
    if sample == "multiple_meshes.glb":
        assert issue["actual_value"] > 1
    if sample == "missing_texture.zip":
        assert "mesh/albedo.png" in issue["evidence"]["missing"]
    if sample == "normal.glb":
        assert library.path(library.version(version)["preview_file"]).read_bytes()[:4] == b"glTF"


@pytest.mark.parametrize("target", ["GLB", "GLTF", "FBX", "OBJ"])
def test_real_roundtrip_and_recheck(workspace, samples, target):
    library, _, _ = workspace
    asset = upload(workspace, samples / "missing_uv.glb")
    parent = asset["current_version_id"]
    original = library.path(asset["versions"][0]["source_file"])
    params = {**OPTIONS, "operations": ["apply_transforms", "recalculate_normals", "smart_uv"], "target_format": target}
    run = execute(workspace, parent, "process", params)
    detail = library.detail(asset["asset_id"])
    child = detail["versions"][0]
    reports = {row["asset_version_id"]: row for row in detail["reports"]}
    assert child["file_format"] == target
    assert child["version_id"] == detail["current_version_id"] == run["output_version_id"]
    assert child["parent_version_id"] == parent
    assert child["version_number"] == 2
    baseline, = detail["baselines"]
    assert baseline["output_version_id"] == child["version_id"]
    assert finding(baseline, "UV_LAYER")["status"] == "WARNING"
    assert original.read_bytes() == (samples / "missing_uv.glb").read_bytes()
    assert finding(reports[parent], "UV_LAYER")["status"] == "WARNING"
    assert finding(reports[child["version_id"]], "UV_LAYER")["status"] == "PASS"
    assert finding(reports[child["version_id"]], "TRIANGLES")["actual_value"] > 0
    assert all(node["status"] == "SUCCEEDED" for node in run["nodes"])


@pytest.mark.parametrize("target", ["GLTF", "GLB", "FBX", "OBJ"])
def test_review_gates_export_and_textures_are_packaged(workspace, samples, target):
    library, flow, _ = workspace
    asset = upload(workspace, samples / "with_texture.zip")
    original_version = asset["current_version_id"]
    execute(workspace, original_version, "inspect")
    initial_report = library.detail(asset["asset_id"])["reports"][0]
    assert finding(initial_report, "IMAGE_DIMENSIONS")["actual_value"] == {"albedo.png": [32, 32]}
    process = execute(workspace, original_version, "process",
                      {**OPTIONS, "operations": ["recalculate_normals"], "target_format": target})
    version = process["output_version_id"]
    report = library.detail(asset["asset_id"])["reports"][0]
    assert not report["summary"]["counts"]["FAIL"], report
    assert 1 == finding(report, "IMAGE_TEXTURE")["actual_value"]
    assert [32, 32] in finding(report, "IMAGE_DIMENSIONS")["actual_value"].values()
    with pytest.raises(Conflict, match="审核"):
        flow.submit(version, "export")
    review = flow.review(version, report["report_id"], "Test reviewer", "APPROVED", "QA and texture verified.")
    exported = execute(workspace, version, "export")
    with ZipFile(flow.export_file(exported["run_id"])) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        lineage = json.loads(bundle.read("version_info.json"))
        history = json.loads(bundle.read("processing_history.json"))
        assert manifest["model"] == f"model/model.{target.lower()}"
        assert manifest["review_id"] == review["review_id"]
        assert manifest["engine_import_validation"] == "NOT_CHECKED"
        assert {row["version_id"] for row in lineage} == {original_version, version}
        assert any(row["run_id"] == process["run_id"] for row in history)
        assert json.loads(bundle.read("qa_report.json"))["report_id"] == report["report_id"]
        if target in {"GLTF", "OBJ"}:
            assert any(item["path"].endswith(".png") for item in manifest["files"])
        for item in manifest["files"]:
            assert sha256(bundle.read(item["path"])).hexdigest() == item["sha256"]
    flow.review(version, report["report_id"], "Test reviewer", "REJECTED", "Reopened")
    with pytest.raises(Conflict):
        flow.export_file(exported["run_id"])


def test_real_retry_after_blender_unavailable_and_restart(workspace, samples):
    library, flow, worker = workspace
    asset = upload(workspace, samples / "normal.glb")
    parent = asset["current_version_id"]
    job = flow.submit(parent, "inspect")
    assert Worker(library, BlenderAdapter(None, library.config)).run_one()
    assert flow.run(job["run_id"])["status"] == "FAILED"
    failed_report = library.detail(asset["asset_id"])["reports"][0]
    assert finding(failed_report, "FILE_PARSE")["status"] == "NOT_CHECKED"
    retry = flow.retry(job["run_id"])
    assert worker.claim()["run_id"] == retry["run_id"]
    restarted = Worker(library, worker.adapter)
    with restarted.exclusive() as acquired:
        assert acquired
        restarted.recover()
        assert restarted.run_one()
        assert not restarted.run_one()
    assert flow.run(retry["run_id"])["status"] == "SUCCEEDED"
    assert library.detail(asset["asset_id"])["reports"][0]["summary"]["metrics"]
