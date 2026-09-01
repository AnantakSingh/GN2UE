"""CubeField_FX v2 — proximity-eater greeble PIPE (freeform showcase, NOT V1).

v2 changes (user feedback): host is the user's `pipe` object instead of a
plane; towers distribute over the pipe surface aligned to its normals; one
noise field drives coverage patches, tower height and a stored `grad`
attribute that the materials ramp against (noise-based gradients); all
emission strengths pulled way down for a subtler look.

The `FieldController` cube still eats the field: towers within its influence
radius smoothly scale to zero, with a faint heat ring at the edge.
"""
import bpy

GROUP_NAME = "CubeField_FX"
PROBLEMS = []


def P(msg):
    PROBLEMS.append(msg)
    print("PROBLEM:", msg)


def fresh_group(name):
    old = bpy.data.node_groups.get(name)
    if old:
        bpy.data.node_groups.remove(old)
    return bpy.data.node_groups.new(name, "GeometryNodeTree")


def sock(ng, name, in_out, stype, default=None):
    s = ng.interface.new_socket(name=name, in_out=in_out, socket_type=stype)
    if default is not None:
        try:
            s.default_value = default
        except Exception as e:
            P("iface %s: %s" % (name, e))
    return s


class G:
    def __init__(self, nt):
        self.nt = nt

    def n(self, idname, label="", props=None, inputs=None, x=0, y=0):
        nd = self.nt.nodes.new(idname)
        if label:
            nd.label = label
        nd.location = (x, y)
        for k, v in (props or {}).items():
            try:
                setattr(nd, k, v)
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
            self.nt.links.new(a.outputs[out], b.inputs[inp])
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


# ------------------------------------------------------------ materials
def mat_new(name):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    m.node_tree.nodes.clear()
    return m, G(m.node_tree)


