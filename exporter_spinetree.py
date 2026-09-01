"""
GN->UE exporter (dev harness) for the SpineTree static-scatter family.

Talks to the blender-mcp addon socket (127.0.0.1:9876) of a running Blender,
reads the live SpineTreeGN node group, and emits:

    export/spinetree.gnue.json   descriptor (blocks + raw_graph layers)

Companion meshes (exported separately from Blender, unit-sized):
    export/SM_SpineCube.fbx      unit cube, simple subdivision level 2
    export/SM_TreeLeaf.fbx       leaf plane + petiole, authored at Leaf Size = 1

Family: "static_scatter" -- a static procedural generator (no animation
driver), realized in UE as a parametric PCG graph. Per the V1 architecture
decision this family is *statistically* equivalent, not instance-identical:
Blender's RNG (Random Value / Accumulate Field) cannot be reproduced in UE.

All values stay in Blender-native units (m, rad, right-handed +Z up).
The importer owns unit/axis conversion (x100 to cm, Y-negation, rad->deg).
"""
import socket
import json
import datetime
import pathlib

HOST, PORT = "127.0.0.1", 9876
OUT = pathlib.Path(__file__).parent / "export" / "spinetree.gnue.json"


def blender(cmd_type, params=None, timeout=30):
    s = socket.create_connection((HOST, PORT), timeout=timeout)
    s.sendall(json.dumps({"type": cmd_type, "params": params or {}}).encode())
    buf = b""
    while True:
        chunk = s.recv(1 << 16)
        if not chunk:
            break
        buf += chunk
        try:
            return json.loads(buf.decode())
        except ValueError:
            continue
    return json.loads(buf.decode())


DUMP_CODE = r'''
import bpy, json
ng = bpy.data.node_groups["SpineTreeGN"]
nodes = []
for n in ng.nodes:
    d = {"name": n.name, "idname": n.bl_idname,
         "loc": [round(n.location.x), round(n.location.y)]}
    ins = []
    for s in n.inputs:
        e = {"name": s.name, "linked": s.is_linked}
        if not s.is_linked and hasattr(s, "default_value"):
            v = s.default_value
            try:
                e["value"] = ([round(x, 6) for x in v]
                              if hasattr(v, "__len__") and not isinstance(v, str)
                              else (round(v, 6) if isinstance(v, float) else v))
            except Exception:
                pass
        ins.append(e)
    d["inputs"] = ins
    props = {}
    for pn in ("operation", "data_type", "domain", "mode", "spline_type"):
        if hasattr(n, pn):
            try:
                props[pn] = str(getattr(n, pn))
            except Exception:
                pass
    if props:
        d["props"] = props
    nodes.append(d)
links = [[l.from_node.name, l.from_socket.name, l.to_node.name, l.to_socket.name]
         for l in ng.links]
iface = []
for it in ng.interface.items_tree:
    if it.item_type == "SOCKET":
        e = {"name": it.name, "dir": it.in_out, "type": it.socket_type}
        if hasattr(it, "default_value"):
            v = it.default_value
            try:
                e["default"] = ([round(x, 6) for x in v]
                                if hasattr(v, "__len__") and not isinstance(v, str)
                                else (round(v, 6) if isinstance(v, float) else v))
            except Exception:
                pass
        iface.append(e)
print(json.dumps({"blender_version": bpy.app.version_string,
                  "file": bpy.data.filepath or "(unsaved)",
                  "nodes": nodes, "links": links, "interface": iface}))
'''


