"""bpy-side frontend: node-group -> IR, unit-cube/asset baking, export driver.

Only this module (and the UI) touches bpy; core.py stays pure Python so the
lowering rules are testable outside Blender.
"""

import json
import os

import bpy

from . import core

# props that carry translation-relevant semantics (read by name, missing ok —
# guards against Blender version drift; the manifest records the version)
PROP_NAMES = ("operation", "data_type", "domain", "mode", "spline_type", "input_type",
              "axis", "pivot_axis", "distribute_method", "vector", "boolean", "integer",
              "transform_space")


def _plain(v):
    if isinstance(v, (int, float, bool, str)) or v is None:
        return v
    try:
        return list(v)          # vectors/colors
    except TypeError:
        # datablock references (Object/Material/...) export as their name
        name = getattr(v, "name", None)
        return name if isinstance(name, str) else None


def _sock_value(s):
    if not hasattr(s, "default_value"):
        return None
    return _plain(s.default_value)


def _resolve(link):
    """Follow a link back through reroutes to the real source socket."""
    fr, sock = link.from_node, link.from_socket
    seen = 0
    while fr.bl_idname == "NodeReroute" and seen < 64:
        inp = fr.inputs[0]
        if not inp.links:
            return None
        fr, sock = inp.links[0].from_node, inp.links[0].from_socket
        seen += 1
    return {"node": fr.name, "socket": sock.name}


def read_group(ng):
    """Blender node group -> IR dict (see core.py docstring for the shape)."""
    ir = {"blender_version": bpy.app.version_string,
          "blend_file": bpy.data.filepath,
          "node_group": ng.name,
          "params": [], "nodes": {}, "output_node": None}

    for item in ng.interface.items_tree:
        if getattr(item, "item_type", "") != "SOCKET" or item.in_out != "INPUT":
            continue
        stype = item.socket_type.replace("NodeSocket", "").upper()
        if stype == "GEOMETRY":
            continue
        p = {"name": item.name, "type": stype,
             "default": _plain(getattr(item, "default_value", None))}
        for a in ("min_value", "max_value"):
            v = getattr(item, a, None)
            if isinstance(v, (int, float)) and abs(v) < 1e17:
                p[a.replace("_value", "")] = v
        ir["params"].append(p)

    for nd in ng.nodes:
        if nd.bl_idname == "NodeReroute":
            continue
        rec = {"idname": nd.bl_idname, "muted": bool(nd.mute), "props": {}, "inputs": [], "outputs": []}
        for pn in PROP_NAMES:
            if hasattr(nd, pn):
                v = _plain(getattr(nd, pn))
                rec["props"][pn] = v if v is not None else str(getattr(nd, pn))
        if nd.bl_idname == "GeometryNodeCaptureAttribute":
            rec["props"]["capture_items"] = [
                {"name": it.name, "data_type": getattr(it, "data_type", "FLOAT")}
                for it in getattr(nd, "capture_items", [])]
        for i, s in enumerate(nd.inputs):
            links = [l for l in (_resolve(lk) for lk in s.links) if l]
            si = {"name": s.name, "idx": i, "type": s.type,
                  "enabled": bool(getattr(s, "enabled", True)),
                  "linked": bool(links), "links": links}
            if not links:
                si["value"] = _sock_value(s)
            rec["inputs"].append(si)
        for i, s in enumerate(nd.outputs):
            rec["outputs"].append({"name": s.name, "idx": i, "type": s.type})
        ir["nodes"][nd.name] = rec
        if nd.bl_idname == "NodeGroupOutput":
            ir["output_node"] = nd.name
    return ir


# ------------------------------------------------------------------ baking

def _export_fbx(obj, path):
    for o in bpy.data.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.fbx(filepath=path, use_selection=True,
                             apply_scale_options="FBX_SCALE_ALL",
                             bake_space_transform=True, use_mesh_modifiers=True,
                             add_leaf_bones=False)


def bake_unit_cube(path, origin):
    """SM_GNue_UnitCube*.fbx — 1m cube, center or bottom origin.

    Uses Blender's cube primitive so winding/normals/UVs are correct —
    hand-listed from_pydata faces shipped inverted normals (UE showed back
    faces only)."""
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.0))
    obj = bpy.context.active_object
    obj.name = "GNueUnitCube"
    if origin == "bottom":
        for v in obj.data.vertices:
            v.co.z += 0.5
    mesh = obj.data
    try:
        _export_fbx(obj, path)
    finally:
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)


def bake_subgraph(ng, source_node, path, sess):
    """Evaluate an instance-source subtree at current parameter defaults via a
    temp copy of the group rewired to output that node, then FBX the result."""
    tmp = ng.copy()
    tmp.name = "__gnue_bake"
    try:
        out = next(n for n in tmp.nodes if n.bl_idname == "NodeGroupOutput")
        src = tmp.nodes.get(source_node)
        if src is None:
            raise core.ExportRefused("bake: node %r missing in copy" % source_node)
        geo_out = next(s for s in src.outputs if s.type == "GEOMETRY")
        for l in list(out.inputs[0].links):
            tmp.links.remove(l)
        tmp.links.new(geo_out, out.inputs[0])

        mesh = bpy.data.meshes.new("__gnue_bake_mesh")
        obj = bpy.data.objects.new("__gnue_bake_obj", mesh)
        bpy.context.collection.objects.link(obj)
        mod = obj.modifiers.new("bake", "NODES")
        mod.node_group = tmp
        deps = bpy.context.evaluated_depsgraph_get()
        try:
            _export_fbx(obj, path)
        finally:
            bpy.data.objects.remove(obj)
            bpy.data.meshes.remove(mesh)
    finally:
        bpy.data.node_groups.remove(tmp)


