from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, ZipInfo
import json
import stat

import pytest

from artpipe.assetgate.library import Library
from artpipe.assetgate.settings import load_settings
from artpipe.assetgate.storage import BadAsset, digest, references

OBJ = b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"


def archive(entries):
    output = BytesIO()
    with ZipFile(output, "w") as bundle:
        for name, data in entries:
            bundle.writestr(name, data)
    output.seek(0)
    return output


@pytest.fixture
def library(tmp_path):
    return Library(tmp_path, load_settings())


def test_upload_preserves_source_and_sha256(library):
    uploaded = library.upload(BytesIO(OBJ), "mesh.obj", "", "prop")
    version, = uploaded["versions"]
    stored = library.path(version["source_file"])
    assert uploaded["current_version_id"] == version["version_id"]
    assert stored.read_bytes() == OBJ
    assert version["file_hash"] == version["upload_hash"] == digest(stored)
    assert version["version_number"] == 1


@pytest.mark.parametrize("name", ["../outside.obj", "C:/mesh.obj", "dir/../../mesh.obj", "folder\\mesh.obj",
                                  "/absolute.obj", "link.obj"])
def test_rejects_zip_path_and_links(library, name):
    entry = ZipInfo(name)
    if name == "link.obj":
        entry.create_system = 3
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(BadAsset):
        library.upload(archive([(entry, OBJ)]), "model.zip", "", "")
    assert library.asset_list() == []


def test_missing_texture_is_recorded_and_escaping_reference_is_rejected(library):
    obj = b"mtllib mesh.mtl\n" + OBJ
    uploaded = library.upload(archive([("sub/mesh.obj", obj), ("sub/mesh.mtl", b"map_Kd -s 1 1 1 missing.png\n")]),
                              "package.zip", "", "")
    version = uploaded["versions"][0]
    source = library.path(version["source_file"])
    assert references(source, source.parents[1])["missing"] == ["sub/missing.png"]
    with pytest.raises(BadAsset):
        library.upload(archive([("mesh.obj", obj), ("mesh.mtl", b"map_Kd ../escape.png\n")]),
                       "package.zip", "", "")


def test_input_type_limit_and_multi_model_selection(library):
    limits = library.config["upload"]
    with pytest.raises(BadAsset):
        library.upload(BytesIO(b"junk"), "mesh.exe", "", "")
    with pytest.raises(BadAsset):
        library.upload(BytesIO(b"junk"), "mesh.glb", "", "")
    limits["max_bytes"] = 8
    with pytest.raises(BadAsset, match="大小"):
        library.upload(BytesIO(OBJ), "mesh.obj", "", "")
    limits["max_bytes"] = 10_000
    values = [("a.obj", OBJ), ("b.obj", OBJ)]
    with pytest.raises(BadAsset, match="主模型"):
        library.upload(archive(values), "model.zip", "", "")
    version = library.upload(archive(values), "model.zip", "", "", "b.obj")["versions"][0]
    assert Path(version["source_file"]).name == "b.obj"


def test_gltf_encoded_external_path_rejected(library):
    doc = {"asset": {"version": "2.0"}, "buffers": [{"uri": "%2e%2e%2fescape.bin"}]}
    with pytest.raises(BadAsset, match="外部"):
        library.upload(BytesIO(json.dumps(doc).encode()), "mesh.gltf", "", "")
