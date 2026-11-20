"""Generate original, reproducible Blender fixtures for the local workbench."""
from pathlib import Path
from zipfile import ZipFile
import sys

import bmesh
import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "artpipe/assetgate"))
from blender_script import export_model


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def material(name, color, metallic=0.0):
    result = bpy.data.materials.new(name)
    result.diffuse_color = (*color, 1.0)
    result.use_nodes = True
    shader = result.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*color, 1)
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Roughness"].default_value = 0.34
    return result


def block(name, location, dimensions, surface, *, uv=True, bevel=0.05):
    bpy.ops.mesh.primitive_cube_add(location=location, calc_uvs=uv)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        rounding = obj.modifiers.new("Edge bevel", "BEVEL")
        rounding.width = bevel
        rounding.segments = 2
        bpy.ops.object.modifier_apply(modifier=rounding.name)
    obj.data.materials.append(surface)
    return obj


def crate(*, uv):
    dark = material("Graphite", (0.11, 0.15, 0.20), 0.25)
    orange = material("Amber powder coat", (0.69, 0.22, 0.035), 0.19)
    trim = material("Steel", (0.38, 0.43, 0.49), 0.55)
    block("Chassis", (0, 0, .72), (2.65, 1.65, 1.30), dark, uv=uv, bevel=.10)
    for x in (-.89, .89):
        block("Top rail", (x, 0, 1.42), (.32, 1.8, .18), orange, uv=uv)
        block("Front brace", (x, -.86, .72), (.32, .18, 1.35), orange, uv=uv)
        block("Rear brace", (x, .86, .72), (.32, .18, 1.35), orange, uv=uv)
        for y in (-.57, .57):
            block("Foot", (x, y, .07), (.36, .36, .15), trim, uv=uv)
    block("Recessed label", (0, -.87, .78), (1.12, .12, .43), trim, uv=uv)
    for i in range(3):
        block("Front vent", (-.35 + .35*i, -.94, .78), (.16, .035, .22), dark, uv=uv, bevel=.016)


def write_texture_bundle(directory):
    # Use the same topology for the present and missing reference cases.
    obj = (
        "mtllib surface.mtl\no TexturedPanel\n"
        "v -1 0 -1\nv 1 0 -1\nv 1 0 1\nv -1 0 1\n"
        "vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\n"
        "usemtl Surface\nf 1/1 2/2 3/3 4/4\n"
    )
    mtl = "newmtl Surface\nKd 1 1 1\nmap_Kd albedo.png\n"
    image = bpy.data.images.new("Generated Checker", width=32, height=32, alpha=False)
    pixels = []
    for y in range(32):
        for x in range(32):
            pixels.extend((0.85, 0.33, 0.06, 1.0) if (x // 8 + y // 8) % 2 else (0.12, 0.18, 0.27, 1.0))
    image.pixels.foreach_set(pixels)
    image.file_format = "PNG"
    texture = directory / "albedo.png"
    image.filepath_raw = str(texture)
    image.save()
    for stem, include in (("with_texture", True), ("missing_texture", False)):
        with ZipFile(directory / f"{stem}.zip", "w") as bundle:
            bundle.writestr("mesh/panel.obj", obj)
            bundle.writestr("mesh/surface.mtl", mtl)
            if include:
                bundle.write(texture, "mesh/albedo.png")
    texture.unlink()


def main(directory):
    directory.mkdir(parents=True, exist_ok=True)
    reset()
    block("Reference cube", (0, 0, 0), (2.0, 2.0, 2.0), material("Reference matte", (.2, .36, .55)))
    export_model(directory / "normal.glb")

    reset()
    crate(uv=False)
    export_model(directory / "missing_uv.glb")

    reset()
    crate(uv=True)
    export_model(directory / "multiple_meshes.glb")

    reset()
    bpy.ops.object.camera_add(location=(3, 3, 3))
    export_model(directory / "no_geometry.glb")

    reset()
    mesh = bpy.data.meshes.new("Budget grid")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=227, y_segments=227, size=2)
    bm.to_mesh(mesh)
    bm.free()
    bpy.context.collection.objects.link(bpy.data.objects.new("Budget grid", mesh))
    export_model(directory / "over_budget.glb")
    write_texture_bundle(directory)


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:]
    main(Path(args[0]).resolve())
