"""Map file evidence and Blender measurements to deterministic findings."""
from .storage import BadAsset, validate_model

STATUSES = ("PASS", "FAIL", "WARNING", "NOT_CHECKED")
SEVERITIES = {"block", "warning", "info"}


def run_qa(model, package, config, *, inspection=None, error=None, parse_failed=False):
    settings = config["rules"]
    results = []
    observed = inspection["metrics"] if inspection else None

    def rule(code, name, severity, ok, actual, expected, evidence, suggestion):
        if severity not in SEVERITIES:
            raise ValueError(f"规则 {code} 的严重程度无效：{severity}")
        status = "NOT_CHECKED" if ok is None else "PASS" if ok else "FAIL" if severity == "block" else "WARNING"
        results.append(dict(rule_id=code, rule_name=name, severity=severity, status=status, actual_value=actual,
                            expected_value=expected, evidence=evidence, suggestion=suggestion))

    here = model.relative_to(package).as_posix()
    exists = model.is_file()
    rule("FILE_EXISTS", "模型文件存在", "block", exists, exists, True, here, "重新上传源文件。")
    byte_count = model.stat().st_size if exists else None
    max_bytes = settings["max_file_bytes"]
    rule("FILE_SIZE", "模型文件大小", "block", 0 < byte_count <= max_bytes if exists else None,
         byte_count, {"max_bytes": max_bytes}, here, "检查源文件并按项目大小预算重新交付。")
    ref = None
    format_error = None
    if exists:
        try:
            ref = validate_model(model, package)
        except (BadAsset, OSError) as exc:
            format_error = str(exc)
    rule("FILE_FORMAT", "模型文件格式", "block", format_error is None if exists else None,
         model.suffix.upper(), "GLB / glTF / FBX / OBJ", format_error or here, "重新导出为有效的模型格式。")
    parsed = True if inspection else False if parse_failed else None
    rule("FILE_PARSE", "Blender 导入", "block", parsed, parsed, True,
         error or (inspection["version"] if inspection else "等待 Blender 检查"),
         "查看任务日志，检查模型结构与此 Blender 构建的格式支持。")
    images = observed["images"] if observed is not None else None
    invalid_image = [entry for entry in images or [] if not entry["valid"] or not entry["exists"]]
    # FBX dependencies are discovered by its importer. Other package paths are preflighted.
    checked_refs = ref is not None and (model.suffix.lower() != ".fbx" or images is not None)
    missing = (ref or {}).get("missing", [])
    rule("FILE_REFERENCES", "包内文件引用", "block", not (missing or invalid_image) if checked_refs else None,
         len(missing) + len(invalid_image) if checked_refs else None, 0,
         {"missing": missing, "image_issues": invalid_image}, "将依赖放入 ZIP，并使用包内相对路径。")

    meshes = observed["meshes"] if observed else []
    mesh_count = observed["objects"] if observed else None
    rule("MESH_OBJECTS", "网格对象数量", "block", mesh_count > 0 if observed else None,
         mesh_count, {"min": 1}, [mesh["name"] for mesh in meshes], "导出至少一个网格对象。")
    for key, label in (("vertices", "顶点数量"), ("edges", "边数量"), ("faces", "面数量")):
        value = observed[key] if observed else None
        rule(key.upper(), label, "block", value > 0 if observed else None, value, {"min": 1},
             {mesh["name"]: mesh[key] for mesh in meshes}, "确认网格包含有效的可交付几何。")
    tri = observed["triangles"] if observed else None
    rule("TRIANGLES", "三角面数预算", "block", 0 < tri <= settings["max_triangles"] if observed else None,
         tri, {"min": 1, "max": settings["max_triangles"]}, {m["name"]: m["triangles"] for m in meshes},
         "确认预算，必要时在 DCC 中制作低面数版本。")
    bbox = observed["bounds"] if observed else None
    dims = observed["dimensions"] if observed else None
    rule("BOUNDING_BOX", "世界空间包围盒", "block", bool(bbox) if observed else None, bbox, "有限坐标",
         bbox, "检查模型尺度与无效坐标。")
    rule("DIMENSIONS", "世界空间尺寸", "info", True if dims is not None else None, dims, "XYZ 尺寸",
         "单位为 Blender 场景单位", "按目标项目确认单位和比例。")
    empty = [m["name"] for m in meshes if not m["faces"] or not m["vertices"]]
    rule("EMPTY_MESH", "空网格", "block", not empty if meshes else None, len(empty) if meshes else None,
         0, empty, "移除空对象或补全可用的面。")
    for key, code, label, threshold, severity, advice in (
        ("non_manifold", "NON_MANIFOLD", "非流形边", "max_non_manifold_edges",
         settings["non_manifold_severity"], "核对开放边界是否有意保留。"),
        ("degenerate", "DEGENERATE", "退化面", "max_degenerate_faces", "warning", "清理零面积和重复面。"),
        ("isolated", "ISOLATED", "孤立顶点与边", "max_isolated_geometry", "warning", "检查无面边和未连接顶点。"),
        ("invalid_vertices", "INVALID_VERTICES", "无效顶点坐标", None, "block", "修复非有限坐标。"),
    ):
        count = observed[key] if meshes else None
        limit = settings[threshold] if threshold else 0
        rule(code, label, severity, count <= limit if meshes else None, count, {"max": limit},
             {m["name"]: m[key] for m in meshes if m[key]}, advice)

    surfaces = [m for m in meshes if m["faces"]]
    missing_uv = [m["name"] for m in surfaces if not m["uv"]["layers"]]
    with_uv = [m for m in surfaces if m["uv"]["layers"]]
    empty_uv = {m["name"]: m["uv"]["empty_layers"] for m in with_uv if m["uv"]["empty_layers"]}
    rule("UV_LAYER", "UV 图层", settings["missing_uv_severity"], not missing_uv if surfaces else None,
         len(missing_uv) if surfaces else None, 0, missing_uv, "添加 UV，或运行 Smart UV 后人工检查。")
    rule("UV_EMPTY", "空 UV 图层", "warning", not empty_uv if with_uv else None,
         sum(map(len, empty_uv.values())) if with_uv else None, 0, empty_uv, "确认 UV 没有全部压在原点。")
    for key, code, label, severity, limit, advice in (
        ("invalid", "UV_VALID", "UV 坐标有效性", "block", 0, "修正非有限 UV 坐标。"),
        ("outside", "UV_RANGE", "UV 越界", settings["uv_outside_severity"], settings["max_uv_outside"],
         "确认越界属于预期的平铺或 UDIM 布局。"),
    ):
        sampled = [m for m in with_uv if m["uv"]["coordinates"]]
        count = sum(m["uv"][key] for m in sampled) if sampled else None
        rule(code, label, severity, count <= limit if sampled else None, count, {"max": limit},
             {m["name"]: m["uv"][key] for m in sampled if m["uv"][key]}, advice)

    material_count = observed["materials"] if observed else None
    rule("MATERIALS", "材质数量", settings["missing_material_severity"],
         material_count > 0 if surfaces else None, material_count, {"min": 1},
         [m["name"] for m in surfaces if not m["assigned_slots"]], "按交付要求分配材质。")
    unassigned = [m["name"] for m in surfaces if not m["assigned_slots"]]
    rule("MATERIAL_SLOTS", "材质槽", settings["missing_material_severity"], not unassigned if surfaces else None,
         {m["name"]: m["slots"] for m in surfaces} if surfaces else None, "每个面网格至少一个已分配槽",
         unassigned, "核对网格是否分配了正确材质。")
    tex_count = len(images) if images is not None else None
    bad_nodes = observed["missing_image_nodes"] if observed else None
    rule("IMAGE_TEXTURE", "图像贴图", "info", bool(images and not bad_nodes) if material_count else None,
         tex_count, {"min": 1, "empty_nodes": 0}, {"empty_nodes": bad_nodes, "images": images},
         "若项目要求贴图，检查图像纹理节点是否绑定图片。")
    for key, code, name, advice in (
        ("valid", "IMAGE_PATH", "贴图路径", "将路径改为包内相对引用。"),
        ("exists", "IMAGE_EXISTS", "贴图文件", "将贴图文件补入资产包或嵌入模型。"),
    ):
        bad = [image for image in images or [] if not image[key]]
        rule(code, name, "block", not bad if images else None, len(bad) if images else None, 0, bad, advice)
    sizes = [image for image in images or [] if image["width"] and image["height"]]
    cap = settings["max_texture_dimension"]
    oversized = any(max(image["width"], image["height"]) > cap for image in sizes)
    dimension_ok = False if oversized else True if images and len(sizes) == len(images) else None
    rule("IMAGE_DIMENSIONS", "图片尺寸", "warning", dimension_ok,
         {image["name"]: [image["width"], image["height"]] for image in sizes} if sizes else None,
         {"max_side": cap}, {"unavailable": [im["name"] for im in images or [] if im not in sizes]},
         "核对贴图分辨率，并确认无法解码的图片。")

    counts = {state: sum(r["status"] == state for r in results) for state in STATUSES}
    return {"ruleset_version": config["ruleset_version"], "findings": results,
            "summary": {"counts": counts, "metrics": observed, "blender_version": inspection["version"]
                        if inspection else None, "preview_error": inspection.get("preview_error")
                        if inspection else None}}
