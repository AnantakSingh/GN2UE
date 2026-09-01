"""RopeBridge_V1 — parametric rope bridge + terrain scatter, V1-core nodes ONLY.

Runs inside Blender (5.x) via the blender-mcp addon socket:
    exec(compile(open(r'c:/Projects/GNtoUEresearch/build_v1_bridge.py').read(),
                 'build_v1_bridge.py', 'exec'))

Every node comes from atlas/v1_core_nodes.md (the 53-node V1 core set).
V1_WHITELIST below is the enforcement list; validate() prints any violation.
"""
import bpy
from mathutils import Vector

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

GROUP_NAME = "RopeBridge_V1"
PROBLEMS = []


def P(msg):
    PROBLEMS.append(msg)
    print("PROBLEM:", msg)


# ---------------------------------------------------------------- helpers
def fresh_group():
    old = bpy.data.node_groups.get(GROUP_NAME)
    if old:
        bpy.data.node_groups.remove(old)
    ng = bpy.data.node_groups.new(GROUP_NAME, "GeometryNodeTree")
    return ng


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
        self.x = 0

    def n(self, idname, label="", props=None, inputs=None, x=None, y=0):
        nd = self.ng.nodes.new(idname)
        if label:
            nd.label = label
        nd.location = (x if x is not None else self.x, y)
        if x is None:
            self.x += 40
        for k, v in (props or {}).items():
            try:
                setattr(nd, k, v)
            except Exception:
                # menu moved from property to input socket in some 5.x nodes
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
            o = a.outputs[out] if not isinstance(out, str) or out in a.outputs else a.outputs[out]
            i = b.inputs[inp]
            self.ng.links.new(o, i)
        except Exception as e:
            P("link %s.%r -> %s.%r: %s" % (a.bl_idname, out, b.bl_idname, inp, e))


