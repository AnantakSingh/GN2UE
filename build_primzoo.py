"""Wave 1 / Person A — PrimZoo: one effect that scatters all six mesh primitives.

Six clusters (one per primitive), each a short row of instances, joined into one
geometry. Exported as a single effect so a single headless UE import verifies
every primitive round-trips: baked FBX -> imported StaticMesh -> PCG graph.

Run headless:  blender --background --python build_primzoo.py
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
OUT = os.path.join(REPO, "export", "primzoo")
RESULT = os.environ.get("GNUE_RESULT") or os.path.join(OUT, "result.txt")

PRIMS = [
    ("GeometryNodeMeshCylinder", {"Vertices": 16, "Radius": 0.4, "Depth": 1.2}, {}),
    ("GeometryNodeMeshCone",     {"Vertices": 16, "Radius Bottom": 0.45,
                                  "Radius Top": 0.0, "Depth": 1.3}, {}),
    ("GeometryNodeMeshIcoSphere", {"Radius": 0.5, "Subdivisions": 2}, {}),
    ("GeometryNodeMeshUVSphere", {"Segments": 16, "Rings": 10, "Radius": 0.5}, {}),
    ("GeometryNodeMeshGrid",     {"Size X": 0.9, "Size Y": 0.9,
                                  "Vertices X": 2, "Vertices Y": 2}, {}),
    ("GeometryNodeMeshCircle",   {"Vertices": 20, "Radius": 0.5},
                                 {"fill_type": "NGON"}),
]
_log = []


def w(*a):
    _log.append(" ".join(str(x) for x in a))


def build():
    name = "PrimZoo"
    old = bpy.data.node_groups.get(name)
    if old:
        bpy.data.node_groups.remove(old)
    ng = bpy.data.node_groups.new(name, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    nt = ng.nodes
    nt.new("NodeGroupInput").location = (-1000, 0)
    gout = nt.new("NodeGroupOutput"); gout.location = (600, 0)
    join = nt.new("GeometryNodeJoinGeometry"); join.location = (300, 0)
    ng.links.new(join.outputs["Geometry"], gout.inputs[0])

    for i, (idname, inputs, props) in enumerate(PRIMS):
        short = idname.replace("GeometryNodeMesh", "")
        y = i * 220
        # one point per primitive, placed on its own Y row. GeometryNodePoints ->
        # point.create is the kernel-supported points source (MeshLine's point.line
        # has no importer kernel handler yet — a separate gap).
        pts = nt.new("GeometryNodePoints"); pts.location = (-800, y)
        pts.inputs["Count"].default_value = 1
        try:
            pts.inputs["Position"].default_value = (0.0, i * 2.2, 0.0)
        except Exception as e:
            w("[%s] pos:" % short, e)

        prim = nt.new(idname); prim.location = (-800, y - 120)
        for k, v in props.items():
            try:
                setattr(prim, k, v)
            except Exception as e:
                w("[%s] prop %s:" % (short, k), e)
        for k, v in inputs.items():
            try:
                prim.inputs[k].default_value = v
            except Exception as e:
                w("[%s] input %r:" % (short, k), e)
        geo = next((s for s in prim.outputs if s.type == "GEOMETRY"), None)

        inst = nt.new("GeometryNodeInstanceOnPoints"); inst.location = (-380, y)
        ng.links.new(pts.outputs["Points"], inst.inputs["Points"])
        ng.links.new(geo, inst.inputs["Instance"])
        ng.links.new(inst.outputs["Instances"], join.inputs["Geometry"])

    obj = bpy.data.objects.get("PrimZoo_Demo")
    if obj is None:
        bpy.ops.mesh.primitive_plane_add(size=1, location=(0, 0, 0))
        obj = bpy.context.active_object
        obj.name = "PrimZoo_Demo"
    for m in list(obj.modifiers):
        obj.modifiers.remove(m)
    obj.modifiers.new("PrimZoo", "NODES").node_group = ng
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
    w("built PrimZoo: %d nodes" % len(ng.nodes))
    ok, report, desc = export(ng)
    w("export ok:", ok)
    if desc:
        assets = desc.get("assets", [])
        w("assets (%d):" % len(assets))
        for a in assets:
            fbx = os.path.join(OUT, a["file"].replace("/", os.sep))
            sz = os.path.getsize(fbx) if os.path.exists(fbx) else -1
            w("   %-22s %s  %sB" % (a["id"], a["kind"], sz))
        kinds = sorted({b["type"] for b in desc.get("blocks", [])})
        w("block types:", kinds)
        w("blocks:", len(desc.get("blocks", [])), " assets:", len(assets))
    w("errors in report:", "YES" if "ERROR" in (report or "") else "no")
    os.makedirs(os.path.dirname(RESULT), exist_ok=True)
    with open(RESULT, "w", encoding="utf-8") as f:
        f.write("\n".join(_log))
    print("\n".join(_log))


main()
