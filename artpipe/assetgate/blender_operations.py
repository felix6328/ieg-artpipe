"""Opt-in edits applied to a job's private Blender scene."""
from math import radians

import bmesh
import bpy


def process(operation, settings):
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.data.polygons]
    if not meshes:
        raise RuntimeError("模型没有可处理的网格面")
    bpy.ops.object.select_all(action="DESELECT")
    if operation == "apply_transforms":
        for obj in meshes:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = meshes[0]
        require_done(bpy.ops.object.transform_apply(location=True, rotation=True, scale=True, isolate_users=True))
    elif operation == "recalculate_normals":
        for data in {obj.data for obj in meshes}:
            bm = bmesh.new()
            try:
                bm.from_mesh(data)
                bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
                bm.to_mesh(data)
                data.update()
            finally:
                bm.free()
    elif operation == "smart_uv":
        for obj in meshes:
            if obj.data.users > 1:
                obj.data = obj.data.copy()
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            bpy.ops.object.mode_set(mode="EDIT")
            try:
                bpy.ops.mesh.select_all(action="SELECT")
                require_done(bpy.ops.uv.smart_project(angle_limit=radians(settings["uv_angle_degrees"]),
                                                      island_margin=settings["uv_island_margin"]))
            finally:
                bpy.ops.object.mode_set(mode="OBJECT")
                obj.select_set(False)
    else:
        raise RuntimeError(f"未知处理项：{operation}")


def require_done(result):
    if "FINISHED" not in result:
        raise RuntimeError(f"Blender 处理取消：{result}")