def build_materials():
    # towers: dark metal; sparse dim windows; color drifts with `grad` noise;
    # faint warm heat-ring near the controller edge
    m, s = mat_new("M_FieldTower")
    out = s.n("ShaderNodeOutputMaterial", x=1000)
    p = s.n("ShaderNodeBsdfPrincipled", x=680,
            inputs={"Metallic": 0.8, "Roughness": 0.42})
    grad = s.n("ShaderNodeAttribute", x=-650, y=-320, props={"attribute_name": "grad"})
    base = s.n("ShaderNodeMix", x=-380, y=-320, props={"data_type": "RGBA"},
               inputs={"A": (0.022, 0.028, 0.045, 1), "B": (0.05, 0.024, 0.05, 1)})
    s.l(grad, "Fac", base, "Factor")
    try:
        s.l(base, 2, p, "Base Color")
    except Exception as e:
        P("tower base: %s" % e)

    geo = s.n("ShaderNodeNewGeometry", x=-650, y=60)
    sep = s.n("ShaderNodeSeparateXYZ", x=-470, y=60)
    s.l(geo, "Position", sep, "Vector")
    rnd = s.n("ShaderNodeAttribute", x=-650, y=-120, props={"attribute_name": "rnd"})
    phase = s.math("MULTIPLY", a=(rnd, "Fac"), x=-470, y=-120, c2=7.0)
    zf = s.math("MULTIPLY", a=(sep, "Z"), x=-290, y=60, c2=7.0)
    zp = s.math("ADD", a=(zf, "Value"), b=(phase, "Value"), x=-130, y=60)
    stripe = s.math("FLOORED_MODULO", a=(zp, "Value"), x=30, y=60, c2=1.0)
    win = s.math("GREATER_THAN", a=(stripe, "Value"), x=190, y=60, c2=0.82)

    glow = s.n("ShaderNodeAttribute", x=-130, y=-460, props={"attribute_name": "glow"})
    # emission color: gradient tint (teal -> dusty magenta), pushed toward
    # ember orange only inside the heat ring
    tint = s.n("ShaderNodeMix", x=190, y=-260, props={"data_type": "RGBA"},
               inputs={"A": (0.25, 0.75, 0.8, 1), "B": (0.75, 0.35, 0.65, 1)})
    s.l(grad, "Fac", tint, "Factor")
    ecol = s.n("ShaderNodeMix", x=420, y=-260, props={"data_type": "RGBA"},
               inputs={"B": (1.0, 0.42, 0.12, 1)})
    s.l(tint, 2, ecol, "A")
    s.l(glow, "Fac", ecol, "Factor")
    winstr = s.math("MULTIPLY", a=(win, "Value"), x=360, y=60, c2=0.5)
    gmod = s.math("MULTIPLY", a=(grad, "Fac"), x=360, y=-60, c2=0.35, label="gradglow")
    ringstr = s.math("MULTIPLY", a=(glow, "Fac"), x=360, y=-140, c2=2.0)
    e1 = s.math("ADD", a=(winstr, "Value"), b=(gmod, "Value"), x=520, y=0)
    estr = s.math("ADD", a=(e1, "Value"), b=(ringstr, "Value"), x=660, y=-60)
    try:
        s.l(ecol, 2, p, "Emission Color")
        s.l(estr, "Value", p, "Emission Strength")
    except Exception as e:
        P("tower emission: %s" % e)
    s.l(p, "BSDF", out, "Surface")

    # greebles: dark, muted two-tone by gid, tiny glow lift inside the ring
    m2, s2 = mat_new("M_FieldGreeble")
    out2 = s2.n("ShaderNodeOutputMaterial", x=700)
    p2 = s2.n("ShaderNodeBsdfPrincipled", x=420,
              inputs={"Base Color": (0.02, 0.022, 0.03, 1), "Metallic": 0.55, "Roughness": 0.5})
    gid = s2.n("ShaderNodeAttribute", x=-300, props={"attribute_name": "gid"})
    ramp = s2.n("ShaderNodeValToRGB", x=-100)
    s2.l(gid, "Fac", ramp, "Fac")
    try:
        ramp.color_ramp.elements[0].color = (0.65, 0.4, 0.2, 1)
        ramp.color_ramp.elements[1].color = (0.2, 0.55, 0.5, 1)
    except Exception as e:
        P("greeble ramp: %s" % e)
    glow2 = s2.n("ShaderNodeAttribute", x=-100, y=-220, props={"attribute_name": "glow"})
    gstr = s2.math("MULTIPLY", a=(glow2, "Fac"), x=120, y=-220, c2=1.2)
    gbase = s2.math("ADD", a=(gstr, "Value"), x=280, y=-220, c2=0.28)
    try:
        s2.l(ramp, "Color", p2, "Emission Color")
        s2.l(gbase, "Value", p2, "Emission Strength")
    except Exception as e:
        P("greeble emission: %s" % e)
    s2.l(p2, "BSDF", out2, "Surface")

    # pipe hull: dark metal, very faint panel grid
    m3, s3 = mat_new("M_FieldGround")
    out3 = s3.n("ShaderNodeOutputMaterial", x=900)
    p3 = s3.n("ShaderNodeBsdfPrincipled", x=620,
              inputs={"Base Color": (0.018, 0.02, 0.03, 1), "Metallic": 0.65, "Roughness": 0.38})
    geo3 = s3.n("ShaderNodeNewGeometry", x=-700)
    sep3 = s3.n("ShaderNodeSeparateXYZ", x=-520)
    s3.l(geo3, "Position", sep3, "Vector")

    def gridline(axis, y):
        f = s3.math("FLOORED_MODULO", a=(sep3, axis), x=-360, y=y, c2=2.0)
        d = s3.math("SUBTRACT", a=(f, "Value"), x=-200, y=y, c2=1.0)
        ab = s3.math("ABSOLUTE", a=(d, "Value"), x=-40, y=y)
        return s3.math("GREATER_THAN", a=(ab, "Value"), x=120, y=y, c2=0.965)

    lx = gridline("X", 60)
    lz = gridline("Z", -120)
    lines = s3.math("MAXIMUM", a=(lx, "Value"), b=(lz, "Value"), x=300, y=0)
    lstr = s3.math("MULTIPLY", a=(lines, "Value"), x=460, y=0, c2=0.25)
    try:
        p3.inputs["Emission Color"].default_value = (0.12, 0.5, 0.55, 1)
        s3.l(lstr, "Value", p3, "Emission Strength")
    except Exception as e:
        P("hull emission: %s" % e)
    s3.l(p3, "BSDF", out3, "Surface")

    # controller: warm but restrained
    m4, s4 = mat_new("M_FieldController")
    out4 = s4.n("ShaderNodeOutputMaterial", x=300)
    em = s4.n("ShaderNodeEmission", x=60, inputs={"Color": (1.0, 0.3, 0.1, 1), "Strength": 3.0})
    s4.l(em, "Emission", out4, "Surface")
    return {"tower": bpy.data.materials["M_FieldTower"],
            "greeble": bpy.data.materials["M_FieldGreeble"],
            "hull": bpy.data.materials["M_FieldGround"],
            "controller": bpy.data.materials["M_FieldController"]}


