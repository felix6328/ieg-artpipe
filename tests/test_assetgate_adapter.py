import os

import pytest

from artpipe.assetgate.blender import BlenderAdapter, BlenderError, Job, JobCanceled, detect_blender
from artpipe.assetgate.settings import load_settings


def test_missing_blender_is_a_failure(tmp_path):
    adapter = BlenderAdapter(None, load_settings())
    with pytest.raises(BlenderError, match="未找到 Blender"):
        adapter.probe(Job(tmp_path))


@pytest.mark.parametrize("cancel", [False, True])
def test_subprocess_supports_timeout_and_cancel(tmp_path, cancel):
    fake = tmp_path / "child"
    fake.write_text("#!/bin/sh\nprintf 'started\\n'\nexec /bin/sleep 20\n")
    fake.chmod(0o700)
    config = load_settings()
    config["blender"]["probe_seconds"] = 2
    adapter = BlenderAdapter(fake, config)
    job = Job(tmp_path / "job")
    log = job.directory / "logs/probe.stdout.log"

    def canceled():
        return cancel and log.is_file() and "started" in log.read_text()

    if cancel:
        with pytest.raises(JobCanceled):
            adapter.probe(job, canceled)
    else:
        with pytest.raises(BlenderError, match="超时"):
            adapter.probe(job)
    assert "started" in (tmp_path / "job/logs/probe.stdout.log").read_text()


@pytest.mark.skipif(os.environ.get("ASSETGATE_REAL_TESTS") != "1", reason="real Blender opt-in")
def test_real_background_operator_probe(tmp_path):
    binary = detect_blender()
    assert binary is not None
    adapter = BlenderAdapter(binary, load_settings())
    assert adapter.get_blender_version().startswith("Blender ")
    probe = adapter.probe(Job(tmp_path))
    assert probe["background"] is True
    for suffix in ("GLB", "GLTF", "FBX", "OBJ"):
        assert probe["formats"][suffix]["import"]
        assert probe["formats"][suffix]["export"]
