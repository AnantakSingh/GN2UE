"""
import_gnue.py — build a parametric PCG graph in Unreal from a .gnue.json descriptor.

Runs inside Unreal's Python environment (no MCP involved):
  in-editor :  py "<repo>/ue_importer/import_gnue.py"
  headless  :  powershell -File ue_importer/run_import.ps1   (engine/project resolved
               by tools/gnue_paths.py), or by hand:
               UnrealEditor-Cmd.exe <project.uproject> -run=pythonscript
               -script="<repo>/ue_importer/import_gnue.py"
               (descriptor path via GNUE_DESCRIPTOR env var; defaults to
                ../export/spinetree.gnue.json next to this script)

Requires the PCG and Python Editor Script plugins enabled on the project.

Supported descriptor family: static_scatter (version 1.1)
  curve.random_walk  -> Create Points + Duplicate Point + Transform Points + Create Spline
  scatter.on_curve   -> Spline Sampler [+ Attribute Noise + Density Filter]
                        + Transform Points + Static Mesh Spawner

Known equivalence limits (same as the hand-built PCG_SpineTree, see export/README.md):
  - spine is per-point jitter, not an accumulated random walk (no prefix-sum in PCG)
  - expression values (segment_overlap) are baked from an estimated curve length
  - graph parameters are declared when the engine API allows it, but not yet wired
    to node properties (nodes are baked to descriptor defaults)
"""

import json
import math
import os
import sys

import unreal

M_TO_CM = 100.0
RAD_TO_DEG = 180.0 / math.pi

WARNINGS = []


def log(msg):
    unreal.log("[GNUE] " + str(msg))


def warn(msg):
    WARNINGS.append(str(msg))
    unreal.log_warning("[GNUE] " + str(msg))


def safe_set(obj, prop, value, ctx=""):
    """set_editor_property that records a warning instead of raising."""
    try:
        obj.set_editor_property(prop, value)
        return True
    except Exception as e:
        warn("could not set %s.%s (%s): %s" % (ctx or type(obj).__name__, prop, value, e))
        return False


# ---------------------------------------------------------------- descriptor

def load_descriptor(path):
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    if d.get("format") != "gnue-descriptor":
        raise RuntimeError("not a gnue-descriptor: %s" % path)
    return d


def param_table(desc):
    return {p["name"]: p["default"] for p in desc.get("parameters", [])}


def estimate_curve_length_m(curve_block, params):
    """Expected length of a random-walk curve: steps x |mean step vector|."""
    points = resolve(curve_block["points"], params, None)
    base = curve_block.get("base_step", [0, 0, 0])
    rnd = curve_block.get("step_random", {})
    scale = resolve(rnd.get("scale", 1.0), params, None)
    lo, hi = rnd.get("min", [0, 0, 0]), rnd.get("max", [0, 0, 0])
    mean = [base[i] + scale * (lo[i] + hi[i]) / 2.0 for i in range(3)]
    step_len = math.sqrt(sum(c * c for c in mean))
    return max(0.0, (points - 1) * step_len)


def resolve(src, params, curves):
    """Evaluate a descriptor valueSource to a plain number/list (Blender units)."""
    if isinstance(src, (int, float)):
        return src
    if isinstance(src, list):
        return src
    if isinstance(src, dict):
        if "param" in src:
            return params[src["param"]]
        if "expr" in src:
            expr = src["expr"]
            if expr == "add":
                return sum(resolve(v, params, curves) for v in src["of"])
            if expr == "max":
                return max(resolve(v, params, curves) for v in src["of"])
            if expr == "segment_overlap":
                curve = curves[src["curve_length_of"]]
                length = estimate_curve_length_m(curve["block"], params)
                count = resolve(src["count"], params, curves)
                overlap = src.get("overlap", 1.0)
                if count <= 1:
                    return length
                return overlap * length / (count - 1)
            raise RuntimeError("unsupported expr: %s" % expr)
    raise RuntimeError("unsupported valueSource: %r" % (src,))


# ---------------------------------------------------------------- unreal glue

