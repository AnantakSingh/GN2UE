"""GN->UE exporter core: validation, lowering, evaluation, emission.

Pure Python — no bpy imports. Consumes the IR dict produced by frontend_bpy.py:

    ir = {
      "blender_version": str, "node_group": str, "units": {...},
      "params": [{"name","type","default","min","max"}],
      "nodes": {node_name: {
          "idname": str, "muted": bool, "props": {...},
          "inputs": [{"name","idx","type","enabled","linked",
                      "value"?, "links":[{"node","socket"}]}],
          "outputs": [{"name","idx","type"}]}},
      "output_node": node_name,
    }

Produces a v2 "graph"-family descriptor: parameters + semantic blocks +
expression trees + asset specs. Deterministic by construction — every rule in
this file is a fixed mapping; anything unrecognized is refused with a report,
never guessed (see docs in ../nextstep.md and atlas/v1_core_nodes.md).
"""

import json

# The 53-node V1 core set (atlas/v1_core_nodes.md) plus group in/out.
V1_WHITELIST = {
    "NodeGroupInput", "NodeGroupOutput",
    "FunctionNodeInputBool", "FunctionNodeInputInt", "ShaderNodeValue", "FunctionNodeInputVector",
    "GeometryNodeCaptureAttribute", "GeometryNodeStoreNamedAttribute", "GeometryNodeInputNamedAttribute",
    "GeometryNodeJoinGeometry", "GeometryNodeInputID", "GeometryNodeInputIndex",
    "GeometryNodeInputNormal", "GeometryNodeInputPosition", "GeometryNodeSetPosition",
    "GeometryNodeDeleteGeometry", "GeometryNodeDuplicateElements", "GeometryNodeSeparateGeometry",
    "GeometryNodeTransform",
    "GeometryNodeCurveLength", "GeometryNodeInputTangent", "GeometryNodeSplineParameter",
    "GeometryNodeSampleCurve", "GeometryNodeCurveSplineType", "GeometryNodeCurveToPoints",
    "GeometryNodeResampleCurve", "GeometryNodeCurvePrimitiveLine",
    "GeometryNodeInstanceOnPoints", "GeometryNodeInstancesToPoints", "GeometryNodeRotateInstances",
    "GeometryNodeScaleInstances", "GeometryNodeTranslateInstances",
    "GeometryNodeTriangulate", "GeometryNodeMeshCube", "GeometryNodeMeshLine",
    "GeometryNodeDistributePointsOnFaces", "GeometryNodePoints", "GeometryNodePointsToCurves",
    "GeometryNodeSwitch", "FunctionNodeRandomValue", "FunctionNodeBooleanMath", "ShaderNodeClamp",
    "FunctionNodeCompare", "ShaderNodeMapRange", "ShaderNodeMath", "ShaderNodeMix",
    "ShaderNodeVectorMath", "ShaderNodeCombineXYZ", "ShaderNodeSeparateXYZ",
    "FunctionNodeAlignRotationToVector", "FunctionNodeEulerToRotation",
}

DESCRIPTOR_VERSION = "2.1"

# V1.x tier: accepted with a feature flag in the descriptor so older importers
# refuse gracefully instead of mis-importing.
V1X_WHITELIST = {
    "GeometryNodeObjectInfo",        # actor binding (live proximity in UE)
    "ShaderNodeTexNoise",            # noise gradients (statistical equivalence)
    "GeometryNodeRealizeInstances",  # scatter-on-instances (greebles)
    "GeometryNodeSetMaterial",       # material name reference
    "GeometryNodeTrimCurve",         # curve trims (kernel arc-length clip)
    "GeometryNodeAccumulateField",   # prefix sums (kernel series, seeded RNG)
}

# Wave 1 (Person A) — mesh primitives supported as *instance sources*. Each is
# baked to an FBX at its current parameter values by frontend_bpy.bake_subgraph
# (the generic bake path) and consumed by the importer's generic asset loop, so
# no new descriptor block or importer capability is needed — just recognition.
# Parametric dependence inside the primitive is frozen at export (reported as a
# baked-asset approximation). Direct (non-instanced) geometry use is refused with
# a clear message by the geo_* handlers below.
BAKED_PRIMITIVES = {
    "GeometryNodeMeshCylinder",
}


class ExportRefused(Exception):
    """Raised when the graph cannot be translated deterministically."""


class Session:
    def __init__(self):
        self.warnings = []
        self.errors = []
        self.features = set()   # V1.x capabilities the importer must support

    def warn(self, msg):
        self.warnings.append(msg)

    def err(self, msg):
        self.errors.append(msg)


# ------------------------------------------------------------------ IR access

def node(ir, name):
    return ir["nodes"][name]


def in_sock(nd, name, enabled_only=True):
    """First matching input socket by name (enabled sockets win on duplicates
    like Mix/Random Value/Compare which expose one socket per data type)."""
    cands = [s for s in nd["inputs"] if s["name"] == name]
    if enabled_only:
        en = [s for s in cands if s.get("enabled", True)]
        if en:
            return en[0]
    return cands[0] if cands else None


