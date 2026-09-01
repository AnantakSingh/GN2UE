"""DominoSpiral_V1 — spiral of dominoes frozen mid-topple, V1-core nodes ONLY.

Runs inside Blender via the blender-mcp addon socket.

Pipeline-compatibility design (import_gnue2 numeric kernel):
  - Fermat spiral (theta = k*sqrt(i)) -> near-constant spacing from pure
    closed-form index math (sqrt/sin/cos are in the evaluator table)
  - the topple wave is DETERMINISTIC per index: fall = smoothstep of
    (Progress-adjusted wavefront), composed manually as f*f*(3-2f) so both
    engines evaluate the exact same easing (Map Range smoothstep mode would
    silently lower as linear)
  - randomness (yaw jitter) only in instance transforms -> TransformPoints
The Progress slider is the UE demo: scrubbing it plays the topple wave.
"""
import bpy

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

GROUP_NAME = "DominoSpiral_V1"
PROBLEMS = []
TAU = 6.283185307


def P(msg):
    PROBLEMS.append(msg)
    print("PROBLEM:", msg)


def fresh_group():
    old = bpy.data.node_groups.get(GROUP_NAME)
    if old:
        bpy.data.node_groups.remove(old)
    return bpy.data.node_groups.new(GROUP_NAME, "GeometryNodeTree")


def sock(ng, name, in_out, stype, default=None, minv=None, maxv=None):
    s = ng.interface.new_socket(name=name, in_out=in_out, socket_type=stype)
    if default is not None:
        try:
            s.default_value = default
        except Exception as e:
            P("iface %s: %s" % (name, e))
    for attr, v in (("min_value", minv), ("max_value", maxv)):
        if v is not None:
            try:
                setattr(s, attr, v)
            except Exception:
                pass
    return s


class G:
    def __init__(self, ng):
        self.ng = ng

    def n(self, idname, label="", props=None, inputs=None, x=0, y=0):
        nd = self.ng.nodes.new(idname)
        if label:
            nd.label = label
        nd.location = (x, y)
        for k, v in (props or {}).items():
            try:
                setattr(nd, k, v)
            except Exception:
                try:
                    nd.inputs[k.title()].default_value = v
                except Exception as e:
                    P("%s prop %s: %s" % (idname, k, e))
        for k, v in (inputs or {}).items():
            try:
                nd.inputs[k].default_value = v
            except Exception as e:
                P("%s input %r: %s" % (idname, k, e))
        return nd

    def l(self, a, out, b, inp):
        try:
            self.ng.links.new(a.outputs[out], b.inputs[inp])
        except Exception as e:
            P("link %s.%r->%s.%r: %s" % (a.bl_idname, out, b.bl_idname, inp, e))

    def math(self, op, a=None, b=None, x=0, y=0, c1=None, c2=None, label=""):
        nd = self.n("ShaderNodeMath", label or op.lower(), {"operation": op}, x=x, y=y)
        if a is not None:
            self.l(a[0], a[1], nd, 0)
        elif c1 is not None:
            nd.inputs[0].default_value = c1
        if b is not None:
            self.l(b[0], b[1], nd, 1)
        elif c2 is not None:
            nd.inputs[1].default_value = c2
        return nd