def create_pcg_graph(package_path, asset_name):
    tools = unreal.AssetToolsHelpers.get_asset_tools()
    full = package_path + "/" + asset_name
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        log("deleting existing asset %s (re-import)" % full)
        unreal.EditorAssetLibrary.delete_asset(full)
    factory_cls = getattr(unreal, "PCGGraphFactory", None)
    if factory_cls is None:
        raise RuntimeError("unreal.PCGGraphFactory not found — is the PCG plugin enabled?")
    graph = tools.create_asset(asset_name, package_path, unreal.PCGGraph, factory_cls())
    if graph is None:
        raise RuntimeError("failed to create PCG graph asset at %s" % full)
    return graph


def add_node(graph, settings_cls, title, pos):
    """Add a PCG node; returns (node, settings)."""
    ret = graph.add_node_of_type(settings_cls)
    if isinstance(ret, tuple):
        node, settings = ret[0], ret[1]
    else:
        node = ret
        settings = node.get_editor_property("settings_interface").get_editor_property("settings")
    if node is None:
        raise RuntimeError("could not add node of type %s" % settings_cls.__name__)
    safe_set(node, "node_title", title, "PCGNode")
    try:
        node.set_node_position(int(pos[0]), int(pos[1]))
    except Exception as e:
        warn("set_node_position: %s" % e)
    return node, settings


EDGE_STATS = {"ok": 0, "fail": 0}


def pin_labels(node, prop):
    labels = []
    try:
        for pin in node.get_editor_property(prop):
            props = pin.get_editor_property("properties")
            labels.append(str(props.get_editor_property("label")))
    except Exception:
        pass
    return labels


def connect(graph, from_node, to_node, preferred_in=None, preferred_out=None):
    """Connect two nodes, resolving real pin labels from the nodes themselves."""
    outs = pin_labels(from_node, "output_pins") or ["Out"]
    ins = pin_labels(to_node, "input_pins") or ["In"]
    if preferred_out is not None and preferred_out in outs:
        out_l = preferred_out
    else:
        out_l = "Out" if "Out" in outs else outs[0]
    if preferred_in is not None and preferred_in in ins:
        in_l = preferred_in
    else:
        in_l = "In" if "In" in ins else ins[0]
    attempts = (
        lambda: from_node.add_edge_to(out_l, to_node, in_l),   # UE 5.8 API
        lambda: graph.add_edge(from_node, out_l, to_node, in_l),
        lambda: graph.add_edge(from_node, to_node),
    )
    last_err = None
    for attempt in attempts:
        try:
            if attempt() is not None:
                EDGE_STATS["ok"] += 1
                return True
        except Exception as e:
            last_err = e
    EDGE_STATS["fail"] += 1
    warn("connect %s(%s) -> %s(%s) failed: %s"
         % (from_node.get_name(), out_l, to_node.get_name(), in_l, last_err))
    return False


def import_fbx(fbx_path, dest_path, asset_name, force=False):
    full = dest_path + "/" + asset_name
    if unreal.EditorAssetLibrary.does_asset_exist(full) and not force:
        log("mesh already imported: %s" % full)
        return unreal.EditorAssetLibrary.load_asset(full)
    options = unreal.FbxImportUI()
    options.set_editor_property("import_mesh", True)
    options.set_editor_property("import_as_skeletal", False)
    options.set_editor_property("import_materials", False)
    options.set_editor_property("import_textures", False)
    options.static_mesh_import_data.set_editor_property("combine_meshes", True)
    task = unreal.AssetImportTask()
    task.set_editor_property("automated", True)
    task.set_editor_property("filename", fbx_path)
    task.set_editor_property("destination_path", dest_path)
    task.set_editor_property("destination_name", asset_name)
    task.set_editor_property("save", True)
    task.set_editor_property("replace_existing", True)
    task.set_editor_property("options", options)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    asset = unreal.EditorAssetLibrary.load_asset(full)
    if asset is None:
        raise RuntimeError("FBX import failed: %s -> %s" % (fbx_path, full))
    return asset