def link_of(nd, sock_name):
    s = in_sock(nd, sock_name)
    if s and s["linked"] and s.get("links"):
        return s["links"][0]
    return None


def value_of(nd, sock_name, default=None):
    s = in_sock(nd, sock_name)
    if s is None:
        return default
    if s["linked"]:
        return None
    return s.get("value", default)


# ------------------------------------------------------------------ validate

def validate(ir, sess):
    """Whitelist + structural risk checks. Errors refuse the export."""
    for name, nd in ir["nodes"].items():
        idn = nd["idname"]
        if idn == "GeometryNodeGroup":
            sess.err("node %r: nested node groups are not yet inlined — apply/ungroup it" % name)
            continue
        if idn not in V1_WHITELIST and idn not in V1X_WHITELIST \
                and idn not in BAKED_PRIMITIVES:
            sess.err("node %r (%s) is outside the V1/V1.x supported set — see "
                     "atlas/v1_core_nodes.md" % (name, idn))
        if nd.get("muted"):
            sess.err("node %r is muted — unmute or delete it (muted pass-through is not translated)" % name)
        dom = nd.get("props", {}).get("domain")
        if idn in ("GeometryNodeDuplicateElements", "GeometryNodeSeparateGeometry",
                   "GeometryNodeDeleteGeometry") and dom not in (None, "POINT", "INSTANCE"):
            sess.err("node %r: domain %r not supported (only POINT/INSTANCE cross to UE)" % (name, dom))
        if idn == "GeometryNodeStoreNamedAttribute" and dom not in (None, "POINT", "INSTANCE"):
            sess.err("node %r: Store Named Attribute on domain %r not supported" % (name, dom))
    if ir.get("output_node") is None:
        sess.err("node group has no Group Output")
    if sess.errors:
        raise ExportRefused("validation failed")


# ------------------------------------------------------------------ lowering

MATH_PASS = {"ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "MULTIPLY_ADD", "SINE", "COSINE",
             "TANGENT", "POWER", "SQRT", "ABSOLUTE", "MINIMUM", "MAXIMUM", "FLOOR", "CEIL",
             "ROUND", "MODULO", "FLOORED_MODULO", "LOGARITHM", "EXPONENT", "SNAP", "SIGN",
             "GREATER_THAN", "LESS_THAN"}
VMATH_PASS = {"ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "CROSS_PRODUCT", "DOT_PRODUCT",
              "NORMALIZE", "SCALE", "LENGTH", "DISTANCE", "MINIMUM", "MAXIMUM"}

ATTR_INPUTS = {
    "GeometryNodeInputPosition": ("Position", "position"),
    "GeometryNodeInputNormal": ("Normal", "normal"),
    "GeometryNodeInputIndex": ("Index", "index"),
    "GeometryNodeInputID": ("ID", "id"),
    "GeometryNodeInputTangent": ("Tangent", "tangent"),
}