def build():
    ng = fresh_group()
    g = G(ng)

    sock(ng, "Geometry", "INPUT", "NodeSocketGeometry")
    sock(ng, "Dominoes", "INPUT", "NodeSocketInt", 150, 8, 600)
    sock(ng, "Turns", "INPUT", "NodeSocketFloat", 3.2, 0.5, 12.0)
    sock(ng, "Radius", "INPUT", "NodeSocketFloat", 4.5, 0.5, 30.0)
    # (width across path, thickness along path, height)
    sock(ng, "Tile Size", "INPUT", "NodeSocketVector", (0.34, 0.08, 0.62))
    sock(ng, "Progress", "INPUT", "NodeSocketFloat", 0.45, 0.0, 1.0)
    sock(ng, "Wave Width", "INPUT", "NodeSocketFloat", 0.10, 0.01, 0.5)
    sock(ng, "Yaw Jitter", "INPUT", "NodeSocketFloat", 0.04, 0.0, 0.5)
    sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    sock(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")

    gin = g.n("NodeGroupInput", "Params", x=-2000)
    gout = g.n("NodeGroupOutput", "Out", x=1500)

    # ---- Fermat spiral: theta = k*sqrt(i), r = Radius*sqrt(i/(N-1)) ----
    idx = g.n("GeometryNodeInputIndex", "Idx", x=-1750, y=300)
    nm1 = g.math("SUBTRACT", x=-1750, y=140, c2=1.0)
    g.l(gin, "Dominoes", nm1, 0)
    sqN = g.math("SQRT", a=(nm1, "Value"), x=-1590, y=140, label="sqrt(N-1)")
    turns_rad = g.math("MULTIPLY", x=-1750, y=20, c2=TAU)
    g.l(gin, "Turns", turns_rad, 0)
    k = g.math("DIVIDE", a=(turns_rad, "Value"), b=(sqN, "Value"), x=-1430, y=60, label="k")

    sqi = g.math("SQRT", a=(idx, "Index"), x=-1590, y=300, label="sqrt(i)")
    theta = g.math("MULTIPLY", a=(k, "Value"), b=(sqi, "Value"), x=-1430, y=300, label="theta")
    rfrac = g.math("DIVIDE", a=(sqi, "Value"), b=(sqN, "Value"), x=-1430, y=180)
    r = g.math("MULTIPLY", a=(rfrac, "Value"), x=-1270, y=180, label="r")
    g.l(gin, "Radius", r, 1)

    cosr = g.math("COSINE", a=(theta, "Value"), x=-1270, y=340)
    sinr = g.math("SINE", a=(theta, "Value"), x=-1270, y=260)
    px = g.math("MULTIPLY", a=(cosr, "Value"), b=(r, "Value"), x=-1110, y=340)
    py = g.math("MULTIPLY", a=(sinr, "Value"), b=(r, "Value"), x=-1110, y=260)
    ppos = g.n("ShaderNodeCombineXYZ", "SpiralPos", x=-950, y=300)
    g.l(px, "Value", ppos, "X")
    g.l(py, "Value", ppos, "Y")

    pts = g.n("GeometryNodePoints", "Spiral", x=-790, y=300)
    g.l(gin, "Dominoes", pts, "Count")
    g.l(ppos, "Vector", pts, "Position")

    # ---- topple wave: t = i/(N-1); f = clamp((P*(1+w)-t)/w); s = f^2(3-2f)
    t = g.math("DIVIDE", a=(idx, "Index"), b=(nm1, "Value"), x=-1110, y=-60, label="t")
    wplus = g.math("ADD", x=-1110, y=-200, c1=1.0)
    g.l(gin, "Wave Width", wplus, 1)
    pfront = g.math("MULTIPLY", a=(wplus, "Value"), x=-950, y=-200, label="front")
    g.l(gin, "Progress", pfront, 1)
    fraw = g.math("SUBTRACT", a=(pfront, "Value"), b=(t, "Value"), x=-790, y=-130)
    fdiv = g.math("DIVIDE", a=(fraw, "Value"), x=-630, y=-130)
    g.l(gin, "Wave Width", fdiv, 1)
    fcl = g.n("ShaderNodeClamp", "clamp01", inputs={"Min": 0.0, "Max": 1.0}, x=-470, y=-130)
    g.l(fdiv, "Value", fcl, "Value")
    # manual smoothstep so UE evaluates the identical curve
    f2 = g.math("MULTIPLY", a=(fcl, "Result"), b=(fcl, "Result"), x=-310, y=-130)
    f3 = g.math("MULTIPLY", a=(fcl, "Result"), x=-310, y=-250, c2=2.0)
    threeminus = g.math("SUBTRACT", a=None, b=(f3, "Value"), x=-150, y=-250, c1=3.0)
    ss = g.math("MULTIPLY", a=(f2, "Value"), b=(threeminus, "Value"), x=10, y=-190, label="smooth")
    # negative X-rotation tips local +Z toward +Y (the travel direction)
    tilt = g.math("MULTIPLY", a=(ss, "Value"), x=170, y=-190, c2=-1.5)  # ~86 deg

    # ---- domino: bottom-origin thin slab, faces along travel -----------
    tile = g.n("GeometryNodeMeshCube", "Tile", x=-790, y=560)
    g.l(gin, "Tile Size", tile, "Size")
    tsz = g.n("ShaderNodeSeparateXYZ", "Tz", x=-950, y=460)
    g.l(gin, "Tile Size", tsz, "Vector")
    thalf = g.math("MULTIPLY", a=(tsz, "Z"), x=-790, y=420, c2=0.5)
    tshift = g.n("ShaderNodeCombineXYZ", "TShift", x=-630, y=420)
    g.l(thalf, "Value", tshift, "Z")
    tileb = g.n("GeometryNodeTransform", "TileB", x=-630, y=560)
    g.l(tile, "Mesh", tileb, "Geometry")
    g.l(tshift, "Vector", tileb, "Translation")

    inst = g.n("GeometryNodeInstanceOnPoints", "Dominoes", x=-430, y=300)
    g.l(pts, "Points", inst, "Points")
    g.l(tileb, "Geometry", inst, "Instance")

    # face along travel: Euler-Z by `yaw` sends local +Y to yaw+90deg, so
    # yaw = theta puts the tile's thickness along the tangent
    yaw = g.math("ADD", a=(theta, "Value"), x=-630, y=140, c2=0.0)
    yawv = g.n("ShaderNodeCombineXYZ", "YawE", x=-470, y=140)
    g.l(yaw, "Value", yawv, "Z")
    yawrot = g.n("FunctionNodeEulerToRotation", "YawRot", x=-310, y=140)
    g.l(yawv, "Vector", yawrot, "Euler")
    face = g.n("GeometryNodeRotateInstances", "Face", x=-230, y=300)
    g.l(inst, "Instances", face, "Instances")
    g.l(yawrot, "Rotation", face, "Rotation")

    # topple: rotate about local X by the wave amount
    tiltv = g.n("ShaderNodeCombineXYZ", "TiltE", x=330, y=-190)
    g.l(tilt, "Value", tiltv, "X")
    tiltrot = g.n("FunctionNodeEulerToRotation", "TiltRot", x=490, y=-190)
    g.l(tiltv, "Vector", tiltrot, "Euler")
    topple = g.n("GeometryNodeRotateInstances", "Topple", x=-30, y=300)
    g.l(face, "Instances", topple, "Instances")
    g.l(tiltrot, "Rotation", topple, "Rotation")

    # tiny random yaw jitter (statistical — lowers to TransformPoints)
    jneg = g.math("MULTIPLY", x=-30, y=80, c2=-1.0)
    g.l(gin, "Yaw Jitter", jneg, 0)
    jminv = g.n("ShaderNodeCombineXYZ", "JMin", x=130, y=40)
    jmaxv = g.n("ShaderNodeCombineXYZ", "JMax", x=130, y=120)
    g.l(jneg, "Value", jminv, "Z")
    g.l(gin, "Yaw Jitter", jmaxv, "Z")
    jr = g.n("FunctionNodeRandomValue", "JRand", {"data_type": "FLOAT_VECTOR"}, x=290, y=80)
    g.l(jminv, "Vector", jr, "Min")
    g.l(jmaxv, "Vector", jr, "Max")
    g.l(gin, "Seed", jr, "Seed")
    jrot = g.n("FunctionNodeEulerToRotation", "JRot", x=450, y=80)
    g.l(jr, "Value", jrot, "Euler")
    jig = g.n("GeometryNodeRotateInstances", "Jitter", x=170, y=300)
    g.l(topple, "Instances", jig, "Instances")
    g.l(jrot, "Rotation", jig, "Rotation")

    join = g.n("GeometryNodeJoinGeometry", "Run", x=1200, y=200)
    for src, out in ((jig, "Instances"), (gin, "Geometry")):
        try:
            g.ng.links.new(src.outputs[out], join.inputs["Geometry"])
        except Exception as e:
            P("join: %s" % e)
    g.l(join, "Geometry", gout, "Geometry")
    return ng


def validate(ng):
    used = sorted({n.bl_idname for n in ng.nodes})
    bad = [i for i in used if i not in V1_WHITELIST]
    print("NODES: %d (%d types)" % (len(ng.nodes), len(used)))
    print("V1 VALIDATION:", "PASS" if not bad else "FAIL " + str(bad))
    return bad


def attach(ng):
    obj = bpy.data.objects.get("V1DominoSpiral_Demo")
    if obj is None:
        bpy.ops.mesh.primitive_plane_add(size=12, location=(60, 0, 0))
        obj = bpy.context.active_object
        obj.name = "V1DominoSpiral_Demo"
    for m in list(obj.modifiers):
        obj.modifiers.remove(m)
    obj.modifiers.new("DominoSpiralV1", "NODES").node_group = ng
    return obj


ng = build()
bad = validate(ng)
obj = attach(ng)
bpy.context.view_layer.update()
print("BUILD DONE: group=%s nodes=%d problems=%d object=%s"
      % (ng.name, len(ng.nodes), len(PROBLEMS), obj.name))
for p in PROBLEMS:
    print("  P:", p)