def make_two_sided_material(package_path, mesh_asset, color=(0.08, 0.35, 0.08)):
    """Gap #5 from export/README.md: leaf planes need a two-sided material."""
    name = "M_GNue_TwoSided"
    full = package_path + "/" + name
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(full):
            mat = unreal.EditorAssetLibrary.load_asset(full)
        else:
            tools = unreal.AssetToolsHelpers.get_asset_tools()
            mat = tools.create_asset(name, package_path, unreal.Material,
                                     unreal.MaterialFactoryNew())
            mel = unreal.MaterialEditingLibrary
            node = mel.create_material_expression(
                mat, unreal.MaterialExpressionConstant3Vector, -300, 0)
            node.set_editor_property("constant",
                                     unreal.LinearColor(color[0], color[1], color[2], 1.0))
            mel.connect_material_property(node, "", unreal.MaterialProperty.MP_BASE_COLOR)
            mat.set_editor_property("two_sided", True)
            mel.recompile_material(mat)
            unreal.EditorAssetLibrary.save_loaded_asset(mat)
        for i in range(mesh_asset.get_num_sections(0)):
            mesh_asset.set_material(i, mat)
        unreal.EditorAssetLibrary.save_loaded_asset(mesh_asset)
        log("two-sided material assigned to %s" % mesh_asset.get_name())
    except Exception as e:
        warn("two-sided material step failed (cosmetic only): %s" % e)


def declare_graph_parameters(graph, desc):
    """Best-effort: declare descriptor parameters on the PCG graph (gap #1).

    The property-bag add API is not exposed the same way across engine versions,
    so probe for known helper shapes and report what worked.
    """
    helpers = getattr(unreal, "PCGGraphParametersHelpers", None)
    if helpers is None:
        warn("PCGGraphParametersHelpers not available — parameters not declared")
        return
    adders = {n.lower(): n for n in dir(helpers)}

    def find_adder(*candidates):
        for c in candidates:
            if c in adders:
                return getattr(helpers, adders[c])
        return None

    add_float = find_adder("add_float_parameter", "add_double_parameter")
    add_int = find_adder("add_int32_parameter", "add_int_parameter", "add_int64_parameter")
    declared = 0
    for p in desc.get("parameters", []):
        name = p["name"].replace(" ", "")
        fn = add_int if p["type"] == "int" else add_float
        if fn is None:
            continue
        try:
            fn(graph, name, p["default"])
            declared += 1
        except Exception as e:
            warn("declare parameter %s failed: %s" % (name, e))
    if declared:
        log("declared %d/%d graph parameters (values still baked into nodes — wiring is TODO)"
            % (declared, len(desc.get("parameters", []))))
    else:
        warn("no graph parameters declared (no known add API on this engine version)")


# ---------------------------------------------------------------- block builders

def vec(v, s=1.0):
    return unreal.Vector(v[0] * s, v[1] * s, v[2] * s)


def build_random_walk_curve(graph, block, params, x, y):
    """curve.random_walk -> CreatePoints + DuplicatePoint + TransformPoints + CreateSpline.

    NOTE (statistical equivalence): the walk is realized as independent per-point
    jitter around a straight stack — PCG has no prefix-sum. See export/README.md #3.
    """
    points = int(resolve(block["points"], params, None))
    base_step_cm = [c * M_TO_CM for c in block.get("base_step", [0, 0, 0])]
    rnd = block.get("step_random", {})
    scale = resolve(rnd.get("scale", 1.0), params, None)
    jitter_min = [c * scale * M_TO_CM for c in rnd.get("min", [0, 0, 0])]
    jitter_max = [c * scale * M_TO_CM for c in rnd.get("max", [0, 0, 0])]

    origin, origin_s = add_node(graph, unreal.PCGCreatePointsSettings,
                                block["id"] + "_Origin", (x, y))
    try:
        pts = origin_s.get_editor_property("points_to_create")
        if len(pts) != 1:
            origin_s.set_editor_property("points_to_create", [unreal.PCGPoint()])
    except Exception as e:
        warn("CreatePoints points_to_create: %s" % e)

    stack, stack_s = add_node(graph, unreal.PCGDuplicatePointSettings,
                              block["id"] + "_Stack", (x + 250, y))
    safe_set(stack_s, "iterations", points - 1, "DuplicatePoint")
    # direction must stay (0,0,0): a non-zero direction adds the 100cm point
    # bounds to the spacing (export/README.md gotcha)
    safe_set(stack_s, "direction", unreal.Vector(0, 0, 0), "DuplicatePoint")
    safe_set(stack_s, "point_transform",
             unreal.Transform(location=base_step_cm), "DuplicatePoint")

    wander, wander_s = add_node(graph, unreal.PCGTransformPointsSettings,
                                block["id"] + "_Wander", (x + 500, y))
    safe_set(wander_s, "offset_min", vec(jitter_min), "TransformPoints")
    safe_set(wander_s, "offset_max", vec(jitter_max), "TransformPoints")
    safe_set(wander_s, "absolute_offset", False, "TransformPoints")

    spline, spline_s = add_node(graph, unreal.PCGCreateSplineSettings,
                                block["id"] + "_Spline", (x + 750, y))
    smooth = block.get("smooth", {})
    safe_set(spline_s, "linear", smooth.get("type") is None, "CreateSpline")

    connect(graph, origin, stack)
    connect(graph, stack, wander)
    connect(graph, wander, spline)
    return spline