class Lowering:
    def __init__(self, ir, sess):
        self.ir = ir
        self.sess = sess
        self.blocks = []            # ordered semantic blocks
        self.block_of_node = {}     # node name -> block id (geometry chain nodes)
        self.assets = {}            # canonical key -> asset dict
        self.counters = {}

    # -- ids
    def bid(self, kind):
        n = self.counters.get(kind, 0)
        self.counters[kind] = n + 1
        return "%s%d" % (kind.replace(".", "_"), n)

    def add(self, kind, node_name=None, **fields):
        blk = {"id": self.bid(kind), "type": kind}
        blk.update(fields)
        self.blocks.append(blk)
        if node_name:
            self.block_of_node[node_name] = blk["id"]
        return blk["id"]

    # ---------------------------------------------------------- expressions
    def expr(self, link):
        """Lower the source socket of a link to an expression tree."""
        if link is None:
            raise ExportRefused("internal: expr() on unlinked socket")
        nname, sname = link["node"], link["socket"]
        nd = node(self.ir, nname)
        idn = nd["idname"]

        if idn == "NodeGroupInput":
            return {"param": sname}
        if idn in ATTR_INPUTS:
            return {"attr": ATTR_INPUTS[idn][1]}
        if idn == "GeometryNodeSplineParameter":
            return {"attr": {"Factor": "spline_factor", "Length": "spline_length_at",
                             "Index": "index"}.get(sname, "spline_factor")}
        if idn == "GeometryNodeInputNamedAttribute":
            return {"attr": "named:%s" % value_of(nd, "Name", "")}
        if idn == "FunctionNodeInputVector":
            return {"const": list(nd["props"].get("vector", (0, 0, 0)))}
        if idn == "ShaderNodeValue":
            return {"const": nd.get("props", {}).get("value", 0.0)}
        if idn in ("FunctionNodeInputBool", "FunctionNodeInputInt"):
            key = "boolean" if idn.endswith("Bool") else "integer"
            return {"const": nd["props"].get(key, 0)}

        if idn == "GeometryNodeObjectInfo":
            obj = value_of(nd, "Object")
            if not obj:
                raise ExportRefused("Object Info %r has no object assigned" % nname)
            self.sess.features.add("actor_binding")
            return {"actor": {"object": obj,
                              "output": sname.lower(),
                              "space": nd["props"].get("transform_space", "ORIGINAL")}}
        if idn == "ShaderNodeTexNoise":
            self.sess.features.add("noise")
            vec = in_sock(nd, "Vector")
            pos = self.sock_expr(vec) if (vec and vec["linked"]) else {"attr": "position"}
            return {"noise": {"pos": pos,
                              "scale": self.in_expr(nd, "Scale"),
                              "detail": self.in_expr(nd, "Detail"),
                              "out": sname.lower()}}

        if idn == "GeometryNodeAccumulateField":
            self.sess.features.add("accumulate")
            return {"accumulate": {"value": self.in_expr(nd, "Value"),
                                   "out": sname.lower()}}

        if idn == "GeometryNodeCaptureAttribute":
            return {"attr": "capture:%s" % sname, "capture_block": self.geometry(nname)}
        if idn == "GeometryNodeDuplicateElements" and sname == "Duplicate Index":
            self.geometry(nname)
            return {"attr": "duplicate_index"}
        if idn == "GeometryNodeDistributePointsOnFaces":
            self.geometry(nname)
            return {"attr": {"Normal": "normal", "Rotation": "rotation"}.get(sname, "normal")}
        if idn == "GeometryNodeCurveToPoints":
            self.geometry(nname)
            return {"attr": {"Tangent": "tangent", "Normal": "normal",
                             "Rotation": "rotation"}.get(sname, "rotation")}

        # auxiliary geometry-consuming scalar blocks
        if idn == "GeometryNodeCurveLength":
            blk = self.aux_block(nname, "curve.length",
                                 curve=self.geo_ref(link_of(nd, "Curve"), nname))
            return {"block_output": {"block": blk, "output": "length"}}
        if idn == "GeometryNodeSampleCurve":
            blk = self.aux_block(nname, "curve.sample",
                                 curve=self.geo_ref(link_of(nd, "Curves"), nname),
                                 factor=self.in_expr(nd, "Factor"))
            out = {"Position": "position", "Tangent": "tangent", "Normal": "normal"}.get(sname, "position")
            return {"block_output": {"block": blk, "output": out}}

        if idn == "FunctionNodeRandomValue":
            dt = nd["props"].get("data_type", "FLOAT")
            e = {"random": {"type": dt,
                            "min": self.in_expr(nd, "Min"),
                            "max": self.in_expr(nd, "Max"),
                            "seed": self.in_expr(nd, "Seed")}}
            if dt == "BOOLEAN":
                e["random"]["probability"] = self.in_expr(nd, "Probability")
                del e["random"]["min"]
                del e["random"]["max"]
            idl = link_of(nd, "ID")
            if idl:
                e["random"]["id"] = self.expr(idl)
            return e

        if idn == "ShaderNodeMath":
            op = nd["props"].get("operation", "ADD")
            if op not in MATH_PASS:
                raise ExportRefused("Math operation %s not in the supported table (node %r)" % (op, nname))
            args = [self.in_expr(nd, s["name"], sock=s) for s in nd["inputs"]
                    if s.get("enabled", True)]
            return {"op": "math." + op.lower(), "args": args}
        if idn == "ShaderNodeVectorMath":
            op = nd["props"].get("operation", "ADD")
            if op not in VMATH_PASS:
                raise ExportRefused("Vector Math operation %s not supported (node %r)" % (op, nname))
            if op == "SCALE":
                args = [self.in_expr(nd, "Vector"), self.in_expr(nd, "Scale")]
            else:
                vecs = [s for s in nd["inputs"] if s["name"] == "Vector"]
                nargs = 1 if op in ("NORMALIZE", "LENGTH") else 2
                args = [self.sock_expr(s) for s in vecs[:nargs]]
            return {"op": "vmath." + op.lower(), "args": args}
        if idn == "ShaderNodeCombineXYZ":
            return {"op": "vec3", "args": [self.in_expr(nd, c) for c in ("X", "Y", "Z")]}
        if idn == "ShaderNodeSeparateXYZ":
            return {"op": "vec." + sname.lower(), "args": [self.in_expr(nd, "Vector")]}
        if idn == "ShaderNodeMapRange":
            return {"op": "map_range", "args": [self.in_expr(nd, "Value"),
                                                self.in_expr(nd, "From Min"), self.in_expr(nd, "From Max"),
                                                self.in_expr(nd, "To Min"), self.in_expr(nd, "To Max")]}
        if idn == "ShaderNodeClamp":
            return {"op": "clamp", "args": [self.in_expr(nd, "Value"),
                                            self.in_expr(nd, "Min"), self.in_expr(nd, "Max")]}
        if idn == "ShaderNodeMix":
            dt = nd["props"].get("data_type", "FLOAT")
            return {"op": "mix", "dtype": dt,
                    "args": [self.in_expr(nd, "Factor"), self.in_expr(nd, "A"), self.in_expr(nd, "B")]}
        if idn == "FunctionNodeCompare":
            op = nd["props"].get("operation", "GREATER_THAN")
            args = [self.in_expr(nd, "A"), self.in_expr(nd, "B")]
            if op == "EQUAL":
                args.append(self.in_expr(nd, "Epsilon"))
            return {"op": "cmp." + op.lower(), "args": args}
        if idn == "FunctionNodeBooleanMath":
            op = nd["props"].get("operation", "AND")
            args = [self.sock_expr(s) for s in nd["inputs"] if s.get("enabled", True)]
            return {"op": "bool." + op.lower(), "args": args}
        if idn == "FunctionNodeEulerToRotation":
            return {"op": "euler_to_rotation", "args": [self.in_expr(nd, "Euler")]}
        if idn == "FunctionNodeAlignRotationToVector":
            return {"op": "align_rotation", "axis": nd["props"].get("axis", "Z"),
                    "args": [self.in_expr(nd, "Factor"), self.in_expr(nd, "Vector")]}
        if idn == "GeometryNodeSwitch":
            return {"op": "switch", "args": [self.in_expr(nd, "Switch"),
                                             self.in_expr(nd, "False"), self.in_expr(nd, "True")]}
        raise ExportRefused("no expression rule for %s (node %r, socket %r)" % (idn, nname, sname))

    def sock_expr(self, s):
        if s["linked"] and s.get("links"):
            return self.expr(s["links"][0])
        v = s.get("value")
        if isinstance(v, (list, tuple)):
            v = list(v)
        return {"const": v}

    def in_expr(self, nd, name, sock=None):
        s = sock or in_sock(nd, name)
        if s is None:
            return {"const": None}
        return self.sock_expr(s)

    def aux_block(self, node_name, kind, **fields):
        if node_name in self.block_of_node:
            return self.block_of_node[node_name]
        bid = self.add(kind, node_name, **fields)
        return bid

    # ---------------------------------------------------------- assets
    def asset_for(self, link, ctx):
        """Lower an Instance-input subtree to an asset spec. Cube chains become
        a shared unit cube + per-instance scale; anything else is baked at
        current parameter values (recorded in the report as an approximation)."""
        nname = link["node"]
        nd = node(self.ir, nname)
        idn = nd["idname"]
        shift = None
        tf_name = None
        if idn == "GeometryNodeTransform":
            tf_name = nname
            tlink = link_of(nd, "Translation")
            shift = self.expr(tlink) if tlink else {"const": list(value_of(nd, "Translation", (0, 0, 0)))}
            inner = link_of(nd, "Geometry")
            if inner is None:
                raise ExportRefused("Transform %r has no geometry input" % nname)
            nd2 = node(self.ir, inner["node"])
            if nd2["idname"] != "GeometryNodeMeshCube":
                return self.baked_asset(inner["node"], ctx)
            nd, nname, idn = nd2, inner["node"], nd2["idname"]
        if idn == "GeometryNodeMeshCube":
            size_link = link_of(nd, "Size")
            size = self.expr(size_link) if size_link else {"const": list(value_of(nd, "Size", (1, 1, 1)))}
            origin = "center"
            if shift is not None:
                if self.is_half_z_shift(shift, size):
                    origin = "bottom"
                else:
                    # bake the WHOLE transform subtree so the odd origin is
                    # preserved in the mesh itself (no half-sunk instances)
                    self.sess.warn("asset %r: non-standard cube origin shift — baked "
                                   "with the shift applied" % nname)
                    return self.baked_asset(tf_name or nname, ctx)
            key = "unit_cube_" + origin
            self.assets.setdefault(key, {"id": key, "kind": "unit_cube", "origin": origin,
                                         "file": "SM_GNue_%s.fbx" % key.title().replace("_", "")})
            return {"asset": key, "size": size}
        return self.baked_asset(nname, ctx)

    def is_half_z_shift(self, shift, size):
        """shift == (0, 0, size.z * 0.5) — numeric consts or structural exprs."""
        sc, zc = shift.get("const"), size.get("const")
        if isinstance(sc, list) and len(sc) >= 3 \
                and abs(sc[0]) < 1e-9 and abs(sc[1]) < 1e-9:
            if isinstance(zc, list) and len(zc) >= 3 and abs(sc[2] - zc[2] * 0.5) < 1e-6:
                return True
        if shift.get("op") != "vec3":
            return False
        x, y, z = shift["args"]
        if x.get("const") not in (0, 0.0) or y.get("const") not in (0, 0.0):
            return False
        if z.get("op") != "math.multiply":
            return False
        a, b = z["args"][0], z["args"][1]
        if b.get("const") != 0.5:
            a, b = b, a
        if b.get("const") != 0.5:
            return False
        size_z = size["args"][2] if size.get("op") == "vec3" else {"op": "vec.z", "args": [size]}
        return json.dumps(a, sort_keys=True) == json.dumps(size_z, sort_keys=True)

    def baked_asset(self, node_name, ctx, extra_shift=None):
        key = "baked_" + node_name.replace(" ", "_").replace(".", "_")
        if key not in self.assets:
            self.assets[key] = {"id": key, "kind": "baked", "source_node": node_name,
                                "file": "SM_GNue_%s.fbx" % node_name.replace(" ", "").replace(".", "_")}
            self.sess.warn("asset %r (%s): baked at current parameter values — parametric "
                           "dependence inside the instance source is frozen" % (node_name, ctx))
        spec = {"asset": key, "size": {"const": [1.0, 1.0, 1.0]}}
        if extra_shift is not None:
            spec["origin_shift"] = extra_shift
        return spec

    # ---------------------------------------------------------- geometry
    def geo_ref(self, link, consumer):
        if link is None:
            raise ExportRefused("geometry input of %r is unlinked" % consumer)
        return self.geometry(link["node"], link["socket"])

    def geometry(self, nname, out_sock=None):
        """Lower a geometry-producing node (memoized) -> block id."""
        if nname in self.block_of_node:
            base = self.block_of_node[nname]
            if out_sock == "Inverted":
                return base + ":inverted"
            return base
        nd = node(self.ir, nname)
        idn = nd["idname"]
        h = getattr(self, "geo_" + idn, None)
        if h is None:
            if idn in BAKED_PRIMITIVES:
                raise ExportRefused(
                    "node %r (%s) is supported as an *instance source* — wire it into "
                    "the Instance input of Instance on Points, not directly as output "
                    "geometry" % (nname, idn))
            raise ExportRefused("no geometry rule for %s (node %r)" % (idn, nname))
        bid = h(nname, nd)
        if out_sock == "Inverted":
            return bid + ":inverted"
        return bid

    def geo_NodeGroupInput(self, nname, nd):
        return self.aux_block(nname, "geometry.input")

    def geo_GeometryNodeCurvePrimitiveLine(self, nname, nd):
        return self.add("curve.line", nname,
                        start=self.in_expr(nd, "Start"), end=self.in_expr(nd, "End"))

    def geo_GeometryNodeResampleCurve(self, nname, nd):
        mode = nd["props"].get("mode") or value_of(nd, "Mode", "Count")
        return self.add("curve.resample", nname, curve=self.geo_ref(link_of(nd, "Curve"), nname),
                        mode=str(mode).lower(), count=self.in_expr(nd, "Count"),
                        length=self.in_expr(nd, "Length"))

    def geo_GeometryNodeSetPosition(self, nname, nd):
        blk = {"geometry": self.geo_ref(link_of(nd, "Geometry"), nname)}
        if link_of(nd, "Position"):
            blk["position"] = self.in_expr(nd, "Position")
        blk["offset"] = self.in_expr(nd, "Offset")
        if link_of(nd, "Selection"):
            blk["selection"] = self.in_expr(nd, "Selection")
        return self.add("geometry.set_position", nname, **blk)

    def geo_GeometryNodeTrimCurve(self, nname, nd):
        self.sess.features.add("trim")
        return self.add("curve.trim", nname,
                        curve=self.geo_ref(link_of(nd, "Curve"), nname),
                        mode=str(nd["props"].get("mode", "FACTOR")).lower(),
                        start=self.in_expr(nd, "Start"),
                        end=self.in_expr(nd, "End"))

    def geo_GeometryNodeCurveSplineType(self, nname, nd):
        return self.add("curve.set_type", nname, curve=self.geo_ref(link_of(nd, "Curve"), nname),
                        spline_type=nd["props"].get("spline_type", "CATMULL_ROM").lower())

    def geo_GeometryNodeCaptureAttribute(self, nname, nd):
        items = {}
        for s in nd["inputs"]:
            if s["name"] not in ("Geometry",) and s.get("enabled", True) and s["linked"]:
                items[s["name"]] = self.sock_expr(s)
        return self.add("attribute.capture", nname,
                        geometry=self.geo_ref(link_of(nd, "Geometry"), nname),
                        domain=nd["props"].get("domain", "POINT"), items=items)

    def geo_GeometryNodeCurveToPoints(self, nname, nd):
        return self.add("curve.to_points", nname, curve=self.geo_ref(link_of(nd, "Curve"), nname),
                        mode=nd["props"].get("mode", "COUNT").lower(), count=self.in_expr(nd, "Count"))

    def geo_GeometryNodeDuplicateElements(self, nname, nd):
        return self.add("points.duplicate", nname,
                        geometry=self.geo_ref(link_of(nd, "Geometry"), nname),
                        domain=nd["props"].get("domain", "POINT"),
                        amount=self.in_expr(nd, "Amount"))

    def geo_GeometryNodePointsToCurves(self, nname, nd):
        return self.add("points.to_curves", nname,
                        points=self.geo_ref(link_of(nd, "Points"), nname),
                        group_id=self.in_expr(nd, "Curve Group ID"))

    def geo_GeometryNodePoints(self, nname, nd):
        return self.add("point.create", nname, count=self.in_expr(nd, "Count"),
                        position=self.in_expr(nd, "Position"))

    def geo_GeometryNodeMeshLine(self, nname, nd):
        return self.add("point.line", nname, count=self.in_expr(nd, "Count"),
                        start=self.in_expr(nd, "Start Location"),
                        offset=self.in_expr(nd, "Offset"))

    def geo_GeometryNodeInstanceOnPoints(self, nname, nd):
        ilink = link_of(nd, "Instance")
        if ilink is None:
            raise ExportRefused("Instance on Points %r has no Instance input" % nname)
        blk = {"points": self.geo_ref(link_of(nd, "Points"), nname),
               "instance": self.asset_for(ilink, nname)}
        if link_of(nd, "Selection"):
            blk["selection"] = self.in_expr(nd, "Selection")
        if link_of(nd, "Rotation"):
            blk["rotation"] = self.in_expr(nd, "Rotation")
        if link_of(nd, "Scale"):
            blk["scale"] = self.in_expr(nd, "Scale")
        return self.add("instance.on_points", nname, **blk)

    def geo_GeometryNodeRotateInstances(self, nname, nd):
        return self.add("instance.rotate", nname,
                        instances=self.geo_ref(link_of(nd, "Instances"), nname),
                        rotation=self.in_expr(nd, "Rotation"),
                        local=bool(value_of(nd, "Local Space", True)))

    def geo_GeometryNodeTranslateInstances(self, nname, nd):
        return self.add("instance.translate", nname,
                        instances=self.geo_ref(link_of(nd, "Instances"), nname),
                        translation=self.in_expr(nd, "Translation"),
                        local=bool(value_of(nd, "Local Space", True)))

    def geo_GeometryNodeScaleInstances(self, nname, nd):
        return self.add("instance.scale", nname,
                        instances=self.geo_ref(link_of(nd, "Instances"), nname),
                        scale=self.in_expr(nd, "Scale"))

    def geo_GeometryNodeInstancesToPoints(self, nname, nd):
        return self.add("instances.to_points", nname,
                        instances=self.geo_ref(link_of(nd, "Instances"), nname))

    def geo_GeometryNodeSeparateGeometry(self, nname, nd):
        return self.add("geometry.separate", nname,
                        geometry=self.geo_ref(link_of(nd, "Geometry"), nname),
                        domain=nd["props"].get("domain", "POINT"),
                        selection=self.in_expr(nd, "Selection"))

    def geo_GeometryNodeDeleteGeometry(self, nname, nd):
        return self.add("geometry.delete", nname,
                        geometry=self.geo_ref(link_of(nd, "Geometry"), nname),
                        domain=nd["props"].get("domain", "POINT"),
                        selection=self.in_expr(nd, "Selection"))

    def geo_GeometryNodeStoreNamedAttribute(self, nname, nd):
        return self.add("attribute.store", nname,
                        geometry=self.geo_ref(link_of(nd, "Geometry"), nname),
                        name=value_of(nd, "Name", ""),
                        domain=nd["props"].get("domain", "POINT"),
                        data_type=nd["props"].get("data_type", "FLOAT"),
                        value=self.in_expr(nd, "Value"))

    def geo_GeometryNodeRealizeInstances(self, nname, nd):
        self.sess.features.add("instance_surface_scatter")
        return self.add("instances.realize", nname,
                        instances=self.geo_ref(link_of(nd, "Geometry"), nname))

    def geo_GeometryNodeSetMaterial(self, nname, nd):
        mat = value_of(nd, "Material")
        self.sess.features.add("materials")
        self.sess.warn("Set Material %r: material %r recorded by name — the importer "
                       "applies a matching /Game material if one exists" % (nname, mat))
        return self.add("material.set", nname,
                        geometry=self.geo_ref(link_of(nd, "Geometry"), nname),
                        material=mat or "")

    def geo_GeometryNodeDistributePointsOnFaces(self, nname, nd):
        mesh = self.geo_ref(link_of(nd, "Mesh"), nname)
        base = self.blocks_by_id().get(mesh.split(":")[0], {})
        surface_kind = "input"
        if base.get("type") == "instances.realize":
            surface_kind = "instances"
        elif base.get("type") == "material.set":
            # look through material pass-through
            inner = self.blocks_by_id().get(base["geometry"].split(":")[0], {})
            if inner.get("type") == "instances.realize":
                surface_kind = "instances"
                mesh = base["geometry"]
            elif inner.get("type") != "geometry.input":
                raise ExportRefused("scatter %r samples generated geometry — only the "
                                    "group input mesh or realized instances are supported" % nname)
        elif base.get("type") != "geometry.input":
            raise ExportRefused("scatter %r samples generated geometry — only the group's "
                                "input mesh or realized instances are supported" % nname)
        blk = {"surface": mesh, "surface_kind": surface_kind,
               "density": self.in_expr(nd, "Density"),
               "seed": self.in_expr(nd, "Seed")}
        if link_of(nd, "Selection"):
            blk["selection"] = self.in_expr(nd, "Selection")
        return self.add("scatter.on_surface", nname, **blk)

    def geo_GeometryNodeSwitch(self, nname, nd):
        if nd["props"].get("input_type", "GEOMETRY") != "GEOMETRY":
            raise ExportRefused("Switch %r: only GEOMETRY switches are geometry blocks" % nname)
        blk = {"switch": self.in_expr(nd, "Switch")}
        for key, sock_name in (("false_branch", "False"), ("true_branch", "True")):
            l = link_of(nd, sock_name)
            blk[key] = self.geometry(l["node"], l["socket"]) if l else None
        return self.add("geometry.switch", nname, **blk)

    def geo_GeometryNodeJoinGeometry(self, nname, nd):
        s = in_sock(nd, "Geometry")
        links = s.get("links", []) if s else []
        return self.add("geometry.join", nname,
                        inputs=[self.geometry(l["node"], l["socket"]) for l in links])

    def geo_GeometryNodeTriangulate(self, nname, nd):
        # UE meshes are triangles; pass geometry through and note it
        self.sess.warn("Triangulate %r: implicit in UE — passed through" % nname)
        return self.geo_ref(link_of(nd, "Mesh"), nname)

    def blocks_by_id(self):
        return {b["id"]: b for b in self.blocks}

    # ---------------------------------------------------------- entry
    def run(self):
        out = node(self.ir, self.ir["output_node"])
        l = link_of(out, "Geometry")
        if l is None:
            raise ExportRefused("Group Output geometry is unlinked")
        root = self.geometry(l["node"], l["socket"])
        return {"root": root, "blocks": self.blocks, "assets": list(self.assets.values())}


