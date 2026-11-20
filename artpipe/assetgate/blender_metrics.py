"""Collect deterministic facts from the imported Blender scene."""
from math import isfinite
from pathlib import Path

import bmesh
import bpy


def topology(mesh):
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        return (
            sum(not edge.is_manifold for edge in bm.edges),
            sum(not edge.link_faces for edge in bm.edges) + sum(not vertex.link_edges for vertex in bm.verts),
        )
    finally:
        bm.free()


def inspect_uv(mesh):
    count = invalid = outside = nonzero = 0
    for layer in mesh.uv_layers:
        for datum in layer.uv if hasattr(layer, "uv") else layer.data:
            u, v = datum.vector if hasattr(datum, "vector") else datum.uv
            count += 1
            if not all(map(isfinite, (u, v))):
                invalid += 1
                continue
            nonzero += int(u != 0 or v != 0)
            outside += int(not (0 <= u <= 1 and 0 <= v <= 1))
    return {"layers": len(mesh.uv_layers), "coordinates": count, "invalid": invalid,
            "outside": outside, "nonzero": nonzero}


def images_in_tree(tree, visited):
    if tree is None or tree.as_pointer() in visited:
        return
    visited.add(tree.as_pointer())
    for node in tree.nodes:
        if node.type == "TEX_IMAGE":
            yield node.image
        elif node.type == "GROUP":
            yield from images_in_tree(node.node_tree, visited)


def image_fact(image, source, root, imported):
    width, height = image.size[:]
    if image.packed_file or image.source == "GENERATED":
        details = {"path": None, "valid": True, "exists": True}
    elif image.as_pointer() in imported:
        details = imported[image.as_pointer()]
    elif image.filepath:
        path = Path(bpy.path.abspath(image.filepath)).resolve()
        if not path.is_relative_to(root) and not Path(image.filepath).is_absolute():
            path = (source.parent / image.filepath.removeprefix("//")).resolve()
        inside = path.is_relative_to(root)
        details = {"path": path.relative_to(root).as_posix() if inside else path.name,
                   "valid": inside, "exists": inside and path.is_file()}
    elif width and height:
        details = {"path": None, "valid": True, "exists": True}
    else:
        details = {"path": None, "valid": False, "exists": False}
    return {"name": image.name, "width": width, "height": height, **details}


def collect(source, root, imported, area_epsilon):
    """Inspect mesh datablocks as stored, with world-space bounds."""
    objs = sorted((obj for obj in bpy.context.scene.objects if obj.type == "MESH"),
                  key=lambda obj: obj.name)
    low, high = [float("inf")] * 3, [float("-inf")] * 3
    by_object = []
    materials = set()
    for obj in objs:
        mesh = obj.data
        mesh.calc_loop_triangles()
        non_manifold, isolated = topology(mesh)
        invalid_vertices = 0
        for vertex in mesh.vertices:
            coords = obj.matrix_world @ vertex.co
            if not all(map(isfinite, coords)):
                invalid_vertices += 1
                continue
            for axis, coord in enumerate(coords):
                low[axis] = min(low[axis], coord)
                high[axis] = max(high[axis], coord)
        materials.update(slot.material for slot in obj.material_slots if slot.material is not None)
        by_object.append({
            "name": obj.name, "vertices": len(mesh.vertices), "edges": len(mesh.edges),
            "faces": len(mesh.polygons), "triangles": len(mesh.loop_triangles),
            "non_manifold": non_manifold, "isolated": isolated, "invalid_vertices": invalid_vertices,
            "degenerate": sum(not isfinite(p.area) or p.area <= area_epsilon for p in mesh.polygons),
            "uv": inspect_uv(mesh), "slots": len(obj.material_slots),
            "assigned_slots": sum(slot.material is not None for slot in obj.material_slots),
        })
    found_images = set()
    missing_image_nodes = 0
    visited = set()
    for material in materials:
        for image in images_in_tree(material.node_tree if material.use_nodes else None, visited):
            if image is None:
                missing_image_nodes += 1
            else:
                found_images.add(image)
    images = [image_fact(image, source, root, imported) for image in sorted(found_images, key=lambda image: image.name)]
    # FBX can load a referenced image before material assignment.
    present_names = {image["name"] for image in images}
    for image in sorted(bpy.data.images, key=lambda image: image.name):
        if image.as_pointer() in imported and image.name not in present_names:
            images.append(image_fact(image, source, root, imported))
    bounds = {"min": low, "max": high} if all(map(isfinite, low + high)) else None
    counts = {key: sum(row[key] for row in by_object) for key in (
        "vertices", "edges", "faces", "triangles", "non_manifold", "isolated",
        "invalid_vertices", "degenerate",
    )}
    return {
        **counts, "objects": len(objs), "meshes": by_object, "materials": len(materials),
        "images": images, "missing_image_nodes": missing_image_nodes, "bounds": bounds,
        "dimensions": [a - b for a, b in zip(high, low)] if bounds else None,
    }
