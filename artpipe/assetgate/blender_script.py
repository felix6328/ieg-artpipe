"""Trusted entry point executed only inside the Blender Python interpreter."""
from pathlib import Path
import json
import re
import shutil
import sys

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blender_metrics import collect, images_in_tree
from blender_operations import process

OPERATORS = {
    "glb": (("import_scene.gltf",), ("export_scene.gltf",)),
    "gltf": (("import_scene.gltf",), ("export_scene.gltf",)),
    "fbx": (("import_scene.fbx",), ("export_scene.fbx",)),
    "obj": (("wm.obj_import", "import_scene.obj"), ("wm.obj_export", "export_scene.obj")),
}


class UnsupportedFormat(RuntimeError):
    """The required Blender operator is absent."""


def operator_name(choices):
    for choice in choices:
        group, name = choice.split(".")
        if name in dir(getattr(bpy.ops, group)):
            return choice
    return None


def invoke(name, **kwargs):
    group, action = name.split(".")
    op = getattr(getattr(bpy.ops, group), action)
    available = op.get_rna_type().properties.keys()
    result = op(**{key: value for key, value in kwargs.items() if key in available})
    if "FINISHED" not in result:
        raise RuntimeError(f"{name} ended with {result}")


def scoped_fbx_import(name, source, root, images):
    # The bundled FBX importer uses this centralized reader for image paths.
    # Supply exact, package-local copies and preserve placeholders for unresolved images.
    from bpy_extras import image_utils

    original = image_utils.load_image

    def load(path, dirname="", **kwargs):
        raw = str(path).replace("\\", "/")
        candidate = (Path(dirname or source.parent) / raw).resolve()
        if ":" in raw or not candidate.is_relative_to(root):
            image = bpy.data.images.new(Path(raw).name or "Missing texture", 1, 1)
            image.source = "FILE"
            images[image.as_pointer()] = {"path": Path(raw).name, "valid": False, "exists": False}
            return image
        relative = candidate.relative_to(root).as_posix()
        if candidate.is_file():
            try:
                image = bpy.data.images.load(str(candidate), check_existing=True)
            except RuntimeError:
                image = bpy.data.images.new(candidate.name, 1, 1)
                image.source = "FILE"
        else:
            image = bpy.data.images.new(candidate.name, 1, 1)
            image.source = "FILE"
        images[image.as_pointer()] = {"path": relative, "valid": True, "exists": candidate.is_file()}
        return image

    image_utils.load_image = load
    try:
        invoke(name, filepath=str(source), use_image_search=False, use_custom_props=False)
    finally:
        image_utils.load_image = original


def import_model(source, root):
    suffix = source.suffix.lower()[1:]
    if suffix == "blend":
        invoke("wm.open_mainfile", filepath=str(source), use_scripts=False)
        return {}
    name = operator_name(OPERATORS[suffix][0])
    if name is None:
        raise UnsupportedFormat(f"当前 Blender 不支持 {suffix.upper()} 的受限导入")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    images = {}
    if suffix == "fbx":
        scoped_fbx_import(name, source, root, images)
    else:
        invoke(name, filepath=str(source), use_image_search=False)
    bpy.context.view_layer.update()
    return images


def export_model(target):
    target.parent.mkdir(parents=True, exist_ok=True)
    suffix = target.suffix.lower()[1:]
    if suffix == "blend":
        invoke("file.pack_all")
        invoke("wm.save_as_mainfile", filepath=str(target), compress=True, relative_remap=False)
    else:
        name = operator_name(OPERATORS[suffix][1])
        if name is None:
            raise UnsupportedFormat(f"当前 Blender 不支持 {suffix.upper()} 导出")
        params = {"filepath": str(target), "check_existing": False}
        if suffix in {"glb", "gltf"}:
            params["export_format"] = "GLB" if suffix == "glb" else "GLTF_SEPARATE"
        elif suffix == "fbx":
            params.update(path_mode="COPY", embed_textures=True, add_leaf_bones=False)
        elif suffix == "obj":
            params.update(path_mode="RELATIVE")
        invoke(name, **params)
    if not target.is_file():
        raise RuntimeError(f"导出未生成 {target.name}")