# ---------------------------------------------------------------- build
def build():
    ng = fresh_group()
    g = G(ng)

    # ---- interface
    sock(ng, "Geometry", "INPUT", "NodeSocketGeometry")
    sock(ng, "Start", "INPUT", "NodeSocketVector", (-5.0, 0.0, 1.4))
    sock(ng, "End", "INPUT", "NodeSocketVector", (5.0, 1.5, 1.7))
    sock(ng, "Sag", "INPUT", "NodeSocketFloat", 0.9, 0.0, 5.0)
    sock(ng, "Plank Spacing", "INPUT", "NodeSocketFloat", 0.45, 0.1, 2.0)
    # (width across, thickness, depth along walk) — Curve to Points aligns local +Z to the tangent
    sock(ng, "Plank Size", "INPUT", "NodeSocketVector", (1.1, 0.055, 0.28))
    sock(ng, "Plank Tilt", "INPUT", "NodeSocketFloat", 0.25, 0.0, 1.0)
    sock(ng, "Bridge Width", "INPUT", "NodeSocketFloat", 1.15, 0.3, 4.0)
    sock(ng, "Rope Height", "INPUT", "NodeSocketFloat", 0.85, 0.1, 3.0)
    sock(ng, "Rope Thickness", "INPUT", "NodeSocketFloat", 0.045, 0.01, 0.3)
    sock(ng, "Post Size", "INPUT", "NodeSocketVector", (0.16, 0.16, 1.3))
    sock(ng, "Lanterns", "INPUT", "NodeSocketBool", True)
    sock(ng, "Show Vegetation", "INPUT", "NodeSocketBool", True)
    sock(ng, "Grass Density", "INPUT", "NodeSocketFloat", 8.0, 0.0, 200.0)
    sock(ng, "Rock Density", "INPUT", "NodeSocketFloat", 1.2, 0.0, 50.0)
    sock(ng, "Grass Size", "INPUT", "NodeSocketFloat", 0.28, 0.01, 2.0)
    sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    sock(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")

    gin = g.n("NodeGroupInput", "Params", x=-1500, y=0)
    gout = g.n("NodeGroupOutput", "Out", x=2600, y=0)

    # ---- A. sagged bridge curve --------------------------------------
    line = g.n("GeometryNodeCurvePrimitiveLine", "BridgeLine", x=-1200, y=600)
    g.l(gin, "Start", line, "Start")
    g.l(gin, "End", line, "End")

    res32 = g.n("GeometryNodeResampleCurve", "Smooth32", inputs={"Count": 32}, x=-1000, y=600)
    g.l(line, "Curve", res32, "Curve")

    t = g.n("GeometryNodeSplineParameter", "t", x=-1000, y=380)
    tpi = g.n("ShaderNodeMath", "t*pi", {"operation": "MULTIPLY"}, {1: 3.14159265}, x=-840, y=420)
    g.l(t, "Factor", tpi, 0)
    sint = g.n("ShaderNodeMath", "sin", {"operation": "SINE"}, x=-700, y=420)
    g.l(tpi, "Value", sint, 0)
    sagclamp = g.n("ShaderNodeClamp", "SagClamp", inputs={"Min": 0.0, "Max": 5.0}, x=-840, y=250)
    g.l(gin, "Sag", sagclamp, "Value")
    sagmul = g.n("ShaderNodeMath", "-sag*sin", {"operation": "MULTIPLY"}, x=-560, y=380)
    g.l(sint, "Value", sagmul, 0)
    neg = g.n("ShaderNodeMath", "negate", {"operation": "MULTIPLY"}, {1: -1.0}, x=-700, y=250)
    g.l(sagclamp, "Result", neg, 0)
    g.l(neg, "Value", sagmul, 1)
    sagvec = g.n("ShaderNodeCombineXYZ", "SagVec", x=-420, y=380)
    g.l(sagmul, "Value", sagvec, "Z")

    sagpos = g.n("GeometryNodeSetPosition", "ApplySag", x=-280, y=600)
    g.l(res32, "Curve", sagpos, "Geometry")
    g.l(sagvec, "Vector", sagpos, "Offset")

    smooth = g.n("GeometryNodeCurveSplineType", "Catmull", {"spline_type": "CATMULL_ROM"}, x=-120, y=600)
    g.l(sagpos, "Geometry", smooth, "Curve")

    # plank count = clamp(length / spacing)
    clen = g.n("GeometryNodeCurveLength", "Len", x=-120, y=380)
    g.l(smooth, "Curve", clen, "Curve")
    pcount = g.n("ShaderNodeMath", "Len/Spacing", {"operation": "DIVIDE"}, x=40, y=380)
    g.l(clen, "Length", pcount, 0)
    g.l(gin, "Plank Spacing", pcount, 1)

    resplank = g.n("GeometryNodeResampleCurve", "PlankRes", x=200, y=600)
    g.l(smooth, "Curve", resplank, "Curve")
    g.l(pcount, "Value", resplank, "Count")

    # capture spline factor so points derived from this curve can use it
    cap = g.n("GeometryNodeCaptureAttribute", "Capture t", x=380, y=600)
    tf = g.n("GeometryNodeSplineParameter", "t2", x=380, y=420)
    try:
        item = cap.capture_items.new("FLOAT", "t")
    except Exception as e:
        P("capture_items: %s" % e)
    g.l(resplank, "Curve", cap, "Geometry")
    try:
        g.ng.links.new(tf.outputs["Factor"], cap.inputs[1])
    except Exception as e:
        P("capture link: %s" % e)

    plankpts = g.n("GeometryNodeCurveToPoints", "PlankPts", {"mode": "EVALUATED"}, x=560, y=600)
    g.l(cap, "Geometry", plankpts, "Curve")

    # ---- B. planks ----------------------------------------------------
    plankcube = g.n("GeometryNodeMeshCube", "PlankCube", x=560, y=300)
    g.l(gin, "Plank Size", plankcube, "Size")

    planks = g.n("GeometryNodeInstanceOnPoints", "Planks", x=760, y=600)
    g.l(plankpts, "Points", planks, "Points")
    g.l(plankcube, "Mesh", planks, "Instance")
    g.l(plankpts, "Rotation", planks, "Rotation")

    # tilt planks by captured t: roll = (t-0.5)*2*tilt
    tremap = g.n("ShaderNodeMapRange", "t->-1..1", inputs={1: 0.0, 2: 1.0, 3: -1.0, 4: 1.0}, x=760, y=300)
    g.l(cap, "t", tremap, "Value")
    tiltm = g.n("ShaderNodeMath", "tilt", {"operation": "MULTIPLY"}, x=920, y=300)
    g.l(tremap, "Result", tiltm, 0)
    g.l(gin, "Plank Tilt", tiltm, 1)
    tilteuler = g.n("ShaderNodeCombineXYZ", "TiltEuler", x=1060, y=300)
    g.l(tiltm, "Value", tilteuler, "Z")  # roll around the tangent (local Z)
    tiltrot = g.n("FunctionNodeEulerToRotation", "TiltRot", x=1200, y=300)
    g.l(tilteuler, "Vector", tiltrot, "Euler")
    planks2 = g.n("GeometryNodeRotateInstances", "PlankTilt", x=1000, y=600)
    g.l(planks, "Instances", planks2, "Instances")
    g.l(tiltrot, "Rotation", planks2, "Rotation")

    # small random plank offset (weathering)
    rvec = g.n("FunctionNodeRandomValue", "PlankJitter", {"data_type": "FLOAT_VECTOR"},
               {"Min": (-0.015, -0.03, -0.012), "Max": (0.015, 0.03, 0.012)}, x=1000, y=380)
    g.l(gin, "Seed", rvec, "Seed")
    planks3 = g.n("GeometryNodeTranslateInstances", "PlankNudge", x=1220, y=600)
    g.l(planks2, "Instances", planks3, "Instances")
    g.l(rvec, "Value", planks3, "Translation")

    # ---- C. hand ropes (both sides) via duplicate + points-to-curves --
    dup = g.n("GeometryNodeDuplicateElements", "TwoSides", {"domain": "POINT"},
              {"Amount": 2}, x=760, y=60)
    g.l(plankpts, "Points", dup, "Geometry")

    side = g.n("ShaderNodeMath", "side=-1/+1", {"operation": "MULTIPLY_ADD"}, {1: 2.0, 2: -1.0}, x=940, y=-60)
    g.l(dup, "Duplicate Index", side, 0)

    tan = g.n("GeometryNodeInputTangent", "Tangent", x=760, y=-160)
    up = g.n("FunctionNodeInputVector", "Up", {"vector": (0.0, 0.0, 1.0)}, x=760, y=-260)
    cross = g.n("ShaderNodeVectorMath", "Side", {"operation": "CROSS_PRODUCT"}, x=940, y=-200)
    g.l(tan, "Tangent", cross, 0)
    g.l(up, "Vector", cross, 1)
    norm = g.n("ShaderNodeVectorMath", "Norm", {"operation": "NORMALIZE"}, x=1100, y=-200)
    g.l(cross, "Vector", norm, 0)

    halfw = g.n("ShaderNodeMath", "w/2", {"operation": "MULTIPLY"}, {1: 0.5}, x=940, y=-320)
    g.l(gin, "Bridge Width", halfw, 0)
    sidew = g.n("ShaderNodeMath", "side*w/2", {"operation": "MULTIPLY"}, x=1100, y=-320)
    g.l(side, "Value", sidew, 0)
    g.l(halfw, "Value", sidew, 1)
    sidevec = g.n("ShaderNodeVectorMath", "SideVec", {"operation": "SCALE"}, x=1260, y=-240)
    g.l(norm, "Vector", sidevec, 0)
    g.l(sidew, "Value", sidevec, "Scale")
    hvec = g.n("ShaderNodeCombineXYZ", "RopeH", x=1100, y=-420)
    g.l(gin, "Rope Height", hvec, "Z")
    offs = g.n("ShaderNodeVectorMath", "Side+H", {"operation": "ADD"}, x=1420, y=-280)
    g.l(sidevec, "Vector", offs, 0)
    g.l(hvec, "Vector", offs, 1)

    ropepts = g.n("GeometryNodeSetPosition", "RopeAnchor", x=1580, y=-60)
    g.l(dup, "Geometry", ropepts, "Geometry")
    g.l(offs, "Vector", ropepts, "Offset")

    ropecrv = g.n("GeometryNodePointsToCurves", "RopeCurves", x=1740, y=-60)
    g.l(ropepts, "Geometry", ropecrv, "Points")
    g.l(dup, "Duplicate Index", ropecrv, "Curve Group ID")

    ropesmooth = g.n("GeometryNodeCurveSplineType", "RopeCatmull", {"spline_type": "CATMULL_ROM"}, x=1900, y=-60)
    g.l(ropecrv, "Curves", ropesmooth, "Curve")

    segs = g.n("ShaderNodeMath", "count*3", {"operation": "MULTIPLY"}, {1: 3.0}, x=1740, y=-220)
    g.l(pcount, "Value", segs, 0)
    ropedense = g.n("GeometryNodeCurveToPoints", "RopeSegs", {"mode": "COUNT"}, x=2060, y=-60)
    g.l(ropesmooth, "Curve", ropedense, "Curve")
    g.l(segs, "Value", ropedense, "Count")

    seglen = g.n("ShaderNodeMath", "seglen", {"operation": "MULTIPLY"}, {1: 0.42}, x=1900, y=-320)
    g.l(gin, "Plank Spacing", seglen, 0)
    ropesize = g.n("ShaderNodeCombineXYZ", "RopeSegSize", x=2060, y=-320)
    g.l(gin, "Rope Thickness", ropesize, "X")
    g.l(gin, "Rope Thickness", ropesize, "Y")
    g.l(seglen, "Value", ropesize, "Z")  # segment length along the tangent (local Z)
    ropecube = g.n("GeometryNodeMeshCube", "RopeCube", x=2200, y=-320)
    g.l(ropesize, "Vector", ropecube, "Size")

    rope = g.n("GeometryNodeInstanceOnPoints", "Rope", x=2260, y=-60)
    g.l(ropedense, "Points", rope, "Points")
    g.l(ropecube, "Mesh", rope, "Instance")
    g.l(ropedense, "Rotation", rope, "Rotation")

    # ---- D. posts at both ends, both sides ---------------------------
    s0 = g.n("GeometryNodeSampleCurve", "Sample t=0", inputs={"Factor": 0.0}, x=-120, y=60)
    s1 = g.n("GeometryNodeSampleCurve", "Sample t=1", inputs={"Factor": 1.0}, x=-120, y=-120)
    g.l(smooth, "Curve", s0, "Curves")
    g.l(smooth, "Curve", s1, "Curves")

    idx = g.n("GeometryNodeInputIndex", "Idx", x=40, y=-40)
    mixpos = g.n("ShaderNodeMix", "EndMix", {"data_type": "VECTOR"}, x=220, y=-40)
    g.l(idx, "Index", mixpos, "Factor")
    try:
        g.ng.links.new(s0.outputs["Position"], mixpos.inputs[4])  # A (vector)
        g.ng.links.new(s1.outputs["Position"], mixpos.inputs[5])  # B (vector)
    except Exception as e:
        P("mix vec sockets: %s" % e)

    postpts = g.n("GeometryNodePoints", "PostPts", inputs={"Count": 2}, x=400, y=-40)
    try:
        g.ng.links.new(mixpos.outputs[1], postpts.inputs["Position"])  # Result (vector)
    except Exception as e:
        P("points position: %s" % e)

    dup2 = g.n("GeometryNodeDuplicateElements", "PostSides", {"domain": "POINT"},
               {"Amount": 2}, x=580, y=-40)
    g.l(postpts, "Points", dup2, "Geometry")
    side2 = g.n("ShaderNodeMath", "pside", {"operation": "MULTIPLY_ADD"}, {1: 2.0, 2: -1.0}, x=740, y=-160)
    g.l(dup2, "Duplicate Index", side2, 0)
    pw = g.n("ShaderNodeMath", "pw", {"operation": "MULTIPLY"}, x=900, y=-160)
    g.l(side2, "Value", pw, 0)
    g.l(halfw, "Value", pw, 1)
    pvec = g.n("ShaderNodeCombineXYZ", "PostOff", x=1060, y=-160)
    g.l(pw, "Value", pvec, "Y")
    postmove = g.n("GeometryNodeSetPosition", "PostPlace", x=1220, y=-40)
    g.l(dup2, "Geometry", postmove, "Geometry")
    g.l(pvec, "Vector", postmove, "Offset")

    postcube = g.n("GeometryNodeMeshCube", "PostCube", x=1220, y=-500)
    g.l(gin, "Post Size", postcube, "Size")
    # shift cube so it stands on its base
    psz = g.n("ShaderNodeSeparateXYZ", "PostZ", x=1060, y=-560)
    g.l(gin, "Post Size", psz, "Vector")
    phalf = g.n("ShaderNodeMath", "z/2", {"operation": "MULTIPLY"}, {1: 0.5}, x=1220, y=-620)
    g.l(psz, "Z", phalf, 0)
    pshift = g.n("ShaderNodeCombineXYZ", "PostShift", x=1380, y=-620)
    g.l(phalf, "Value", pshift, "Z")
    postmesh = g.n("GeometryNodeTransform", "PostOrigin", x=1400, y=-500)
    g.l(postcube, "Mesh", postmesh, "Geometry")
    g.l(pshift, "Vector", postmesh, "Translation")

    posts = g.n("GeometryNodeInstanceOnPoints", "Posts", x=1580, y=-500)
    g.l(postmove, "Geometry", posts, "Points")
    g.l(postmesh, "Geometry", posts, "Instance")

    # ---- E. lanterns under every 3rd plank ---------------------------
    lpts = g.n("GeometryNodeInstancesToPoints", "PlankAnchors", x=1440, y=600)
    g.l(planks3, "Instances", lpts, "Instances")

    li = g.n("GeometryNodeInputIndex", "LIdx", x=1440, y=440)
    lmod = g.n("ShaderNodeMath", "mod3", {"operation": "FLOORED_MODULO"}, {1: 3.0}, x=1600, y=440)
    g.l(li, "Index", lmod, 0)
    liszero = g.n("FunctionNodeCompare", "==0", {"operation": "EQUAL", "data_type": "FLOAT"},
                  {"B": 0.0, "Epsilon": 0.1}, x=1760, y=440)
    g.l(lmod, "Value", liszero, "A")
    lon = g.n("FunctionNodeBooleanMath", "AND lanterns", {"operation": "AND"}, x=1920, y=440)
    g.l(liszero, "Result", lon, 0)
    g.l(gin, "Lanterns", lon, 1)

    lsep = g.n("GeometryNodeSeparateGeometry", "LanternPts", {"domain": "POINT"}, x=1620, y=600)
    g.l(lpts, "Points", lsep, "Geometry")
    g.l(lon, "Boolean", lsep, "Selection")

    ldrop = g.n("GeometryNodeSetPosition", "Drop", inputs={"Offset": (0.0, 0.0, -0.22)}, x=1800, y=600)
    g.l(lsep, "Selection", ldrop, "Geometry")

    lcube = g.n("GeometryNodeMeshCube", "LanternCube", inputs={"Size": (0.12, 0.12, 0.16)}, x=1800, y=760)
    lanterns = g.n("GeometryNodeInstanceOnPoints", "Lanterns", x=1980, y=600)
    g.l(ldrop, "Geometry", lanterns, "Points")
    g.l(lcube, "Mesh", lanterns, "Instance")

    # ---- F. vegetation scatter on input terrain ----------------------
    nrm = g.n("GeometryNodeInputNormal", "N", x=-1200, y=-700)
    nz = g.n("ShaderNodeSeparateXYZ", "Nz", x=-1040, y=-700)
    g.l(nrm, "Normal", nz, "Vector")
    upfacing = g.n("FunctionNodeCompare", "N.z>0.85", {"operation": "GREATER_THAN", "data_type": "FLOAT"},
                   {"B": 0.85}, x=-880, y=-700)
    g.l(nz, "Z", upfacing, "A")
    pos = g.n("GeometryNodeInputPosition", "P", x=-1200, y=-840)
    pz = g.n("ShaderNodeSeparateXYZ", "Pz", x=-1040, y=-840)
    g.l(pos, "Position", pz, "Vector")
    above = g.n("FunctionNodeCompare", "P.z>-0.2", {"operation": "GREATER_THAN", "data_type": "FLOAT"},
                {"B": -0.2}, x=-880, y=-840)
    g.l(pz, "Z", above, "A")
    landok = g.n("FunctionNodeBooleanMath", "AND", {"operation": "AND"}, x=-720, y=-760)
    g.l(upfacing, "Result", landok, 0)
    g.l(above, "Result", landok, 1)

    def scatter(label, density_sock, seed_off, y):
        dist = g.n("GeometryNodeDistributePointsOnFaces", label, x=-560, y=y)
        g.l(gin, "Geometry", dist, "Mesh")
        g.l(landok, "Boolean", dist, "Selection")
        g.l(gin, density_sock, dist, "Density")
        soff = g.n("ShaderNodeMath", "seed+%d" % seed_off, {"operation": "ADD"}, {1: float(seed_off)}, x=-720, y=y - 140)
        g.l(gin, "Seed", soff, 0)
        g.l(soff, "Value", dist, "Seed")
        return dist

    # grass: thin cubes aligned to surface normal, random yaw + size
    gdist = scatter("GrassPts", "Grass Density", 11, -700)
    gsize = g.n("ShaderNodeCombineXYZ", "BladeSize", inputs={"X": 0.045, "Y": 0.045}, x=-560, y=-880)
    g.l(gin, "Grass Size", gsize, "Z")
    gcube = g.n("GeometryNodeMeshCube", "Blade", x=-400, y=-880)
    g.l(gsize, "Vector", gcube, "Size")
    ghalf = g.n("ShaderNodeMath", "gz/2", {"operation": "MULTIPLY"}, {1: 0.5}, x=-560, y=-1020)
    g.l(gin, "Grass Size", ghalf, 0)
    gshift = g.n("ShaderNodeCombineXYZ", "BladeShift", x=-400, y=-1020)
    g.l(ghalf, "Value", gshift, "Z")
    gmesh = g.n("GeometryNodeTransform", "BladeOrigin", x=-240, y=-880)
    g.l(gcube, "Mesh", gmesh, "Geometry")
    g.l(gshift, "Vector", gmesh, "Translation")

    galign = g.n("FunctionNodeAlignRotationToVector", "AlignN", {"axis": "Z"}, x=-400, y=-700)
    g.l(gdist, "Normal", galign, "Vector")

    grass = g.n("GeometryNodeInstanceOnPoints", "Grass", x=-220, y=-700)
    g.l(gdist, "Points", grass, "Points")
    g.l(gmesh, "Geometry", grass, "Instance")
    g.l(galign, "Rotation", grass, "Rotation")

    gyawr = g.n("FunctionNodeRandomValue", "YawRand", {"data_type": "FLOAT"},
                {"Min": 0.0, "Max": 6.2832}, x=-220, y=-880)
    g.l(gin, "Seed", gyawr, "Seed")
    gyawv = g.n("ShaderNodeCombineXYZ", "YawE", x=-60, y=-880)
    g.l(gyawr, "Value", gyawv, "Z")
    gyawrot = g.n("FunctionNodeEulerToRotation", "YawRot", x=80, y=-880)
    g.l(gyawv, "Vector", gyawrot, "Euler")
    grass2 = g.n("GeometryNodeRotateInstances", "GrassYaw", x=-40, y=-700)
    g.l(grass, "Instances", grass2, "Instances")
    g.l(gyawrot, "Rotation", grass2, "Rotation")

    gscale_r = g.n("FunctionNodeRandomValue", "SizeRand", {"data_type": "FLOAT"},
                   {"Min": 0.0, "Max": 1.0}, x=-40, y=-1040)
    gid = g.n("GeometryNodeInputID", "ID", x=-220, y=-1040)
    g.l(gid, "ID", gscale_r, "ID")
    g.l(gin, "Seed", gscale_r, "Seed")
    gremap = g.n("ShaderNodeMapRange", "0.6..1.4", inputs={3: 0.6, 4: 1.4}, x=120, y=-1040)
    g.l(gscale_r, "Value", gremap, "Value")
    grass3 = g.n("GeometryNodeScaleInstances", "GrassScale", x=140, y=-700)
    g.l(grass2, "Instances", grass3, "Instances")
    gsv = g.n("ShaderNodeCombineXYZ", "SV", x=260, y=-880)
    for c in ("X", "Y", "Z"):
        g.l(gremap, "Result", gsv, c)
    g.l(gsv, "Vector", grass3, "Scale")

    # store a tint attribute for material variation (mix of two greens by random)
    tintmix = g.n("ShaderNodeMix", "TintMix", {"data_type": "FLOAT"}, {2: 0.25, 3: 1.0}, x=260, y=-1180)
    g.l(gscale_r, "Value", tintmix, "Factor")
    gstore = g.n("GeometryNodeStoreNamedAttribute", "StoreTint",
                 {"data_type": "FLOAT", "domain": "INSTANCE"}, {"Name": "tint"}, x=320, y=-700)
    g.l(grass3, "Instances", gstore, "Geometry")
    try:
        g.ng.links.new(tintmix.outputs[0], gstore.inputs["Value"])
    except Exception as e:
        P("store tint: %s" % e)

    # rocks: cubes, random rotation + scale read back from named attribute
    rdist = scatter("RockPts", "Rock Density", 29, -1350)
    rcube = g.n("GeometryNodeMeshCube", "RockCube", inputs={"Size": (0.35, 0.3, 0.22)}, x=-400, y=-1500)
    rocks = g.n("GeometryNodeInstanceOnPoints", "Rocks", x=-220, y=-1350)
    g.l(rdist, "Points", rocks, "Points")
    g.l(rcube, "Mesh", rocks, "Instance")
    rrot = g.n("FunctionNodeRandomValue", "RockRot", {"data_type": "FLOAT_VECTOR"},
               {"Min": (-0.3, -0.3, 0.0), "Max": (0.3, 0.3, 6.2832)}, x=-220, y=-1500)
    g.l(gin, "Seed", rrot, "Seed")
    rerot = g.n("FunctionNodeEulerToRotation", "RockEuler", x=-60, y=-1500)
    g.l(rrot, "Value", rerot, "Euler")
    rocks2 = g.n("GeometryNodeRotateInstances", "RockSpin", x=-40, y=-1350)
    g.l(rocks, "Instances", rocks2, "Instances")
    g.l(rerot, "Rotation", rocks2, "Rotation")
    rsr = g.n("FunctionNodeRandomValue", "RockSize", {"data_type": "FLOAT"},
              {"Min": 0.4, "Max": 1.8}, x=-40, y=-1650)
    g.l(gin, "Seed", rsr, "Seed")
    rstore = g.n("GeometryNodeStoreNamedAttribute", "StoreRS",
                 {"data_type": "FLOAT", "domain": "POINT"}, {"Name": "rs"}, x=-380, y=-1250)
    # store BEFORE instancing so instances inherit, then read back for scale
    g.ng.links.new(rdist.outputs["Points"], rstore.inputs["Geometry"])
    try:
        g.ng.links.new(rsr.outputs[1], rstore.inputs["Value"])
    except Exception:
        try:
            g.ng.links.new(rsr.outputs["Value"], rstore.inputs["Value"])
        except Exception as e:
            P("rock store: %s" % e)
    g.ng.links.new(rstore.outputs["Geometry"], rocks.inputs["Points"])
    rread = g.n("FunctionNodeInputBool", "veg?", x=-1500, y=-1200)  # placeholder replaced below
    g.ng.nodes.remove(rread)
    rnamed = g.n("GeometryNodeInputNamedAttribute", "rs", {"data_type": "FLOAT"}, {"Name": "rs"}, x=-40, y=-1780)
    rsv = g.n("ShaderNodeCombineXYZ", "RSV", x=120, y=-1780)
    for c in ("X", "Y", "Z"):
        g.l(rnamed, "Attribute", rsv, c)
    rocks3 = g.n("GeometryNodeScaleInstances", "RockScale", x=140, y=-1350)
    g.l(rocks2, "Instances", rocks3, "Instances")
    g.l(rsv, "Vector", rocks3, "Scale")

    vegjoin = g.n("GeometryNodeJoinGeometry", "Veg", x=520, y=-900)
    g.l(gstore, "Geometry", vegjoin, "Geometry")
    g.l(rocks3, "Instances", vegjoin, "Geometry")

    vegswitch = g.n("GeometryNodeSwitch", "VegSwitch", {"input_type": "GEOMETRY"}, x=700, y=-900)
    g.l(gin, "Show Vegetation", vegswitch, "Switch")
    try:
        g.ng.links.new(vegjoin.outputs["Geometry"], vegswitch.inputs["True"])
    except Exception as e:
        P("switch true: %s" % e)

    # ---- G. join everything ------------------------------------------
    join = g.n("GeometryNodeJoinGeometry", "Bridge+World", x=2440, y=100)
    for src, out in ((planks3, "Instances"), (rope, "Instances"), (posts, "Instances"),
                     (lanterns, "Instances"), (vegswitch, "Output"), (gin, "Geometry")):
        try:
            g.ng.links.new(src.outputs[out], join.inputs["Geometry"])
        except Exception as e:
            P("final join %s: %s" % (out, e))
    g.l(join, "Geometry", gout, "Geometry")

    return ng


def validate(ng):
    used = sorted({n.bl_idname for n in ng.nodes})
    bad = [i for i in used if i not in V1_WHITELIST]
    print("NODES USED (%d types, %d nodes):" % (len(used), len(ng.nodes)))
    for u in used:
        print("  ", u, "OK" if u in V1_WHITELIST else "*** OUTSIDE V1 ***")
    print("V1 VALIDATION:", "PASS" if not bad else "FAIL " + str(bad))
    return bad


def attach(ng):
    obj = bpy.data.objects.get("V1Bridge_Demo")
    if obj is None:
        bpy.ops.mesh.primitive_plane_add(size=16, location=(0, 0, 0))
        obj = bpy.context.active_object
        obj.name = "V1Bridge_Demo"
    for m in list(obj.modifiers):
        obj.modifiers.remove(m)
    mod = obj.modifiers.new("RopeBridgeV1", "NODES")
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
