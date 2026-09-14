"""
export_raw_graph.py — M1 raw-graph layer of the .gnue.json exporter.

Run inside Blender 5.x. Walks the Geometry Nodes group on the active (or
named) object and writes a .gnue.json containing:

  * the descriptor header (format/version/source/units)
  * parameters[]  — derived from the group's input interface
  * objects[]     — every Object Info binding found in the graph (role
                    left as "unknown"; the M2 recognizers will classify)
  * blocks: []    — empty; M2 fills this via pattern matching
  * raw_graph     — full node/link/value dump (diagnostics + recognizer dev)

Pure structure walk: no depsgraph, no evaluation (V1_Architecture.md §5.1).
"""

import bpy
import json
from datetime import datetime, timezone

# ----------------------------------------------------------------- config
OBJECT_NAME   = None              # None = active object, else first GN object
MODIFIER_NAME = None
OUTPUT_PATH   = "//card_spring.gnue.json"
# -------------------------------------------------------------------------

SOCKET_TYPE_MAP = {
    "NodeSocketFloat": "float", "NodeSocketInt": "int",
    "NodeSocketBool": "bool", "NodeSocketVector": "vector",
    "NodeSocketRotation": "rotation", "NodeSocketColor": "color",
    "NodeSocketString": "string", "NodeSocketObject": "object",
    "NodeSocketGeometry": "geometry", "NodeSocketMaterial": "material",
    "NodeSocketCollection": "collection", "NodeSocketMenu": "menu",
}


def fail(msg):
    raise RuntimeError(f"[export_raw_graph] {msg}")


def find_host_and_modifier():
    candidates = []
    if OBJECT_NAME:
        obj = bpy.data.objects.get(OBJECT_NAME)
        if not obj:
            fail(f"Object '{OBJECT_NAME}' not found.")
        candidates = [obj]
    else:
        if bpy.context.active_object:
            candidates.append(bpy.context.active_object)
        candidates += [o for o in bpy.data.objects if o not in candidates]

    for obj in candidates:
        for mod in obj.modifiers:
            if mod.type == 'NODES' and mod.node_group is not None:
                if MODIFIER_NAME and mod.name != MODIFIER_NAME:
                    continue
                return obj, mod
    fail("No Geometry Nodes modifier found.")


def serialize_value(v):
    """Best-effort JSON serialization of a socket default_value."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if hasattr(v, "name"):                      # datablock pointer (Object, etc.)
        return {"datablock": type(v).__name__, "name": v.name}
    try:
        return [float(c) for c in v]            # vectors, colors, eulers
    except TypeError:
        return repr(v)


def serialize_socket(sock):
    d = {
        "identifier": sock.identifier,
        "name": sock.name,
        "type": sock.bl_idname,
        "is_linked": sock.is_linked,
    }
    if hasattr(sock, "default_value") and not sock.is_linked:
        d["default_value"] = serialize_value(sock.default_value)
    return d


def serialize_node(node):
    d = {
        "name": node.name,
        "label": node.label,
        "idname": node.bl_idname,
        "location": [node.location.x, node.location.y],
        "mute": node.mute,
        "inputs": [serialize_socket(s) for s in node.inputs],
        "outputs": [{"identifier": s.identifier, "name": s.name,
                     "type": s.bl_idname, "is_linked": s.is_linked}
                    for s in node.outputs],
    }
    # enum/mode properties that recognizers key on (operation, data_type, ...)
    props = {}
    for prop in node.bl_rna.properties:
        if prop.is_readonly or prop.identifier in {
                "name", "label", "location", "mute", "select", "width",
                "height", "color", "use_custom_color", "hide", "show_options",
                "show_preview", "show_texture", "location_absolute",
                "parent", "warning_propagation"}:
            continue
        if prop.type in {'ENUM', 'BOOLEAN', 'INT', 'FLOAT', 'STRING'}:
            try:
                props[prop.identifier] = getattr(node, prop.identifier)
            except Exception:
                pass
    if props:
        d["properties"] = props
    if node.bl_idname == 'GeometryNodeGroup' and node.node_tree:
        d["group"] = node.node_tree.name
    return d


def walk_group(ng):
    return {
        "name": ng.name,
        "nodes": [serialize_node(n) for n in ng.nodes],
        "links": [{
            "from_node": l.from_node.name,
            "from_socket": l.from_socket.identifier,
            "to_node": l.to_node.name,
            "to_socket": l.to_socket.identifier,
            "muted": l.is_muted,
        } for l in ng.links],
    }


def export_parameters(ng, mod):
    params = []
    for item in ng.interface.items_tree:
        if getattr(item, "item_type", None) != 'SOCKET' or item.in_out != 'INPUT':
            continue
        stype = SOCKET_TYPE_MAP.get(item.socket_type, item.socket_type)
        if stype in {"geometry",}:
            continue
        p = {"name": item.name, "type": stype, "identifier": item.identifier}
        if hasattr(item, "default_value"):
            p["default"] = serialize_value(item.default_value)
        # value actually set on the modifier, if overridden
        try:
            p["modifier_value"] = serialize_value(mod[item.identifier])
        except KeyError:
            pass
        params.append(p)
    return params


def export_object_bindings(ng):
    objs, seen = [], set()

    def walk(g):
        for node in g.nodes:
            if node.bl_idname == 'GeometryNodeObjectInfo':
                sock = node.inputs.get("Object")
                target = getattr(sock, "default_value", None) if sock else None
                if target and target.name not in seen:
                    seen.add(target.name)
                    objs.append({"id": f"obj{len(objs)}", "name": target.name,
                                 "role": "unknown"})
            elif node.bl_idname == 'GeometryNodeGroup' and node.node_tree:
                walk(node.node_tree)

    walk(ng)
    return objs


def main():
    host, mod = find_host_and_modifier()
    ng = mod.node_group

    # V1 supports a single inline group; nested groups are Tier X — but the
    # raw layer records them anyway so the export report can name them.
    groups, seen = [], set()

    def collect(g):
        if g.name in seen:
            return
        seen.add(g.name)
        groups.append(walk_group(g))
        for n in g.nodes:
            if n.bl_idname == 'GeometryNodeGroup' and n.node_tree:
                collect(n.node_tree)

    collect(ng)

    nested = [g["name"] for g in groups[1:]]
    if nested:
        print(f"[export_raw_graph] WARNING: nested node groups present "
              f"({', '.join(nested)}) — Tier X in V1, export will be "
              f"rejected at the Match stage.")

    doc = {
        "format": "gnue-descriptor",
        "version": "1.0",
        "source": {
            "blender_version": bpy.app.version_string,
            "file": bpy.path.basename(bpy.data.filepath) or "<unsaved>",
            "node_group": ng.name,
            "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "units": {"length": "m", "rotation": "rad", "up": "+Z", "handedness": "right"},
        "parameters": export_parameters(ng, mod),
        "objects": export_object_bindings(ng),
        "blocks": [],            # filled by the M2 recognizers
        "raw_graph": {"groups": groups},
    }

    path = bpy.path.abspath(OUTPUT_PATH)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2)

    n_nodes = sum(len(g["nodes"]) for g in groups)
    n_links = sum(len(g["links"]) for g in groups)
    print(f"[export_raw_graph] wrote {path}: {n_nodes} nodes, {n_links} links, "
          f"{len(doc['parameters'])} parameters, {len(doc['objects'])} object bindings")


main()
