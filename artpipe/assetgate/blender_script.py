"""Trusted entry point executed only inside the Blender Python interpreter."""
from pathlib import Path
import json
import sys

import bpy

OPERATORS = {
    "glb": (("import_scene.gltf",), ("export_scene.gltf",)),
    "gltf": (("import_scene.gltf",), ("export_scene.gltf",)),
    "fbx": (("import_scene.fbx",), ("export_scene.fbx",)),
    "obj": (("wm.obj_import", "import_scene.obj"), ("wm.obj_export", "export_scene.obj")),
}


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
            images[image.name] = {"path": Path(raw).name, "valid": False, "exists": False}
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
        images[image.name] = {"path": relative, "valid": True, "exists": candidate.is_file()}
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
        raise RuntimeError(f"当前 Blender 不支持 {suffix.upper()} 的受限导入")
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
        invoke("wm.save_as_mainfile", filepath=str(target), compress=True)
    else:
        name = operator_name(OPERATORS[suffix][1])
        if name is None:
            raise RuntimeError(f"当前 Blender 不支持 {suffix.upper()} 导出")
        params = {"filepath": str(target), "check_existing": False}
        if suffix in {"glb", "gltf"}:
            params["export_format"] = "GLB" if suffix == "glb" else "GLTF_SEPARATE"
        elif suffix == "fbx":
            params.update(path_mode="COPY", embed_textures=True, add_leaf_bones=False)
        elif suffix == "obj":
            params.update(path_mode="COPY")
        invoke(name, **params)
    if not target.is_file():
        raise RuntimeError(f"导出未生成 {target.name}")


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
    imported_images = import_model(source, root)
    if action == "export":
        export_model(Path(request["target"]))
    return result


if __name__ == "__main__":
    arguments = sys.argv[sys.argv.index("--") + 1:]
    request = json.loads(Path(arguments[0]).read_text(encoding="utf-8"))
    value = main(request)
    Path(request["result"]).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
