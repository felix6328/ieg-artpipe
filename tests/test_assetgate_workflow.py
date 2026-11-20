from io import BytesIO
from shutil import copyfile

import pytest

from artpipe.assetgate.blender import BlenderError
from artpipe.assetgate.library import Library
from artpipe.assetgate.settings import load_settings
from artpipe.assetgate.worker import Worker
from artpipe.assetgate.workflow import Conflict, Workflow
from test_assetgate_qa import observed
from test_assetgate_storage import OBJ


class MockAdapter:
    """Unit-test adapter. It never runs in the local product."""

    mode = "MOCK"
    failed = False

    def inspect_model(self, job, source, canceled, **kwargs):
        if self.failed:
            raise BlenderError("Synthetic adapter failure")
        value = observed()
        target = kwargs.get("preview")
        if target:
            (job.output / target).write_bytes(b"MOCK PREVIEW")
            value["preview_ready"] = True
        return value

    def process_model(self, job, source, target, operation, settings, canceled):
        (job.output / target).parent.mkdir(exist_ok=True)
        copyfile(source, job.output / target)

    def export_model(self, job, source, target, canceled):
        (job.output / target).parent.mkdir(exist_ok=True)
        copyfile(source, job.output / target)


@pytest.fixture
def setup(tmp_path):
    library = Library(tmp_path, load_settings())
    asset = library.upload(BytesIO(OBJ), "mesh.obj", "", "model")
    return library, asset, Workflow(library), Worker(library, MockAdapter())


def test_failure_report_retry_and_recovery(setup):
    library, asset, workflow, worker = setup
    parent = asset["current_version_id"]
    queued = workflow.submit(parent, "inspect")
    assert workflow.submit(parent, "inspect")["run_id"] == queued["run_id"]
    worker.adapter.failed = True
    assert worker.run_one()
    failed = workflow.run(queued["run_id"])
    assert failed["status"] == "FAILED"
    assert failed["error_message"] == "Synthetic adapter failure"
    assert failed["nodes"][0]["status"] == "FAILED"
    failure_report = library.detail(asset["asset_id"])["reports"][0]
    assert failure_report["summary"]["counts"]["NOT_CHECKED"]
    retry = workflow.retry(failed["run_id"])
    assert retry["retry_of"] == failed["run_id"]
    assert worker.claim()["run_id"] == retry["run_id"]
    worker.adapter.failed = False
    worker.recover()
    assert worker.run_one()
    assert workflow.run(retry["run_id"])["status"] == "SUCCEEDED"
    assert not worker.run_one()
    assert library.detail(asset["asset_id"])["reports"][0]["summary"]["adapter_mode"] == "MOCK"


def test_processing_creates_immutable_version_and_stale_results(setup):
    library, asset, workflow, worker = setup
    parent = asset["current_version_id"]
    params = {"operations": ["smart_uv"], "target_format": "OBJ", "uv_angle_degrees": 66, "uv_island_margin": 0.02}
    queued = workflow.submit(parent, "process", params)
    assert worker.run_one()
    run = workflow.run(queued["run_id"])
    assert run["status"] == "SUCCEEDED", run["error_message"]
    assert [(node["name"], node["status"]) for node in run["nodes"]] == [
        ("inspect_source", "SUCCEEDED"), ("smart_uv", "SUCCEEDED"), ("convert", "SUCCEEDED"), ("recheck", "SUCCEEDED")]
    model = library.detail(asset["asset_id"])
    ver, original = model["versions"]
    assert (model["current_version_id"], ver["version_number"], ver["parent_version_id"]) == (ver["version_id"], 2, parent)
    assert library.path(original["source_file"]).read_bytes() == OBJ
    assert {row["asset_version_id"] for row in model["reports"]} == {parent, ver["version_id"]}
    with pytest.raises(Conflict, match="真实 Blender"):
        workflow.review(ver["version_id"], model["reports"][0]["report_id"], "tester", "APPROVED", "")
    workflow.select(parent)
    assert library.version(ver["version_id"])["freshness"] == "STALE"
    assert workflow.run(run["run_id"])["freshness"] == "STALE"
    with pytest.raises(Conflict, match="过时"):
        workflow.submit(ver["version_id"], "inspect")


def test_cancel_pending_and_single_worker_lock(setup):
    library, asset, workflow, worker = setup
    pending = workflow.submit(asset["current_version_id"], "inspect")
    assert workflow.cancel(pending["run_id"])["status"] == "CANCELED"
    assert not worker.run_one()
    with worker.exclusive() as lock:
        assert lock
        with Worker(library, MockAdapter()).exclusive() as duplicate:
            assert not duplicate