def main():
    resp = blender("execute_code", {"code": DUMP_CODE})
    raw = json.loads(resp["result"]["result"])

    descriptor = {
        "format": "gnue-descriptor",
        "version": "1.1",
        "family": "static_scatter",
        "source": {
            "blender_version": raw["blender_version"],
            "file": raw["file"],
            "node_group": "SpineTreeGN",
            "exported_at": datetime.datetime.now(datetime.timezone.utc)
                .strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "units": {"length": "m", "rotation": "rad", "up": "+Z",
                  "handedness": "right"},
        "parameters": [
            {"name": "Seed",             "type": "int",   "default": 0},
            {"name": "Spine Segments",   "type": "int",   "default": 12},
            {"name": "Wander",           "type": "float", "default": 0.5},
            {"name": "Cube Count",       "type": "int",   "default": 10},
            {"name": "Cube Thickness",   "type": "float", "default": 0.22},
            {"name": "Cube Length",      "type": "float", "default": 0.85},
            {"name": "Leaf Points",      "type": "int",   "default": 48},
            {"name": "Leaf Probability", "type": "float", "default": 0.35,
             "subtype": "factor"},
            {"name": "Leaf Size",        "type": "float", "default": 0.6},
        ],
        "meshes": [
            {"id": "cube", "file": "SM_SpineCube.fbx",
             "source": "generated: MeshCube(1,1,1) + SubdivideMesh(level 2)",
             "note": "unit cube; scaled per-instance by the cubes0 block"},
            {"id": "leaf", "file": "SM_TreeLeaf.fbx",
             "source": "generated: MeshGrid(1 x 0.33) at X=0.9 + "
                       "Cylinder(r=0.035, depth=0.55, 8 verts) along X",
             "note": "authored at Leaf Size = 1; scale uniformly by the "
                     "Leaf Size parameter (all leaf dimensions are linear "
                     "in Leaf Size)"},
        ],
        "blocks": [
            {
                "id": "spine0",
                "type": "curve.random_walk",
                "points": {"param": "Spine Segments"},
                "base_step": [0.0, 0.0, 0.6],
                "step_random": {
                    "min": [-1.0, -1.0, -0.1],
                    "max": [1.0, 1.0, 0.4],
                    "scale": {"param": "Wander"},
                    "seed": {"param": "Seed"},
                    "accumulate": True,
                },
                "smooth": {"type": "catmull_rom", "samples": 128},
            },
            {
                "id": "cubes0",
                "type": "scatter.on_curve",
                "curve": "spine0",
                "count": {"param": "Cube Count"},
                "mesh": "cube",
                "align": {"axis": "z", "to": "tangent"},
                "scale": {
                    "x": {"param": "Cube Thickness"},
                    "y": {"param": "Cube Thickness"},
                    "z": {"expr": "max", "of": [
                        {"expr": "segment_overlap",
                         "curve_length_of": "spine0",
                         "count": {"param": "Cube Count"},
                         "overlap": 1.5,
                         "note": "1.5 * curve_length / (count - 1)"},
                        {"param": "Cube Length"},
                    ]},
                },
            },
            {
                "id": "leaves0",
                "type": "scatter.on_curve",
                "curve": "spine0",
                "count": {"param": "Leaf Points"},
                "mesh": "leaf",
                "selection": {
                    "kind": "random_bool",
                    "probability": {"param": "Leaf Probability"},
                    "seed": {"expr": "add", "of": [{"param": "Seed"}, 1]},
                },
                "rotation": {
                    "kind": "random_euler",
                    "replaces_alignment": True,
                    "yaw": {"min": 0.0, "max": 6.2832,
                            "seed": {"expr": "add", "of": [{"param": "Seed"}, 2]}},
                    "tilt": {"min": [-0.45, -0.9, 0.0],
                             "max": [0.45, 0.2, 0.0],
                             "seed": {"expr": "add", "of": [{"param": "Seed"}, 7]}},
                    "compose": "yaw_plus_tilt_euler_add",
                },
                "scale": {"uniform": {"param": "Leaf Size"}},
            },
        ],
        "raw_graph": {
            "nodes": raw["nodes"],
            "links": raw["links"],
            "interface": raw["interface"],
        },
    }

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(descriptor, indent=2), encoding="utf-8")
    print(f"wrote {OUT} "
          f"({len(raw['nodes'])} raw nodes, {len(raw['links'])} raw links)")


if __name__ == "__main__":
    main()