def build_scatter_on_curve(graph, block, params, curves, spawn_meshes, x, y):
    """scatter.on_curve -> SplineSampler [+ noise/filter] + TransformPoints + Spawner."""
    count = int(resolve(block["count"], params, curves))
    spline_node = curves[block["curve"]]["node"]

    sampler, sampler_s = add_node(graph, unreal.PCGSplineSamplerSettings,
                                  block["id"] + "_Sampler", (x, y))
    try:
        sp = sampler_s.get_editor_property("sampler_params")
        safe_set(sp, "mode", unreal.PCGSplineSamplingMode.NUMBER_OF_SAMPLES, "SplineSamplerParams")
        safe_set(sp, "num_samples", count, "SplineSamplerParams")
        safe_set(sp, "unbounded", True, "SplineSamplerParams")
        if hasattr(unreal, "PCGSplineSamplingSeedingMode"):
            safe_set(sp, "seeding_mode",
                     unreal.PCGSplineSamplingSeedingMode.SEED_FROM_INDEX, "SplineSamplerParams")
        sampler_s.set_editor_property("sampler_params", sp)
    except Exception as e:
        warn("SplineSampler params: %s" % e)
    connect(graph, spline_node, sampler, preferred_in="Spline")
    tail = sampler

    sel = block.get("selection")
    if sel is not None:
        if sel.get("kind") != "random_bool":
            warn("unsupported selection kind %r — skipped" % sel.get("kind"))
        else:
            prob = float(resolve(sel["probability"], params, curves))
            noise, noise_s = add_node(graph, unreal.PCGAttributeNoiseSettings,
                                      block["id"] + "_Chance", (x + 250, y))
            safe_set(noise_s, "mode", unreal.PCGAttributeNoiseMode.SET, "AttributeNoise")
            safe_set(noise_s, "noise_min", 0.0, "AttributeNoise")
            safe_set(noise_s, "noise_max", 1.0, "AttributeNoise")
            # input defaults to $Density and output to @Source already, but pin
            # it explicitly via the selector's setter API
            try:
                selector = noise_s.get_editor_property("input_source")
                selector.set_point_property(unreal.PCGPointProperties.DENSITY)
                noise_s.set_editor_property("input_source", selector)
            except Exception as e:
                warn("AttributeNoise input_source selector: %s" % e)
            filt, filt_s = add_node(graph, unreal.PCGDensityFilterSettings,
                                    block["id"] + "_Filter", (x + 500, y))
            safe_set(filt_s, "lower_bound", 0.0, "DensityFilter")
            safe_set(filt_s, "upper_bound", prob, "DensityFilter")
            connect(graph, tail, noise)
            connect(graph, noise, filt)
            tail = filt

    xform, xform_s = add_node(graph, unreal.PCGTransformPointsSettings,
                              block["id"] + "_Transform", (x + 750, y))
    build_scatter_transform(xform_s, block, params, curves)
    connect(graph, tail, xform)

    spawner, spawner_s = add_node(graph, unreal.PCGStaticMeshSpawnerSettings,
                                  block["id"] + "_Spawner", (x + 1000, y))
    set_spawner_mesh(spawner_s, spawn_meshes[block["mesh"]])
    connect(graph, xform, spawner)