# ------------------------------------------------------------ geometry
def build(mats, controller):
    ng = fresh_group(GROUP_NAME)
    g = G(ng)

    sock(ng, "Geometry", "INPUT", "NodeSocketGeometry")
    sock(ng, "Density", "INPUT", "NodeSocketFloat", 2.4)
    sock(ng, "Coverage", "INPUT", "NodeSocketFloat", 0.62)
    sock(ng, "Noise Scale", "INPUT", "NodeSocketFloat", 0.28)
    sock(ng, "Tower Height", "INPUT", "NodeSocketFloat", 1.5)
    sock(ng, "Height Random", "INPUT", "NodeSocketFloat", 1.0)
    sock(ng, "Footprint", "INPUT", "NodeSocketFloat", 0.34)
    sock(ng, "Greeble Density", "INPUT", "NodeSocketFloat", 5.0)
    sock(ng, "Greeble Size", "INPUT", "NodeSocketFloat", 0.12)
    sock(ng, "Influence Radius", "INPUT", "NodeSocketFloat", 4.0)
    sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    sock(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")

    gin = g.n("NodeGroupInput", "Params", x=-2100)
    gout = g.n("NodeGroupOutput", "Out", x=2300)

    # ---- one coherent noise field: coverage mask + height + grad tint --
    pos = g.n("GeometryNodeInputPosition", "P", x=-1900, y=-40)
    noise = g.n("ShaderNodeTexNoise", "Field", inputs={"Detail": 3.0}, x=-1740, y=-40)
    g.l(pos, "Position", noise, "Vector")
    g.l(gin, "Noise Scale", noise, "Scale")
    thresh = g.math("SUBTRACT", x=-1740, y=-220, c1=1.0, label="1-cov")
    g.l(gin, "Coverage", thresh, 1)
    keep = g.math("GREATER_THAN", a=(noise, "Fac"), b=(thresh, "Value"), x=-1580, y=-120)

    # ---- towers distributed over the pipe surface ----------------------
    dist = g.n("GeometryNodeDistributePointsOnFaces", "TowerPts", x=-1420, y=260)
    g.l(gin, "Geometry", dist, "Mesh")
    g.l(keep, "Value", dist, "Selection")
    g.l(gin, "Density", dist, "Density")
    g.l(gin, "Seed", dist, "Seed")

    # ---- controller proximity -> collapse factor + heat ring -----------
    objinfo = g.n("GeometryNodeObjectInfo", "Controller", {"transform_space": "RELATIVE"},
                  x=-1420, y=-320)
    try:
        objinfo.inputs["Object"].default_value = controller
    except Exception as e:
        P("controller ref: %s" % e)
    dvec = g.n("ShaderNodeVectorMath", "ToCtl", {"operation": "SUBTRACT"}, x=-1260, y=-280)
    g.l(pos, "Position", dvec, 0)
    g.l(objinfo, "Location", dvec, 1)
    distc = g.n("ShaderNodeVectorMath", "Dist", {"operation": "LENGTH"}, x=-1100, y=-280)
    g.l(dvec, "Vector", distc, 0)
    factor = g.n("ShaderNodeMapRange", "Collapse", {"interpolation_type": "SMOOTHSTEP"},
                 inputs={1: 0.3, 3: 0.0, 4: 1.0}, x=-940, y=-280)
    g.l(distc, "Value", factor, "Value")
    g.l(gin, "Influence Radius", factor, 2)
    f2 = g.math("MULTIPLY", a=(factor, "Result"), x=-780, y=-420, c2=2.0)
    f2m1 = g.math("SUBTRACT", a=(f2, "Value"), x=-620, y=-420, c2=1.0)
    fabs = g.math("ABSOLUTE", a=(f2m1, "Value"), x=-460, y=-420)
    ring = g.math("SUBTRACT", a=(fabs, "Value"), x=-300, y=-420, c1=1.0, label="ring")
    g.l(fabs, "Value", ring, 1)

    rnd = g.n("FunctionNodeRandomValue", "RndPer", {"data_type": "FLOAT"},
              {"Min": 0.0, "Max": 1.0}, x=-1100, y=-40)
    g.l(gin, "Seed", rnd, "Seed")

    st1 = g.n("GeometryNodeStoreNamedAttribute", "StoreGlow",
              {"data_type": "FLOAT", "domain": "POINT"}, {"Name": "glow"}, x=-1240, y=260)
    g.l(dist, "Points", st1, "Geometry")
    g.l(ring, "Value", st1, "Value")
    st2 = g.n("GeometryNodeStoreNamedAttribute", "StoreRnd",
              {"data_type": "FLOAT", "domain": "POINT"}, {"Name": "rnd"}, x=-1080, y=260)
    g.l(st1, "Geometry", st2, "Geometry")
    g.l(rnd, "Value", st2, "Value")
    st3 = g.n("GeometryNodeStoreNamedAttribute", "StoreGrad",
              {"data_type": "FLOAT", "domain": "POINT"}, {"Name": "grad"}, x=-920, y=260)
    g.l(st2, "Geometry", st3, "Geometry")
    g.l(noise, "Fac", st3, "Value")

    # ---- tower instances: radial (normal-aligned), height by noise -----
    hshape = g.n("ShaderNodeMapRange", "Wave", inputs={1: 0.0, 2: 1.0, 3: 0.35, 4: 1.3},
                 x=-760, y=-40)
    g.l(noise, "Fac", hshape, "Value")
    hr = g.math("MULTIPLY", a=(rnd, "Value"), x=-760, y=-160, label="hrand")
    g.l(gin, "Height Random", hr, 1)
    hbase = g.math("ADD", a=(hr, "Value"), x=-600, y=-160, c2=0.3)
    hmix = g.math("MULTIPLY", a=(hbase, "Value"), b=(hshape, "Result"), x=-440, y=-100)
    h = g.math("MULTIPLY", a=(hmix, "Value"), x=-280, y=-100)
    g.l(gin, "Tower Height", h, 1)

    tower = g.n("GeometryNodeMeshCube", "Tower", inputs={"Size": (1.0, 1.0, 1.0)}, x=-600, y=520)
    towerb = g.n("GeometryNodeTransform", "TowerB", inputs={"Translation": (0, 0, 0.5)}, x=-440, y=520)
    g.l(tower, "Mesh", towerb, "Geometry")

    align = g.n("FunctionNodeAlignRotationToVector", "AlignN", {"axis": "Z"}, x=-760, y=120)
    g.l(dist, "Normal", align, "Vector")

    tinst = g.n("GeometryNodeInstanceOnPoints", "Towers", x=-260, y=260)
    g.l(st3, "Geometry", tinst, "Points")
    g.l(towerb, "Geometry", tinst, "Instance")
    g.l(align, "Rotation", tinst, "Rotation")

    fp = g.n("FunctionNodeRandomValue", "FpRand", {"data_type": "FLOAT"},
             {"Min": 0.75, "Max": 1.25}, x=-260, y=40)
    g.l(gin, "Seed", fp, "Seed")
    fpx = g.math("MULTIPLY", a=(fp, "Value"), x=-100, y=40)
    g.l(gin, "Footprint", fpx, 1)
    sx = g.math("MULTIPLY", a=(fpx, "Value"), b=(factor, "Result"), x=60, y=40)
    sz = g.math("MULTIPLY", a=(h, "Value"), b=(factor, "Result"), x=60, y=-80)
    svec = g.n("ShaderNodeCombineXYZ", "TScale", x=220, y=-20)
    g.l(sx, "Value", svec, "X")
    g.l(sx, "Value", svec, "Y")
    g.l(sz, "Value", svec, "Z")
    tscale = g.n("GeometryNodeScaleInstances", "CollapseScale", x=220, y=260)
    g.l(tinst, "Instances", tscale, "Instances")
    g.l(svec, "Vector", tscale, "Scale")

    real = g.n("GeometryNodeRealizeInstances", "Realize", x=400, y=260)
    g.l(tscale, "Instances", real, "Geometry")
    tmat = g.n("GeometryNodeSetMaterial", "TowerMat", x=580, y=260)
    g.l(real, "Geometry", tmat, "Geometry")
    try:
        tmat.inputs["Material"].default_value = mats["tower"]
    except Exception as e:
        P("tower mat: %s" % e)

    # ---- greebles on tower surfaces ------------------------------------
    gd = g.n("GeometryNodeDistributePointsOnFaces", "GreeblePts", x=580, y=-120)
    g.l(real, "Geometry", gd, "Mesh")
    g.l(gin, "Greeble Density", gd, "Density")
    gseed = g.math("ADD", x=400, y=-260, c2=7.0)
    g.l(gin, "Seed", gseed, 0)
    g.l(gseed, "Value", gd, "Seed")

    gcube = g.n("GeometryNodeMeshCube", "Greeble", inputs={"Size": (1.0, 1.0, 0.35)}, x=580, y=-420)
    galign = g.n("FunctionNodeAlignRotationToVector", "GAlign", {"axis": "Z"}, x=760, y=-260)
    g.l(gd, "Normal", galign, "Vector")
    ginst = g.n("GeometryNodeInstanceOnPoints", "Greebles", x=940, y=-120)
    g.l(gd, "Points", ginst, "Points")
    g.l(gcube, "Mesh", ginst, "Instance")
    g.l(galign, "Rotation", ginst, "Rotation")

    gsr = g.n("FunctionNodeRandomValue", "GSize", {"data_type": "FLOAT"},
              {"Min": 0.4, "Max": 1.6}, x=940, y=-320)
    g.l(gseed, "Value", gsr, "Seed")
    gsx = g.math("MULTIPLY", a=(gsr, "Value"), x=1100, y=-320)
    g.l(gin, "Greeble Size", gsx, 1)
    gsv = g.n("ShaderNodeCombineXYZ", "GSV", x=1260, y=-320)
    for c in ("X", "Y", "Z"):
        g.l(gsx, "Value", gsv, c)
    gscale = g.n("GeometryNodeScaleInstances", "GScale", x=1120, y=-120)
    g.l(ginst, "Instances", gscale, "Instances")
    g.l(gsv, "Vector", gscale, "Scale")

    gidr = g.n("FunctionNodeRandomValue", "GidRand", {"data_type": "FLOAT"},
               {"Min": 0.0, "Max": 1.0}, x=1120, y=-320)
    g.l(gseed, "Value", gidr, "Seed")
    gst = g.n("GeometryNodeStoreNamedAttribute", "StoreGid",
              {"data_type": "FLOAT", "domain": "INSTANCE"}, {"Name": "gid"}, x=1300, y=-120)
    g.l(gscale, "Instances", gst, "Geometry")
    g.l(gidr, "Value", gst, "Value")
    gmat = g.n("GeometryNodeSetMaterial", "GreebleMat", x=1480, y=-120)
    g.l(gst, "Geometry", gmat, "Geometry")
    try:
        gmat.inputs["Material"].default_value = mats["greeble"]
    except Exception as e:
        P("greeble mat: %s" % e)

    # ---- pipe hull + join ----------------------------------------------
    hull = g.n("GeometryNodeSetMaterial", "HullMat", x=580, y=520)
    g.l(gin, "Geometry", hull, "Geometry")
    try:
        hull.inputs["Material"].default_value = mats["hull"]
    except Exception as e:
        P("hull mat: %s" % e)

    join = g.n("GeometryNodeJoinGeometry", "Field", x=2100, y=100)
    for src, outn in ((hull, "Geometry"), (tmat, "Geometry"), (gmat, "Geometry")):
        try:
            g.nt.links.new(src.outputs[outn], join.inputs["Geometry"])
        except Exception as e:
            P("join: %s" % e)
    g.l(join, "Geometry", gout, "Geometry")
    return ng


def setup_scene():
    ctl = bpy.data.objects.get("FieldController")
    if ctl is None:
        bpy.ops.mesh.primitive_cube_add(size=1.2, location=(9.0, -2.0, 3.0))
        ctl = bpy.context.active_object
        ctl.name = "FieldController"
    else:
        ctl.location = (9.0, -2.0, 3.0)  # move next to the pipe
    pipe = bpy.data.objects.get("pipe")
    if pipe is None:
        raise RuntimeError("no 'pipe' object in scene")
    old = bpy.data.objects.get("CubeField_Demo")
    if old is not None:
        for m in list(old.modifiers):
            old.modifiers.remove(m)
    return pipe, ctl


mats = build_materials()
host, ctl = setup_scene()
ctl.data.materials.clear()
ctl.data.materials.append(mats["controller"])
ng = build(mats, ctl)
for m in list(host.modifiers):
    host.modifiers.remove(m)
host.modifiers.new("CubeFieldFX", "NODES").node_group = ng
bpy.context.view_layer.update()
print("BUILD DONE: %s nodes=%d problems=%d host=%s controller=%s"
      % (ng.name, len(ng.nodes), len(PROBLEMS), host.name, ctl.name))
for p in PROBLEMS:
    print("  P:", p)
