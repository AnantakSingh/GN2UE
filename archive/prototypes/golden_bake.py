"""
golden_bake.py — M1 golden-data bake for the GN→UE bridge.

Run inside Blender 5.x (Scripting tab > Run Script, or:
    blender card_spring.blend --background --python golden_bake.py
).

Evaluates the depsgraph at fixed values of the animation-driver parameter
(default: "Spring Progress") and writes every instance's translation,
rotation, and scale to golden.json — in Blender-native units (meters,
radians, right-handed, +Z up). The UE validation script owns conversion,
per V1_Architecture.md §6/§7.

Notes
-----
* If the node group contains Realize Instances, instances stop being
  instances and depsgraph.object_instances can't see them. With
  MUTE_REALIZE = True (default) the script temporarily mutes every
  GeometryNodeRealizeInstances node and restores it afterwards.
* Modifier inputs are keyed by socket *identifier* (e.g. "Socket_2"),
  not by name; the script resolves the identifier from the group
  interface, so you only supply the human name.
"""

import bpy
import json
import os
from datetime import datetime, timezone

# ----------------------------------------------------------------- config
OBJECT_NAME   = None              # None = auto-detect first object with a GN modifier
MODIFIER_NAME = None              # None = first NODES modifier on that object
PARAM_NAME    = "Spring Progress" # group input to sweep
SAMPLES       = [0.0, 0.25, 0.5, 0.75, 1.0]
OUTPUT_PATH   = "//golden.json"   # // = next to the .blend
MUTE_REALIZE  = True
# -------------------------------------------------------------------------


def fail(msg):
    raise RuntimeError(f"[golden_bake] {msg}")


def find_host_and_modifier():
    if OBJECT_NAME:
        obj = bpy.data.objects.get(OBJECT_NAME)
        if not obj:
            fail(f"Object '{OBJECT_NAME}' not found.")
        candidates = [obj]
    else:
        candidates = list(bpy.data.objects)

    for obj in candidates:
        for mod in obj.modifiers:
            if mod.type != 'NODES' or mod.node_group is None:
                continue
            if MODIFIER_NAME and mod.name != MODIFIER_NAME:
                continue
            return obj, mod
    fail("No Geometry Nodes modifier found. Set OBJECT_NAME/MODIFIER_NAME explicitly.")


def find_input_identifier(node_group, name):
    for item in node_group.interface.items_tree:
        if (getattr(item, "item_type", None) == 'SOCKET'
                and item.in_out == 'INPUT'
                and item.name == name):
            return item.identifier
    fail(f"Group input '{name}' not found on node group '{node_group.name}'. "
         f"Available inputs: "
         + ", ".join(i.name for i in node_group.interface.items_tree
                     if getattr(i, 'item_type', None) == 'SOCKET' and i.in_out == 'INPUT'))


def mute_realize_nodes(node_group):
    """Mute Realize Instances nodes (incl. nested groups); return restore list."""
    muted = []
    seen = set()

    def walk(ng):
        if ng is None or ng.name in seen:
            return
        seen.add(ng.name)
        for node in ng.nodes:
            if node.bl_idname == 'GeometryNodeRealizeInstances' and not node.mute:
                node.mute = True
                muted.append(node)
            if node.bl_idname == 'GeometryNodeGroup':
                walk(node.node_tree)

    walk(node_group)
    return muted


def collect_instances(depsgraph, host):
    out = []
    for oi in depsgraph.object_instances:
        if not oi.is_instance:
            continue
        parent = oi.parent
        if parent is None or parent.original != host:
            continue
        loc, quat, scale = oi.matrix_world.decompose()
        eul = quat.to_euler('XYZ')
        out.append({
            "persistent_id": list(oi.persistent_id[:2]),
            "location": [loc.x, loc.y, loc.z],
            "rotation_quat_wxyz": [quat.w, quat.x, quat.y, quat.z],
            "rotation_euler_xyz": [eul.x, eul.y, eul.z],
            "scale": [scale.x, scale.y, scale.z],
        })
    # enumerate in iteration order — for GN instance-on-points this follows
    # point index, which is the stagger index we compare against in UE
    for i, inst in enumerate(out):
        inst["index"] = i
    return out


def main():
    host, mod = find_host_and_modifier()
    ng = mod.node_group
    ident = find_input_identifier(ng, PARAM_NAME)

    original_value = mod[ident]
    muted = mute_realize_nodes(ng) if MUTE_REALIZE else []

    samples_out = []
    try:
        for value in SAMPLES:
            mod[ident] = float(value)
            host.update_tag()
            bpy.context.view_layer.update()
            dg = bpy.context.evaluated_depsgraph_get()
            dg.update()

            instances = collect_instances(dg, host)
            if not instances:
                print(f"[golden_bake] WARNING: 0 instances at {PARAM_NAME}={value}. "
                      "Is Realize Instances still active, or does the graph output "
                      "realized geometry only?")
            samples_out.append({"value": value, "count": len(instances),
                                "instances": instances})
            print(f"[golden_bake] {PARAM_NAME}={value}: {len(instances)} instances")
    finally:
        mod[ident] = original_value
        for node in muted:
            node.mute = False
        host.update_tag()
        bpy.context.view_layer.update()

    doc = {
        "format": "gnue-golden",
        "version": "1.0",
        "source": {
            "blender_version": bpy.app.version_string,
            "file": bpy.path.basename(bpy.data.filepath) or "<unsaved>",
            "object": host.name,
            "modifier": mod.name,
            "node_group": ng.name,
            "baked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "units": {"length": "m", "rotation": "rad", "up": "+Z", "handedness": "right"},
        "param": PARAM_NAME,
        "samples": samples_out,
    }

    path = bpy.path.abspath(OUTPUT_PATH)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)
    print(f"[golden_bake] wrote {path} ({os.path.getsize(path)} bytes)")


main()