# ------------------------------------------------------------------ evaluator

class NonConstant(Exception):
    pass


def _v(x):
    return x if isinstance(x, list) else [x, x, x]


def evaluate(e, params, env=None):
    """Numerically evaluate an expression tree. env supplies per-point context
    (spline_factor, index, tangent, ...). Raises NonConstant on random leaves
    or attrs missing from env — callers decide how to realize those in UE."""
    env = env or {}
    if e is None:
        raise NonConstant("empty")
    if "const" in e:
        return e["const"]
    if "param" in e:
        if e["param"] not in params:
            raise NonConstant("unknown param " + e["param"])
        return params[e["param"]]
    if "attr" in e:
        if e["attr"] in env:
            return env[e["attr"]]
        raise NonConstant("attr " + e["attr"])
    if "random" in e:
        raise NonConstant("random")
    if "block_output" in e:
        key = "%s.%s" % (e["block_output"]["block"], e["block_output"]["output"])
        if key in env:
            return env[key]
        raise NonConstant("block_output " + key)
    op = e.get("op")
    if op is None:
        raise NonConstant("unrecognized expr %r" % e)
    A = [evaluate(a, params, env) for a in e.get("args", [])]
    f = _EVAL_OPS.get(op)
    if f is None:
        raise NonConstant("op " + op)
    return f(A)


