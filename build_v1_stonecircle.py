"""StoneCircle_V1 — ancient stone circle ruins, V1-core nodes ONLY.

Runs inside Blender via the blender-mcp addon socket:
    python tools/bl_exec.py build_v1_stonecircle.py
or headless:  blender --background --python build_v1_stonecircle.py   (PORTABILITY.md §2.4)

Design notes for pipeline compatibility (import_gnue2 numeric kernel):
  - point positions are DETERMINISTIC (index trig) — no random leaves there
  - the ruin pattern is deterministic (every Nth stone falls, via index modulo),
    so Separate Geometry selections stay kernel-evaluable
  - randomness lives only in instance transforms (wobble/sink/size) and the
    rubble/grass scatter — the paths that lower to PCG TransformPoints ranges
Whitelist enforcement identical to build_v1_bridge.py.
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

GROUP_NAME = "StoneCircle_V1"
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
            P("iface default %s: %s" % (name, e))
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
                    P("%s prop %s=%r: %s" % (idname, k, v, e))
        for k, v in (inputs or {}).items():
            try:
                nd.inputs[k].default_value = v
            except Exception as e:
                P("%s input %r=%r: %s" % (idname, k, v, e))
        return nd

    def l(self, a, out, b, inp):
        try:
            self.ng.links.new(a.outputs[out], b.inputs[inp])
        except Exception as e:
            P("link %s.%r -> %s.%r: %s" % (a.bl_idname, out, b.bl_idname, inp, e))

    def math(self, op, a=None, b=None, label="", x=0, y=0, const1=None, const2=None):
        nd = self.n("ShaderNodeMath", label or op.lower(), {"operation": op}, x=x, y=y)
        if a is not None:
            self.l(a[0], a[1], nd, 0)
        elif const1 is not None:
            nd.inputs[0].default_value = const1
        if b is not None:
            self.l(b[0], b[1], nd, 1)
        elif const2 is not None:
            nd.inputs[1].default_value = const2
        return nd


def build():
    ng = fresh_group()
    g = G(ng)

    sock(ng, "Geometry", "INPUT", "NodeSocketGeometry")
    sock(ng, "Stones", "INPUT", "NodeSocketInt", 12, 3, 64)
    sock(ng, "Radius", "INPUT", "NodeSocketFloat", 4.0, 1.0, 30.0)
    sock(ng, "Stone Size", "INPUT", "NodeSocketVector", (0.8, 0.5, 2.4))
    sock(ng, "Size Variance", "INPUT", "NodeSocketFloat", 0.25, 0.0, 1.0)
    sock(ng, "Wobble", "INPUT", "NodeSocketFloat", 0.06, 0.0, 0.5)
    sock(ng, "Sink", "INPUT", "NodeSocketFloat", 0.25, 0.0, 1.0)
    sock(ng, "Fall Every", "INPUT", "NodeSocketInt", 4, 2, 32)
    sock(ng, "Ruined", "INPUT", "NodeSocketBool", True)
    sock(ng, "Lintels", "INPUT", "NodeSocketBool", True)
    sock(ng, "Rubble Density", "INPUT", "NodeSocketFloat", 1.5, 0.0, 30.0)
    sock(ng, "Grass Density", "INPUT", "NodeSocketFloat", 8.0, 0.0, 100.0)
    sock(ng, "Grass Size", "INPUT", "NodeSocketFloat", 0.25, 0.05, 1.0)
    sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    sock(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")

    gin = g.n("NodeGroupInput", "Params", x=-1900)
    gout = g.n("NodeGroupOutput", "Out", x=2200)

    # ---- ring geometry: angle(i) = i * TAU / Stones -------------------
    idx = g.n("GeometryNodeInputIndex", "Idx", x=-1600, y=300)
    step = g.math("DIVIDE", label="tau/N", x=-1600, y=180, const1=TAU)
    g.l(gin, "Stones", step, 1)
    angle = g.math("MULTIPLY", a=(idx, "Index"), label="angle", x=-1440, y=240)
    g.l(step, "Value", angle, 1)

    cosr = g.math("COSINE", a=(angle, "Value"), x=-1280, y=300)
    sinr = g.math("SINE", a=(angle, "Value"), x=-1280, y=180)
    px = g.math("MULTIPLY", a=(cosr, "Value"), x=-1120, y=300)
    g.l(gin, "Radius", px, 1)
    py = g.math("MULTIPLY", a=(sinr, "Value"), x=-1120, y=180)
    g.l(gin, "Radius", py, 1)
    ringpos = g.n("ShaderNodeCombineXYZ", "RingPos", x=-960, y=240)
    g.l(px, "Value", ringpos, "X")
    g.l(py, "Value", ringpos, "Y")

    ring = g.n("GeometryNodePoints", "Ring", x=-800, y=240)
    g.l(gin, "Stones", ring, "Count")
    g.l(ringpos, "Vector", ring, "Position")

    # facing yaw: tangent to circle = angle + 90deg
    yaw = g.math("ADD", a=(angle, "Value"), label="yaw", x=-1120, y=60, const2=1.5708)

    # ---- ruin pattern: every Nth stone falls (deterministic) ----------
    fmod = g.math("FLOORED_MODULO", a=(idx, "Index"), x=-800, y=40)
    g.l(gin, "Fall Every", fmod, 1)
    isfall = g.n("FunctionNodeCompare", "falls?", {"operation": "EQUAL", "data_type": "FLOAT"},
                 {"B": 0.0, "Epsilon": 0.1}, x=-640, y=40)
    g.l(fmod, "Value", isfall, "A")
    ruined = g.n("FunctionNodeBooleanMath", "AND ruined", {"operation": "AND"}, x=-480, y=40)
    g.l(isfall, "Result", ruined, 0)
    g.l(gin, "Ruined", ruined, 1)

    sep = g.n("GeometryNodeSeparateGeometry", "Fallen/Standing", {"domain": "POINT"}, x=-480, y=240)
    g.l(ring, "Points", sep, "Geometry")
    g.l(ruined, "Boolean", sep, "Selection")

    # ---- monolith mesh: bottom-origin cube ----------------------------
    mono = g.n("GeometryNodeMeshCube", "Monolith", x=-480, y=-260)
    g.l(gin, "Stone Size", mono, "Size")
    msz = g.n("ShaderNodeSeparateXYZ", "Sz", x=-640, y=-380)
    g.l(gin, "Stone Size", msz, "Vector")
    mhalf = g.math("MULTIPLY", a=(msz, "Z"), x=-480, y=-420, const2=0.5)
    mshift = g.n("ShaderNodeCombineXYZ", "MShift", x=-320, y=-420)
    g.l(mhalf, "Value", mshift, "Z")
    monob = g.n("GeometryNodeTransform", "MonolithB", x=-160, y=-260)
    g.l(mono, "Mesh", monob, "Geometry")
    g.l(mshift, "Vector", monob, "Translation")

    # per-point deterministic facing rotation (plank-tilt pattern)
    yawv = g.n("ShaderNodeCombineXYZ", "YawE", x=-960, y=-80)
    g.l(yaw, "Value", yawv, "Z")
    yawrot = g.n("FunctionNodeEulerToRotation", "YawRot", x=-800, y=-80)
    g.l(yawv, "Vector", yawrot, "Euler")

    def stone_chain(points_out, tag, y0, fallen):
        inst = g.n("GeometryNodeInstanceOnPoints", tag, x=0, y=y0)
        g.l(sep, points_out, inst, "Points")
        g.l(monob, "Geometry", inst, "Instance")
        face = g.n("GeometryNodeRotateInstances", tag + "Face", x=180, y=y0)
        g.l(inst, "Instances", face, "Instances")
        g.l(yawrot, "Rotation", face, "Rotation")
        cur = face
        if fallen:
            # topple 100deg outward (const) — reads as a collapsed slab
            tip = g.n("GeometryNodeRotateInstances", tag + "Tip", x=360, y=y0,
                      inputs={"Rotation": (1.745, 0.0, 0.0)})
            g.l(cur, "Instances", tip, "Instances")
            cur = tip
        # random wobble / extra scatter for fallen
        wmax = g.math("MULTIPLY", label=tag + "wob", x=180, y=y0 - 140, const2=3.0 if fallen else 1.0)
        g.l(gin, "Wobble", wmax, 0)
        wneg = g.math("MULTIPLY", a=(wmax, "Value"), x=340, y=y0 - 140, const2=-1.0)
        wmaxv = g.n("ShaderNodeCombineXYZ", tag + "WMax", x=500, y=y0 - 110)
        wminv = g.n("ShaderNodeCombineXYZ", tag + "WMin", x=500, y=y0 - 190)
        for c in ("X", "Y", "Z"):
            g.l(wmax, "Value", wmaxv, c)
            g.l(wneg, "Value", wminv, c)
        wrand = g.n("FunctionNodeRandomValue", tag + "WRand", {"data_type": "FLOAT_VECTOR"}, x=660, y=y0 - 140)
        g.l(wminv, "Vector", wrand, "Min")
        g.l(wmaxv, "Vector", wrand, "Max")
        g.l(gin, "Seed", wrand, "Seed")
        werot = g.n("FunctionNodeEulerToRotation", tag + "WRot", x=820, y=y0 - 140)
        g.l(wrand, "Value", werot, "Euler")
        wob = g.n("GeometryNodeRotateInstances", tag + "Wobble", x=560, y=y0)
        g.l(cur, "Instances", wob, "Instances")
        g.l(werot, "Rotation", wob, "Rotation")
        # sink into the ground: random -Sink..0 (fallen sink less)
        sneg = g.math("MULTIPLY", label=tag + "sink", x=560, y=y0 - 320,
                      const2=-0.4 if fallen else -1.0)
        g.l(gin, "Sink", sneg, 0)
        sminv = g.n("ShaderNodeCombineXYZ", tag + "SMin", x=720, y=y0 - 320)
        g.l(sneg, "Value", sminv, "Z")
        srand = g.n("FunctionNodeRandomValue", tag + "SRand", {"data_type": "FLOAT_VECTOR"},
                    {"Max": (0.0, 0.0, 0.0)}, x=880, y=y0 - 320)
        g.l(sminv, "Vector", srand, "Min")
        g.l(gin, "Seed", srand, "Seed")
        snk = g.n("GeometryNodeTranslateInstances", tag + "Sink", x=740, y=y0)
        g.l(wob, "Instances", snk, "Instances")
        g.l(srand, "Value", snk, "Translation")
        # size variance: uniform random 1-v .. 1+v
        vmin = g.math("SUBTRACT", label=tag + "vmin", x=740, y=y0 - 480, const1=1.0)
        g.l(gin, "Size Variance", vmin, 1)
        vmax = g.math("ADD", label=tag + "vmax", x=740, y=y0 - 560, const1=1.0)
        g.l(gin, "Size Variance", vmax, 1)
        vrand = g.n("FunctionNodeRandomValue", tag + "VRand", {"data_type": "FLOAT"}, x=900, y=y0 - 520)
        g.l(vmin, "Value", vrand, "Min")
        g.l(vmax, "Value", vrand, "Max")
        g.l(gin, "Seed", vrand, "Seed")
        vv = g.n("ShaderNodeCombineXYZ", tag + "VV", x=1060, y=y0 - 520)
        for c in ("X", "Y", "Z"):
            g.l(vrand, "Value", vv, c)
        scl = g.n("GeometryNodeScaleInstances", tag + "Var", x=920, y=y0)
        g.l(snk, "Instances", scl, "Instances")
        g.l(vv, "Vector", scl, "Scale")
        return scl

    standing = stone_chain("Inverted", "Stand", 400, fallen=False)
    fallenst = stone_chain("Selection", "Fall", -700, fallen=True)

    # ---- lintels: slabs bridging adjacent standing pairs --------------
    half = g.math("MULTIPLY", a=(step, "Value"), label="halfstep", x=-1440, y=-560, const2=0.5)
    langle = g.math("ADD", a=(angle, "Value"), x=-1280, y=-560)
    g.l(half, "Value", langle, 1)
    lcos = g.math("COSINE", a=(langle, "Value"), x=-1120, y=-520)
    lsin = g.math("SINE", a=(langle, "Value"), x=-1120, y=-600)
    lx = g.math("MULTIPLY", a=(lcos, "Value"), x=-960, y=-520)
    g.l(gin, "Radius", lx, 1)
    ly = g.math("MULTIPLY", a=(lsin, "Value"), x=-960, y=-600)
    g.l(gin, "Radius", ly, 1)
    lz = g.math("MULTIPLY", a=(msz, "Z"), x=-960, y=-680, const2=0.98)
    lpos = g.n("ShaderNodeCombineXYZ", "LintelPos", x=-800, y=-560)
    g.l(lx, "Value", lpos, "X")
    g.l(ly, "Value", lpos, "Y")
    g.l(lz, "Value", lpos, "Z")
    lring = g.n("GeometryNodePoints", "LintelRing", x=-640, y=-560)
    g.l(gin, "Stones", lring, "Count")
    g.l(lpos, "Vector", lring, "Position")

    # keep a lintel only if neither pillar i nor i+1 has fallen
    i1 = g.math("ADD", a=(idx, "Index"), x=-640, y=-760, const2=1.0)
    fmod2 = g.math("FLOORED_MODULO", a=(i1, "Value"), x=-480, y=-760)
    g.l(gin, "Fall Every", fmod2, 1)
    n2 = g.n("FunctionNodeCompare", "next falls?", {"operation": "EQUAL", "data_type": "FLOAT"},
             {"B": 0.0, "Epsilon": 0.1}, x=-320, y=-760)
    g.l(fmod2, "Value", n2, "A")
    either = g.n("FunctionNodeBooleanMath", "either", {"operation": "OR"}, x=-160, y=-780)
    g.l(isfall, "Result", either, 0)
    g.l(n2, "Result", either, 1)
    gone = g.n("FunctionNodeBooleanMath", "AND ruined2", {"operation": "AND"}, x=0, y=-780)
    g.l(either, "Boolean", gone, 0)
    g.l(gin, "Ruined", gone, 1)
    lkeep = g.n("FunctionNodeBooleanMath", "keep", {"operation": "NOT"}, x=160, y=-780)
    g.l(gone, "Boolean", lkeep, 0)
    lsep = g.n("GeometryNodeSeparateGeometry", "LintelKeep", {"domain": "POINT"}, x=-320, y=-560)
    g.l(lring, "Points", lsep, "Geometry")
    g.l(lkeep, "Boolean", lsep, "Selection")

    # lintel slab: chord length x stone depth x slab height, tangent-aligned
    chord = g.math("MULTIPLY", a=(step, "Value"), label="chord~", x=-320, y=-960)
    g.l(gin, "Radius", chord, 1)
    lclen = g.math("MULTIPLY", a=(chord, "Value"), x=-160, y=-960, const2=1.15)
    lsz = g.n("ShaderNodeCombineXYZ", "LintelSize", x=0, y=-960)
    g.l(lclen, "Value", lsz, "Y")
    g.l(msz, "X", lsz, "X")
    lh = g.math("MULTIPLY", a=(msz, "Z"), x=-160, y=-1040, const2=0.22)
    g.l(lh, "Value", lsz, "Z")
    lcube = g.n("GeometryNodeMeshCube", "LintelCube", x=160, y=-960)
    g.l(lsz, "Vector", lcube, "Size")
    lhalf = g.math("MULTIPLY", a=(lh, "Value"), x=160, y=-1100, const2=0.5)
    lshift = g.n("ShaderNodeCombineXYZ", "LShift", x=320, y=-1100)
    g.l(lhalf, "Value", lshift, "Z")
    lcubeb = g.n("GeometryNodeTransform", "LintelB", x=320, y=-960)
    g.l(lcube, "Mesh", lcubeb, "Geometry")
    g.l(lshift, "Vector", lcubeb, "Translation")

    lyawv = g.n("ShaderNodeCombineXYZ", "LYawE", x=-160, y=-640)
    lyaw = g.math("ADD", a=(langle, "Value"), x=-320, y=-660, const2=1.5708)
    g.l(lyaw, "Value", lyawv, "Z")
    lyawrot = g.n("FunctionNodeEulerToRotation", "LYawRot", x=0, y=-640)
    g.l(lyawv, "Vector", lyawrot, "Euler")

    linst = g.n("GeometryNodeInstanceOnPoints", "Lintels", x=0, y=-560)
    g.l(lsep, "Inverted", linst, "Points")
    g.l(lcubeb, "Geometry", linst, "Instance")
    lface = g.n("GeometryNodeRotateInstances", "LFace", x=180, y=-560)
    g.l(linst, "Instances", lface, "Instances")
    g.l(lyawrot, "Rotation", lface, "Rotation")

    lswitch = g.n("GeometryNodeSwitch", "Lintels?", {"input_type": "GEOMETRY"}, x=360, y=-560)
    g.l(gin, "Lintels", lswitch, "Switch")
    g.l(lface, "Instances", lswitch, "True")

    # ---- rubble + grass scatter on the input ground -------------------
    nrm = g.n("GeometryNodeInputNormal", "N", x=-1900, y=-1300)
    nz = g.n("ShaderNodeSeparateXYZ", "Nz", x=-1740, y=-1300)
    g.l(nrm, "Normal", nz, "Vector")
    upok = g.n("FunctionNodeCompare", "N.z>0.8", {"operation": "GREATER_THAN", "data_type": "FLOAT"},
               {"B": 0.8}, x=-1580, y=-1300)
    g.l(nz, "Z", upok, "A")

    def scatter(tag, density_sock, seed_off, cube_size, y0, rotmax, smin, smax):
        dist = g.n("GeometryNodeDistributePointsOnFaces", tag, x=-1420, y=y0)
        g.l(gin, "Geometry", dist, "Mesh")
        g.l(upok, "Result", dist, "Selection")
        g.l(gin, density_sock, dist, "Density")
        soff = g.math("ADD", label=tag + "seed", x=-1580, y=y0 - 140, const2=float(seed_off))
        g.l(gin, "Seed", soff, 0)
        g.l(soff, "Value", dist, "Seed")
        cube = g.n("GeometryNodeMeshCube", tag + "Cube", inputs={"Size": cube_size}, x=-1420, y=y0 - 200)
        inst = g.n("GeometryNodeInstanceOnPoints", tag + "Inst", x=-1240, y=y0)
        g.l(dist, "Points", inst, "Points")
        g.l(cube, "Mesh", inst, "Instance")
        rot = g.n("FunctionNodeRandomValue", tag + "Rot", {"data_type": "FLOAT_VECTOR"},
                  {"Min": (-rotmax, -rotmax, 0.0), "Max": (rotmax, rotmax, 6.2832)}, x=-1240, y=y0 - 180)
        g.l(gin, "Seed", rot, "Seed")
        erot = g.n("FunctionNodeEulerToRotation", tag + "ERot", x=-1080, y=y0 - 180)
        g.l(rot, "Value", erot, "Euler")
        spin = g.n("GeometryNodeRotateInstances", tag + "Spin", x=-1060, y=y0)
        g.l(inst, "Instances", spin, "Instances")
        g.l(erot, "Rotation", spin, "Rotation")
        sr = g.n("FunctionNodeRandomValue", tag + "SR", {"data_type": "FLOAT"},
                 {"Min": smin, "Max": smax}, x=-1060, y=y0 - 340)
        g.l(gin, "Seed", sr, "Seed")
        sv = g.n("ShaderNodeCombineXYZ", tag + "SV", x=-900, y=y0 - 340)
        for c in ("X", "Y", "Z"):
            g.l(sr, "Value", sv, c)
        size = g.n("GeometryNodeScaleInstances", tag + "Size", x=-880, y=y0)
        g.l(spin, "Instances", size, "Instances")
        g.l(sv, "Vector", size, "Scale")
        return size

    rubble = scatter("Rubble", "Rubble Density", 13, (0.28, 0.22, 0.15), -1500, 0.4, 0.3, 1.0)

    gsize = g.n("ShaderNodeCombineXYZ", "BladeSize", inputs={"X": 0.04, "Y": 0.04}, x=-1740, y=-2050)
    g.l(gin, "Grass Size", gsize, "Z")
    gdist = g.n("GeometryNodeDistributePointsOnFaces", "GrassPts", x=-1420, y=-1900)
    g.l(gin, "Geometry", gdist, "Mesh")
    g.l(upok, "Result", gdist, "Selection")
    g.l(gin, "Grass Density", gdist, "Density")
    gseed = g.math("ADD", label="gseed", x=-1580, y=-2040, const2=29.0)
    g.l(gin, "Seed", gseed, 0)
    g.l(gseed, "Value", gdist, "Seed")
    gcube = g.n("GeometryNodeMeshCube", "Blade", x=-1580, y=-2140)
    g.l(gsize, "Vector", gcube, "Size")
    ghalf = g.math("MULTIPLY", label="gz/2", x=-1740, y=-2200, const2=0.5)
    g.l(gin, "Grass Size", ghalf, 0)
    gshift = g.n("ShaderNodeCombineXYZ", "BladeShift", x=-1580, y=-2260)
    g.l(ghalf, "Value", gshift, "Z")
    gmesh = g.n("GeometryNodeTransform", "BladeB", x=-1420, y=-2140)
    g.l(gcube, "Mesh", gmesh, "Geometry")
    g.l(gshift, "Vector", gmesh, "Translation")
    galign = g.n("FunctionNodeAlignRotationToVector", "AlignN", {"axis": "Z"}, x=-1420, y=-2000)
    g.l(gdist, "Normal", galign, "Vector")
    ginst = g.n("GeometryNodeInstanceOnPoints", "Grass", x=-1240, y=-1900)
    g.l(gdist, "Points", ginst, "Points")
    g.l(gmesh, "Geometry", ginst, "Instance")
    g.l(galign, "Rotation", ginst, "Rotation")
    gyaw = g.n("FunctionNodeRandomValue", "GYaw", {"data_type": "FLOAT"},
               {"Min": 0.0, "Max": 6.2832}, x=-1240, y=-2080)
    g.l(gin, "Seed", gyaw, "Seed")
    gyv = g.n("ShaderNodeCombineXYZ", "GYawE", x=-1080, y=-2080)
    g.l(gyaw, "Value", gyv, "Z")
    gyr = g.n("FunctionNodeEulerToRotation", "GYawRot", x=-920, y=-2080)
    g.l(gyv, "Vector", gyr, "Euler")
    gspin = g.n("GeometryNodeRotateInstances", "GrassYaw", x=-1060, y=-1900)
    g.l(ginst, "Instances", gspin, "Instances")
    g.l(gyr, "Rotation", gspin, "Rotation")

    vegjoin = g.n("GeometryNodeJoinGeometry", "Veg", x=-700, y=-1700)
    g.l(rubble, "Instances", vegjoin, "Geometry")
    g.l(gspin, "Instances", vegjoin, "Geometry")

    # ---- output -------------------------------------------------------
    join = g.n("GeometryNodeJoinGeometry", "Circle+World", x=1400, y=0)
    for src, out in ((standing, "Instances"), (fallenst, "Instances"),
                     (lswitch, "Output"), (vegjoin, "Geometry"), (gin, "Geometry")):
        try:
            g.ng.links.new(src.outputs[out], join.inputs["Geometry"])
        except Exception as e:
            P("final join %s: %s" % (out, e))
    g.l(join, "Geometry", gout, "Geometry")
    return ng


def validate(ng):
    used = sorted({n.bl_idname for n in ng.nodes})
    bad = [i for i in used if i not in V1_WHITELIST]
    print("NODES: %d (%d types)" % (len(ng.nodes), len(used)))
    print("V1 VALIDATION:", "PASS" if not bad else "FAIL " + str(bad))
    return bad


def attach(ng):
    obj = bpy.data.objects.get("V1StoneCircle_Demo")
    if obj is None:
        bpy.ops.mesh.primitive_plane_add(size=14, location=(30, 0, 0))
        obj = bpy.context.active_object
        obj.name = "V1StoneCircle_Demo"
    for m in list(obj.modifiers):
        obj.modifiers.remove(m)
    mod = obj.modifiers.new("StoneCircleV1", "NODES")
    mod.node_group = ng
    return obj


ng = build()
bad = validate(ng)
obj = attach(ng)
bpy.context.view_layer.update()
print("BUILD DONE: group=%s nodes=%d problems=%d object=%s"
      % (ng.name, len(ng.nodes), len(PROBLEMS), obj.name))
for p in PROBLEMS:
    print("  P:", p)