def build_scatter_transform(settings, block, params, curves):
    """Scale + rotation for a scatter block, in UE conventions.

    Axis mapping: the Spline Sampler aligns UE +X to the spline tangent, while the
    descriptor's align axis is Blender's; the tangent-axis scale component
    therefore lands on UE X (verified against the hand-built graph).
    """
    scale = block.get("scale", {})
    if "uniform" in scale:
        s = float(resolve(scale["uniform"], params, curves))
        safe_set(settings, "absolute_scale", True, "TransformPoints")
        safe_set(settings, "uniform_scale", True, "TransformPoints")
        safe_set(settings, "scale_min", unreal.Vector(s, s, s), "TransformPoints")
        safe_set(settings, "scale_max", unreal.Vector(s, s, s), "TransformPoints")
    elif scale:
        sx = float(resolve(scale.get("x", 1.0), params, curves))
        sy = float(resolve(scale.get("y", 1.0), params, curves))
        sz = float(resolve(scale.get("z", 1.0), params, curves))
        align = block.get("align", {})
        if align.get("to") == "tangent":
            tangent = {"x": sx, "y": sy, "z": sz}[align.get("axis", "z")]
            others = [v for a, v in (("x", sx), ("y", sy), ("z", sz))
                      if a != align.get("axis", "z")]
            ue_scale = unreal.Vector(tangent, others[0], others[1])
        else:
            ue_scale = unreal.Vector(sx, sy, sz)
        safe_set(settings, "absolute_scale", True, "TransformPoints")
        safe_set(settings, "uniform_scale", False, "TransformPoints")  # defaults True: would silently use X for all axes
        safe_set(settings, "scale_min", ue_scale, "TransformPoints")
        safe_set(settings, "scale_max", ue_scale, "TransformPoints")

    rot = block.get("rotation")
    if rot is not None:
        if rot.get("kind") != "random_euler":
            warn("unsupported rotation kind %r — skipped" % rot.get("kind"))
            return
        yaw = rot.get("yaw", {})
        tilt = rot.get("tilt", {})
        t_min = tilt.get("min", [0, 0, 0])
        t_max = tilt.get("max", [0, 0, 0])
        # Blender euler (x, y, z) -> UE (roll, pitch, yaw)
        rot_min = unreal.Rotator(roll=t_min[0] * RAD_TO_DEG,
                                 pitch=t_min[1] * RAD_TO_DEG,
                                 yaw=yaw.get("min", 0.0) * RAD_TO_DEG)
        rot_max = unreal.Rotator(roll=t_max[0] * RAD_TO_DEG,
                                 pitch=t_max[1] * RAD_TO_DEG,
                                 yaw=yaw.get("max", 0.0) * RAD_TO_DEG)
        safe_set(settings, "absolute_rotation", rot.get("replaces_alignment", False),
                 "TransformPoints")
        safe_set(settings, "rotation_min", rot_min, "TransformPoints")
        safe_set(settings, "rotation_max", rot_max, "TransformPoints")


