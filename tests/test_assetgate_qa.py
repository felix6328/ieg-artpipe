from artpipe.assetgate.qa import run_qa
from artpipe.assetgate.settings import load_settings


def check(value, rule):
    return next(row for row in value["findings"] if row["rule_id"] == rule)


def observed():
    mesh = {"name": "Plane", "vertices": 3, "edges": 3, "faces": 1, "triangles": 1,
            "degenerate": 0, "non_manifold": 3, "isolated": 0, "invalid_vertices": 0,
            "slots": 0, "assigned_slots": 0,
            "uv": {"layers": 1, "coordinates": 3, "nonzero": 2, "outside": 2, "invalid": 0}}
    return {"version": "test", "metrics": {**mesh, "meshes": [mesh], "objects": 1,
                                           "materials": 0, "images": [], "missing_image_nodes": 0,
                                           "bounds": {"min": [0, 0, 0], "max": [1, 1, 0]}, "dimensions": [1, 1, 0]}}


def test_qa_does_not_mark_unmeasured_items_pass(tmp_path):
    model = tmp_path / "example.obj"
    model.write_text("o Empty\n")
    report = run_qa(model, tmp_path, load_settings(), error="Blender could not parse the file")
    assert check(report, "FILE_FORMAT")["status"] == "PASS"
    assert check(report, "FILE_PARSE")["status"] == "FAIL"
    assert check(report, "UV_VALID")["status"] == "NOT_CHECKED"
    assert check(report, "TRIANGLES")["status"] == "NOT_CHECKED"


def test_qa_configurable_thresholds_and_severity(tmp_path):
    model = tmp_path / "example.obj"
    model.write_text("o Plane\n")
    config = load_settings()
    report = run_qa(model, tmp_path, config, inspection=observed())
    assert check(report, "NON_MANIFOLD")["status"] == "WARNING"
    assert check(report, "UV_RANGE")["severity"] == "info"
    assert check(report, "MATERIAL_SLOTS")["status"] == "WARNING"
    config["rules"].update(uv_outside_severity="block", max_non_manifold_edges=3)
    report = run_qa(model, tmp_path, config, inspection=observed())
    assert check(report, "NON_MANIFOLD")["status"] == "PASS"
    assert check(report, "UV_RANGE")["status"] == "FAIL"