def _mapr(a):
    v, fmin, fmax, tmin, tmax = a
    if fmax == fmin:
        return tmin
    t = (v - fmin) / (fmax - fmin)
    return tmin + t * (tmax - tmin)


_EVAL_OPS = {
    "math.add": lambda a: a[0] + a[1],
    "math.subtract": lambda a: a[0] - a[1],
    "math.multiply": lambda a: a[0] * a[1],
    "math.divide": lambda a: (a[0] / a[1]) if a[1] else 0.0,
    "math.multiply_add": lambda a: a[0] * a[1] + a[2],
    "math.sine": lambda a: __import__("math").sin(a[0]),
    "math.cosine": lambda a: __import__("math").cos(a[0]),
    "math.power": lambda a: a[0] ** a[1],
    "math.sqrt": lambda a: a[0] ** 0.5,
    "math.absolute": lambda a: abs(a[0]),
    "math.minimum": lambda a: min(a[0], a[1]),
    "math.maximum": lambda a: max(a[0], a[1]),
    "math.floor": lambda a: float(int(a[0]) if a[0] >= 0 else -int(-a[0] + 0.999999)),
    "math.floored_modulo": lambda a: a[0] % a[1] if a[1] else 0.0,
    "math.greater_than": lambda a: 1.0 if a[0] > a[1] else 0.0,
    "math.less_than": lambda a: 1.0 if a[0] < a[1] else 0.0,
    "math.modulo": lambda a: __import__("math").fmod(a[0], a[1]) if a[1] else 0.0,
    "clamp": lambda a: max(a[1], min(a[2], a[0])),
    "map_range": _mapr,
    "mix": lambda a: ([a[1][i] + (a[2][i] - a[1][i]) * a[0] for i in range(3)]
                      if isinstance(a[1], list) else a[1] + (a[2] - a[1]) * a[0]),
    "vec3": lambda a: [a[0], a[1], a[2]],
    "vec.x": lambda a: _v(a[0])[0],
    "vec.y": lambda a: _v(a[0])[1],
    "vec.z": lambda a: _v(a[0])[2],
    "vmath.add": lambda a: [_v(a[0])[i] + _v(a[1])[i] for i in range(3)],
    "vmath.subtract": lambda a: [_v(a[0])[i] - _v(a[1])[i] for i in range(3)],
    "vmath.scale": lambda a: [_v(a[0])[i] * a[1] for i in range(3)],
    "vmath.cross_product": lambda a: [
        _v(a[0])[1] * _v(a[1])[2] - _v(a[0])[2] * _v(a[1])[1],
        _v(a[0])[2] * _v(a[1])[0] - _v(a[0])[0] * _v(a[1])[2],
        _v(a[0])[0] * _v(a[1])[1] - _v(a[0])[1] * _v(a[1])[0]],
    "vmath.normalize": lambda a: (lambda v, n: [c / n for c in v] if n else [0, 0, 0])(
        _v(a[0]), sum(c * c for c in _v(a[0])) ** 0.5),
    "vmath.length": lambda a: sum(c * c for c in _v(a[0])) ** 0.5,
    "vmath.dot_product": lambda a: sum(_v(a[0])[i] * _v(a[1])[i] for i in range(3)),
    "cmp.greater_than": lambda a: a[0] > a[1],
    "cmp.less_than": lambda a: a[0] < a[1],
    "cmp.equal": lambda a: abs(a[0] - a[1]) <= (a[2] if len(a) > 2 else 1e-6),
    "bool.and": lambda a: bool(a[0]) and bool(a[1]),
    "bool.or": lambda a: bool(a[0]) or bool(a[1]),
    "bool.not": lambda a: not a[0],
    "switch": lambda a: a[2] if a[0] else a[1],
}


