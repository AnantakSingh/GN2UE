"""Wave 1 / Person A — mesh primitives end-to-end test (parameterized).

Covers every mesh primitive supported as a baked instance source. For each, it
builds a minimal graph (a row of points -> the primitive instanced on them),
runs the real exporter, and asserts: not refused, a non-empty baked FBX is
produced, an instance block references it, and no ERROR / no false dead-branch
warning for the primitive.

Cylinder has its own pattern-setter script (build_cylinder.py); this covers the
rest and re-checks Cylinder too, so it is the canonical Person A regression test.

Run headless:  blender --background --python build_mesh_primitives.py
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
RESULT = (os.environ.get("GNUE_RESULT")
          or os.path.join(REPO, "export", "mesh_primitives_test_a", "result.txt"))

# idname, low-poly input defaults, node props
PRIMS = [
    ("GeometryNodeMeshCylinder", {"Vertices": 12, "Radius": 0.4, "Depth": 1.2}, {}),
    ("GeometryNodeMeshCone",     {"Vertices": 12, "Radius Bottom": 0.4,
                                  "Radius Top": 0.0, "Depth": 1.2}, {}),
    ("GeometryNodeMeshIcoSphere", {"Radius": 0.4, "Subdivisions": 1}, {}),
    ("GeometryNodeMeshUVSphere", {"Segments": 12, "Rings": 6, "Radius": 0.4}, {}),
    ("GeometryNodeMeshGrid",     {"Size X": 0.8, "Size Y": 0.8,
                                  "Vertices X": 2, "Vertices Y": 2}, {}),
    ("GeometryNodeMeshCircle",   {"Vertices": 12, "Radius": 0.4},
                                 {"fill_type": "NGON"}),
]
_log = []


def w(*a):
    _log.append(" ".join(str(x) for x in a))


def exporter():
    if REPO not in sys.path:
        sys.path.insert(0, REPO)
    import gnue_exporter.core
    import gnue_exporter.frontend_bpy
    importlib.reload(gnue_exporter.core)
    importlib.reload(gnue_exporter.frontend_bpy)
    return gnue_exporter.frontend_bpy.export_group


def build_group(idname, inputs, props):
    short = idname.replace("GeometryNodeMesh", "")
    name = "Prim_%s" % short
    old = bpy.data.node_groups.get(name)
    if old:
        bpy.data.node_groups.remove(old)
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nt = ng.nodes
    nt.new("NodeGroupInput").location = (-800, 0)
    gout = nt.new("NodeGroupOutput"); gout.location = (400, 0)

    line = nt.new("GeometryNodeMeshLine"); line.location = (-600, 200)
    line.inputs["Count"].default_value = 6
    try:
        line.inputs["Offset"].default_value = (1.5, 0.0, 0.0)
    except Exception as e:
        w("  [%s] line offset:" % short, e)

    prim = nt.new(idname); prim.location = (-600, -160)
    for k, v in props.items():
        try:
            setattr(prim, k, v)
        except Exception as e:
            w("  [%s] prop %s:" % (short, k), e)
    for k, v in inputs.items():
        try:
            prim.inputs[k].default_value = v
        except Exception as e:
            w("  [%s] input %r:" % (short, k), e)
    geo_out = next((s for s in prim.outputs if s.type == "GEOMETRY"), None)

    inst = nt.new("GeometryNodeInstanceOnPoints"); inst.location = (0, 0)
    ng.links.new(line.outputs["Mesh"], inst.inputs["Points"])
    ng.links.new(geo_out, inst.inputs["Instance"])
    ng.links.new(inst.outputs["Instances"], gout.inputs[0])
    return ng, name, short


def check(idname):
    export_group = exporter()
    ng, name, short = build_group(idname, dict(PRIMS_BY_ID[idname][0]),
                                  PRIMS_BY_ID[idname][1])
    out = os.path.join(REPO, "export", "%s_test_a" % short.lower())
    ok, report, desc = export_group(ng, out)
    fails = []
    if not ok:
        fails.append("export REFUSED")
    baked = [a for a in (desc.get("assets", []) if desc else []) if a.get("kind") == "baked"]
    if not baked:
        fails.append("no baked asset")
    else:
        fbx = os.path.join(out, baked[0]["file"].replace("/", os.sep))
        sz = os.path.getsize(fbx) if os.path.exists(fbx) else -1
        if sz < 1000:
            fails.append("baked FBX missing/tiny (%s)" % sz)
    if desc and not any("instance" in b["type"] for b in desc.get("blocks", [])):
        fails.append("no instance block")
    if "ERROR" in (report or ""):
        fails.append("report ERROR")
    if any("dead branch" in ln and idname in ln for ln in (report or "").splitlines()):
        fails.append("false dead-branch for %s" % short)
    status = "PASS" if not fails else "FAIL"
    fbxsz = os.path.getsize(os.path.join(out, baked[0]["file"].replace("/", os.sep))) \
        if baked and os.path.exists(os.path.join(out, baked[0]["file"].replace("/", os.sep))) else 0
    w("%-5s %-12s ok=%s fbx=%sB %s" % (status, short, ok, fbxsz,
                                       ("" if not fails else "-> " + "; ".join(fails))))
    return not fails


PRIMS_BY_ID = {idn: (inp, pr) for idn, inp, pr in PRIMS}


def main():
    results = []
    for idn, _, _ in PRIMS:
        try:
            results.append(check(idn))
        except Exception:
            import traceback
            w("EXC", idn, traceback.format_exc().splitlines()[-1])
            results.append(False)
    w("")
    w("OVERALL:", "ALL PASS (%d/%d)" % (sum(results), len(results))
      if all(results) else "FAILURES (%d/%d passed)" % (sum(results), len(results)))
    os.makedirs(os.path.dirname(RESULT), exist_ok=True)
    with open(RESULT, "w", encoding="utf-8") as f:
        f.write("\n".join(_log))
    print("\n".join(_log))


main()