def set_spawner_mesh(spawner_settings, mesh_asset, material=None):
    """Mutate the spawner's DefaultSelectorInstance in place — the
    mesh_selector_parameters property itself is read-only (same object the MCP
    path reached via ObjectTools; see export/README.md). `material` overrides
    slot 0 on every spawned instance (the GNue dynamics material)."""
    try:
        spawner_settings.set_mesh_selector_type(unreal.PCGMeshSelectorWeighted)
        selector = spawner_settings.get_editor_property("mesh_selector_parameters")
        entry = unreal.PCGMeshSelectorWeightedEntry()
        descriptor = entry.get_editor_property("descriptor")
        descriptor.set_editor_property("static_mesh", mesh_asset)
        if material is not None:
            try:
                descriptor.set_editor_property("override_materials", [material])
            except Exception as e:
                warn("spawner material override: %s" % e)
        entry.set_editor_property("descriptor", descriptor)
        safe_set(entry, "weight", 1, "MeshSelectorWeightedEntry")
        selector.set_editor_property("mesh_entries", [entry])
        readback = selector.get_editor_property("mesh_entries")
        if len(readback) != 1:
            raise RuntimeError("mesh_entries readback length %d" % len(readback))
        log("spawner mesh set: %s" % mesh_asset.get_name())
    except Exception as e:
        warn("StaticMeshSpawner mesh assignment failed for %s: %s"
             % (mesh_asset.get_name(), e))


# ---------------------------------------------------------------- families

def build_static_scatter(graph, desc, params, spawn_meshes):
    curves = {}
    y = 0
    for block in desc["blocks"]:
        if block["type"] == "curve.random_walk":
            node = build_random_walk_curve(graph, block, params, 0, y)
            curves[block["id"]] = {"node": node, "block": block}
            y += 300
    for block in desc["blocks"]:
        if block["type"] == "scatter.on_curve":
            build_scatter_on_curve(graph, block, params, curves, spawn_meshes, 1100, y)
            y += 300
        elif block["type"] != "curve.random_walk":
            warn("unsupported block type %r — skipped (conservative import)" % block["type"])


FAMILY_BUILDERS = {"static_scatter": build_static_scatter}


# ---------------------------------------------------------------- main

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_desc = os.path.normpath(os.path.join(script_dir, "..", "export", "spinetree.gnue.json"))
    desc_path = os.environ.get("GNUE_DESCRIPTOR") or (sys.argv[1] if len(sys.argv) > 1 else default_desc)
    desc = load_descriptor(desc_path)

    family = desc.get("family")
    builder = FAMILY_BUILDERS.get(family)
    if builder is None:
        raise RuntimeError("unsupported descriptor family %r (supported: %s)"
                           % (family, ", ".join(FAMILY_BUILDERS)))

    node_group = desc.get("source", {}).get("node_group", "GNueEffect")
    root = os.environ.get("GNUE_DEST", "/Game/GNueImport/" + node_group)
    graph_name = "PCG_" + node_group
    log("descriptor: %s (family %s) -> %s/%s" % (desc_path, family, root, graph_name))

    params = param_table(desc)

    spawn_meshes = {}
    desc_dir = os.path.dirname(os.path.abspath(desc_path))
    for m in desc.get("meshes", []):
        fbx = os.path.join(desc_dir, m["file"])
        if not os.path.isfile(fbx):
            raise RuntimeError("mesh file missing: %s" % fbx)
        asset_name = os.path.splitext(os.path.basename(m["file"]))[0]
        spawn_meshes[m["id"]] = import_fbx(fbx, root + "/Meshes", asset_name)
        log("mesh %r -> %s" % (m["id"], spawn_meshes[m["id"]].get_path_name()))

    # leaf-style thin planes need a two-sided material or they render dark
    if "leaf" in spawn_meshes:
        make_two_sided_material(root + "/Meshes", spawn_meshes["leaf"])

    graph = create_pcg_graph(root, graph_name)
    builder(graph, desc, params, spawn_meshes)
    declare_graph_parameters(graph, desc)

    nodes = graph.get_editor_property("nodes")
    unreal.EditorAssetLibrary.save_loaded_asset(graph)

    if EDGE_STATS["fail"]:
        result = "FAIL"
    elif WARNINGS:
        result = "PASS_WITH_WARNINGS"
    else:
        result = "PASS"
    print("GNUE IMPORT RESULT: %s" % result)
    print("GNUE graph: %s (%d nodes, %d/%d edges)"
          % (graph.get_path_name(), len(nodes),
             EDGE_STATS["ok"], EDGE_STATS["ok"] + EDGE_STATS["fail"]))
    for w in WARNINGS:
        print("GNUE WARNING: %s" % w)


if __name__ == "__main__":
    main()
