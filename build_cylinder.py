"""Wave 1 / Person A — Cylinder (GeometryNodeMeshCylinder) end-to-end test.

Builds a minimal graph that instances a mesh Cylinder on a row of points, then
runs the real exporter on it and asserts:
  - the export is NOT refused (Cylinder is whitelisted),
  - a baked FBX asset is produced (bake_subgraph path) and is non-empty,
  - an instance block references that asset,
  - no ERROR in the report and no false "dead branch" warning for the Cylinder.

Cylinder is supported as an *instance source*; its parameters (radius/depth/
verts) are frozen into the baked FBX at export time.
    headless:  blender --background --python build_cylinder.py
    socket:    python tools/bl_exec.py build_cylinder.py
Writes a PASS/FAIL summary to export/cyl_test_a/result.txt (or GNUE_RESULT).
"""
import importlib
import os
import sys

import bpy

# repo root: injected global (tools/bl_exec.py) -> env -> this file's folder (PORTABILITY.md §2.4)
REPO = (globals().get("GNUE_REPO") or os.environ.get("GNUE_REPO")
        or (os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else None))
if not REPO:
    raise RuntimeError("set GNUE_REPO before exec'ing this script - see PORTABILITY.md")
OUT = os.path.join(REPO, "export", "cyl_test_a")
RESULT = os.environ.get("GNUE_RESULT") or os.path.join(OUT, "result.txt")

GROUP_NAME = "CylTest_A"
_log = []


def w(*a):
    _log.append(" ".join(str(x) for x in a))


def fresh_group(name):
    old = bpy.data.node_groups.get(name)
    if old:
        bpy.data.node_groups.remove(old)
    return bpy.data.node_groups.new(name, "GeometryNodeTree")


def build():
    ng = fresh_group(GROUP_NAME)
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nt = ng.nodes

    gin = nt.new("NodeGroupInput"); gin.location = (-800, 0)
    gout = nt.new("NodeGroupOutput"); gout.location = (400, 0)

    # a row of points (mesh vertices) to instance on
    line = nt.new("GeometryNodeMeshLine"); line.location = (-600, 200)
    line.inputs["Count"].default_value = 6
    # Offset mode: step along +X so instances don't overlap
    try:
        line.inputs["Offset"].default_value = (1.5, 0.0, 0.0)
    except Exception as e:
        w("line offset:", e)

    # the primitive under test
    cyl = nt.new("GeometryNodeMeshCylinder"); cyl.location = (-600, -160)
    for k, v in (("Vertices", 12), ("Radius", 0.4), ("Depth", 1.2)):
        try:
            cyl.inputs[k].default_value = v
        except Exception as e:
            w("cyl input", k, ":", e)

    inst = nt.new("GeometryNodeInstanceOnPoints"); inst.location = (0, 0)
    ng.links.new(line.outputs["Mesh"], inst.inputs["Points"])
    ng.links.new(cyl.outputs["Mesh"], inst.inputs["Instance"])
    ng.links.new(inst.outputs["Instances"], gout.inputs[0])

    # host object carrying the modifier (matches the other build_*.py scripts)
    obj = bpy.data.objects.get("CylTest_A_Demo")
    if obj is None:
        bpy.ops.mesh.primitive_plane_add(size=1, location=(120, 0, 0))
        obj = bpy.context.active_object
        obj.name = "CylTest_A_Demo"
    for m in list(obj.modifiers):
        obj.modifiers.remove(m)
    obj.modifiers.new("CylTest", "NODES").node_group = ng
    return ng


def export(ng):
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    import gnue_exporter.core
    import gnue_exporter.frontend_bpy
    importlib.reload(gnue_exporter.core)
    importlib.reload(gnue_exporter.frontend_bpy)
    return gnue_exporter.frontend_bpy.export_group(ng, OUT)


def main():
    ng = build()
    w("built %r: %d nodes" % (GROUP_NAME, len(ng.nodes)))
    ok, report, desc = export(ng)
    w("export ok:", ok)

    fails = []
    if not ok:
        fails.append("export REFUSED")
    if desc:
        assets = desc.get("assets", [])
        baked = [a for a in assets if a.get("kind") == "baked"]
        w("assets:", [(a["id"], a["kind"], a["file"]) for a in assets])
        if not baked:
            fails.append("no baked asset produced")
        else:
            fbx = os.path.join(OUT, baked[0]["file"].replace("/", os.sep))
            sz = os.path.getsize(fbx) if os.path.exists(fbx) else -1
            w("baked FBX:", fbx, "size:", sz)
            if sz < 1000:
                fails.append("baked FBX missing or tiny (%s bytes)" % sz)
        blocks = desc.get("blocks", [])
        inst_blocks = [b for b in blocks if "instance" in b["type"]]
        w("block types:", sorted({b["type"] for b in blocks}))
        refs_asset = any(
            isinstance(b.get(k), dict) and "asset" in b.get(k, {})
            for b in blocks for k in b
        ) or any("asset" in str(b) for b in blocks)
        if not inst_blocks:
            fails.append("no instance block emitted")
        if not refs_asset:
            fails.append("no block references the baked asset")
    if "ERROR" in (report or ""):
        fails.append("report contains ERROR")
    # a dead-branch warning naming the Cylinder node type would mean the asset
    # source wasn't recognised as consumed (the unlinked Group Input warning in
    # this minimal test graph is expected and unrelated)
    if any("dead branch" in ln and "GeometryNodeMeshCylinder" in ln
           for ln in (report or "").splitlines()):
        fails.append("false dead-branch warning for Cylinder")

    w("")
    w("RESULT:", "PASS" if not fails else "FAIL")
    for f in fails:
        w("  FAIL:", f)
    w("--- report ---")
    w(report or "(none)")

    os.makedirs(os.path.dirname(RESULT), exist_ok=True)
    with open(RESULT, "w", encoding="utf-8") as f:
        f.write("\n".join(_log))
    print("\n".join(_log))


main()