# ------------------------------------------------------------------ pipeline

def lower(ir, sess):
    validate(ir, sess)
    lowering = Lowering(ir, sess)
    result = lowering.run()
    # coverage: every node must have been consumed by some rule
    consumed = set(lowering.block_of_node)
    expr_reachable = set()  # expression nodes are consumed transitively; approximate
    for name, nd in ir["nodes"].items():
        if name in consumed or nd["idname"] in ("NodeGroupOutput",):
            continue
        geoish = any(s["type"] == "GEOMETRY" for s in nd["outputs"])
        if geoish and nd["idname"] not in ("GeometryNodeMeshCube", "GeometryNodeTransform") \
                and nd["idname"] not in BAKED_PRIMITIVES:
            sess.warn("node %r (%s) produces geometry but was never reached from the "
                      "output — dead branch, not exported" % (name, nd["idname"]))
    return result


def make_descriptor(ir, lowered, sess, meshes_dir="meshes"):
    params = []
    for p in ir["params"]:
        q = dict(p)
        params.append(q)
    return {
        "format": "gnue-descriptor",
        "version": DESCRIPTOR_VERSION,
        "family": "graph",
        "source": {"blender_version": ir.get("blender_version", "?"),
                   "node_group": ir["node_group"], "file": ir.get("blend_file", "")},
        "units": {"length": "m", "rotation": "rad", "up": "+Z", "handedness": "right"},
        "conventions": {"curve_tangent_axis": "+Z",
                        "note": "Blender aligns instance +Z to curve tangent; UE Spline "
                                "Sampler aligns +X — importer permutes axes."},
        "parameters": params,
        "assets": [dict(a, file=meshes_dir + "/" + a["file"]) for a in lowered["assets"]],
        "requires": sorted(sess.features),
        "root": lowered["root"],
        "blocks": lowered["blocks"],
        "warnings": list(sess.warnings),
    }