# ------------------------------------------------------------------ driver


def _host_object(ng):
    """The object whose GN modifier runs this group (the scatter surface)."""
    for obj in bpy.data.objects:
        for m in obj.modifiers:
            if m.type == "NODES" and getattr(m, "node_group", None) == ng:
                return obj
    return None


def _pre_gn_mesh(obj, ng):
    """The mesh exactly as it enters the GN modifier: evaluate the object with
    the GN modifier (and everything after it) disabled, so bends/solidify/etc.
    that Blender's Distribute-on-Faces actually sampled are baked in."""
    saved = []
    hit = False
    for m in obj.modifiers:
        if not hit and m.type == "NODES" and getattr(m, "node_group", None) == ng:
            hit = True
        if hit:
            saved.append((m, m.show_viewport, m.show_render))
            m.show_viewport = m.show_render = False
    try:
        deps = bpy.context.evaluated_depsgraph_get()
        ev = obj.evaluated_get(deps)
        me = bpy.data.meshes.new_from_object(
            ev, preserve_all_data_layers=False, depsgraph=deps)
    finally:
        for m, sv, sr in saved:
            m.show_viewport, m.show_render = sv, sr
    return me


def _recalc_outward(me):
    """Consistent outward normals — user meshes often carry flipped faces,
    which would render the surface inside-out in UE and grow the scattered
    instances into the mesh instead of out of it."""
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(me)
    bm.free()


def _maybe_bake_surface(ng, descriptor, out_dir, sess):
    """If the effect scatters on the group-input mesh and that mesh is shaped
    (not just a flat ground plane), bake it to meshes/SM_GNue_Surface.fbx so
    UE can sample the same surface. Flat hosts keep the ground-sampling
    translation (the UE level's own floor plays the terrain's part)."""
    import math
    if not any(b["type"] == "scatter.on_surface" and b.get("surface_kind") == "input"
               for b in descriptor["blocks"]):
        return
    obj = _host_object(ng)
    if obj is None or obj.type != "MESH":
        return
    me = _pre_gn_mesh(obj, ng)
    try:
        _recalc_outward(me)
        me.calc_loop_triangles()
        cos_lim = math.cos(math.radians(25.0))
        up_area = total = 0.0
        for tri in me.loop_triangles:
            a = tri.area
            total += a
            if tri.normal.z >= cos_lim:
                up_area += a
        if total <= 0.0 or (up_area / total) >= 0.9:
            return  # flat ground -> UE floor stands in for it (status quo)
        if len(me.loop_triangles) > 50000:
            sess.warn("surface mesh %r has %d tris — not exported (over 50k cap); "
                      "scatter falls back to the UE ground"
                      % (obj.name, len(me.loop_triangles)))
            return
        tris = len(me.loop_triangles)
        path = os.path.join(out_dir, "meshes", "SM_GNue_Surface.fbx")
        dup = bpy.data.objects.new("SM_GNue_Surface", me)
        bpy.context.scene.collection.objects.link(dup)
        dup.matrix_world = obj.matrix_world.copy()
        dup.matrix_world.translation = (0, 0, 0)
        try:
            _export_fbx(dup, path)
        finally:
            bpy.data.objects.remove(dup)
        descriptor["surface_asset"] = {"file": "meshes/SM_GNue_Surface.fbx",
                                       "name": "SM_GNue_Surface",
                                       "tris": tris}
        sess.warn("scatter surface %r exported as SM_GNue_Surface.fbx (evaluated "
                  "through its modifier stack, normals made outward) — the effect "
                  "carries its own surface into UE" % obj.name)
    finally:
        if me is not None and me.users == 0:
            bpy.data.meshes.remove(me)


def export_group(ng, out_dir):
    """Full pipeline: read -> validate -> lower -> bake -> emit. Returns
    (ok, report_text, descriptor|None)."""
    sess = core.Session()
    ir = read_group(ng)
    try:
        lowered = core.lower(ir, sess)
    except core.ExportRefused as e:
        # lowering-time refusals carry their reason in the exception
        msg = str(e)
        if msg and msg != "validation failed" and msg not in sess.errors:
            sess.errors.append(msg)
        report = core.make_report(ir, None, sess, refused=True)
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, "export_report.txt"), "w", encoding="utf-8") as f:
            f.write(report)
        return False, report, None

    descriptor = core.make_descriptor(ir, lowered, sess)
    os.makedirs(os.path.join(out_dir, "meshes"), exist_ok=True)
    _maybe_bake_surface(ng, descriptor, out_dir, sess)
    for a in lowered["assets"]:
        path = os.path.join(out_dir, "meshes", a["file"])
        if a["kind"] == "unit_cube":
            bake_unit_cube(path, a["origin"])
        else:
            bake_subgraph(ng, a["source_node"], path, sess)
    descriptor["warnings"] = list(sess.warnings)

    with open(os.path.join(out_dir, "effect.gnue.json"), "w", encoding="utf-8") as f:
        json.dump(descriptor, f, indent=1)
    manifest = {"exporter": "gnue_exporter", "descriptor": "effect.gnue.json",
                "descriptor_version": core.DESCRIPTOR_VERSION,
                "blender_version": ir["blender_version"],
                "blend_file": ir["blend_file"], "node_group": ng.name,
                "assets": [a["file"] for a in descriptor["assets"]]
                          + ([descriptor["surface_asset"]["file"]]
                             if "surface_asset" in descriptor else [])}
    with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    report = core.make_report(ir, descriptor, sess)
    with open(os.path.join(out_dir, "export_report.txt"), "w", encoding="utf-8") as f:
        f.write(report)
    return True, report, descriptor