def stage_obj_textures(target, source, workspace):
    """Write packed textures and point the OBJ exporter at the packaged copies."""
    materials = {slot.material for obj in bpy.context.scene.objects if obj.type == "MESH"
                 for slot in obj.material_slots if slot.material and slot.material.use_nodes}
    visited = set()
    images = {image for material in materials for image in images_in_tree(material.node_tree, visited) if image}
    extensions = {"JPEG": ".jpg", "TARGA": ".tga", "TARGA_RAW": ".tga", "OPEN_EXR": ".exr",
                  "JPEG2000": ".jp2", "TIFF": ".tif"}
    known = {".png", ".jpg", ".jpeg", ".tga", ".bmp", ".tiff", ".tif", ".exr", ".hdr", ".webp", ".dds", ".jp2"}
    for index, image in enumerate(sorted(images, key=lambda item: item.name), 1):
        name = Path(image.filepath or image.name).name
        extension = Path(name).suffix.lower()
        if extension not in known:
            extension = extensions.get(image.file_format, f".{image.file_format.lower()}")
        if extension not in known:
            raise RuntimeError(f"无法以 OBJ 封装贴图 {image.name}（{image.file_format}）")
        stem = re.sub(r"[^a-zA-Z0-9_-]+", "_", Path(name).stem) or "texture"
        path = target.parent / "textures" / f"{index:03d}-{stem}{extension.lower()}"
        path.parent.mkdir(parents=True, exist_ok=True)
        if image.packed_file:
            path.write_bytes(image.packed_file.data)
            image.unpack(method="REMOVE")
        else:
            candidates = [Path(bpy.path.abspath(image.filepath)).resolve(),
                          (source.parent / image.filepath.removeprefix("//")).resolve()]
            local = next((path for path in candidates if path.is_relative_to(workspace) and path.is_file()), None)
            if local:
                shutil.copyfile(local, path)
            elif image.has_data:
                image.save(filepath=str(path))
            else:
                continue
        image.filepath = str(path)


def main(request):
    action = request["action"]
    result = {"ok": True, "version": bpy.app.version_string, "background": bpy.app.background}
    if action == "probe":
        result["formats"] = {
            fmt.upper(): {"import": operator_name(importers), "export": operator_name(exporters)}
            for fmt, (importers, exporters) in OPERATORS.items()
        }
        return result
    source = Path(request["source"])
    workspace = Path(request["root"])
    # The first component under the job is the input/output boundary. Re-import
    # only sees the model bundle, not the job's other stages or logs.
    bundle = source.relative_to(workspace).parts[0]
    root = workspace / bundle
    try:
        imported_images = import_model(source, root)
    except Exception as exc:
        failure = {"ok": False, "error": str(exc), "parse_failed": not isinstance(exc, UnsupportedFormat)}
        Path(request["result"]).write_text(json.dumps(failure, ensure_ascii=False), encoding="utf-8")
        raise
    if action == "inspect":
        result["metrics"] = collect(source, root, imported_images, request.get("area_epsilon", 1e-12))
        if request.get("preview") and result["metrics"]["triangles"]:
            try:
                export_model(Path(request["preview"]))
                result["preview_ready"] = True
            except RuntimeError as exc:
                result["preview_error"] = str(exc)
    if action == "process":
        process(request["operation"], request["settings"])
    if action in {"process", "export"}:
        target = Path(request["target"])
        if target.suffix.lower() == ".obj":
            stage_obj_textures(target, source, workspace)
        export_model(target)
    return result


if __name__ == "__main__":
    arguments = sys.argv[sys.argv.index("--") + 1:]
    request = json.loads(Path(arguments[0]).read_text(encoding="utf-8"))
    value = main(request)
    Path(request["result"]).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