def make_report(ir, descriptor, sess, refused=None):
    lines = []
    lines.append("GN->UE export report — node group %r" % ir["node_group"])
    lines.append("Blender %s, descriptor v%s (family: graph)" %
                 (ir.get("blender_version", "?"), DESCRIPTOR_VERSION))
    if refused:
        lines.append("")
        lines.append("EXPORT REFUSED — the graph is not fully translatable:")
        for e in sess.errors:
            lines.append("  ERROR: " + e)
        return "\n".join(lines)
    lines.append("nodes: %d -> blocks: %d, assets: %d, params: %d" %
                 (len(ir["nodes"]), len(descriptor["blocks"]),
                  len(descriptor["assets"]), len(descriptor["parameters"])))
    kinds = {}
    for b in descriptor["blocks"]:
        kinds[b["type"]] = kinds.get(b["type"], 0) + 1
    for k in sorted(kinds):
        lines.append("  block %-22s x%d" % (k, kinds[k]))
    lines.append("")
    lines.append("Known approximations (by design, statistical equivalence):")
    lines.append("  - random values use UE's RNG (distributions match, placements differ)")
    lines.append("  - baked assets freeze parameter dependence at export-time values")
    if descriptor.get("surface_asset"):
        lines.append("  - scatter surface exported (SM_GNue_Surface.fbx) — the effect")
        lines.append("    carries its own surface mesh and rebuilds it at the PCG volume")
    elif any(b["type"] == "scatter.on_surface" for b in descriptor["blocks"]):
        lines.append("  - scatter samples YOUR UE level's ground (any collidable surface")
        lines.append("    under the PCG volume) — the Blender input mesh is not exported")
    for w in sess.warnings:
        lines.append("  WARNING: " + w)
    return "\n".join(lines)
