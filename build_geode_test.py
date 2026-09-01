"""CrystalGeode_Test — validator stress-test effect (deliberately NOT V1-clean).

Runs inside Blender via the blender-mcp addon socket. Mixes the crystal-growth,
rock-generator and gradient-tint genres into one geode, while intentionally
tripping every refusal class in the exporter's validator:

  whitelist errors : Ico Sphere, Subdivide Mesh, Noise Texture, Geometry
                     Proximity, Voronoi Texture, Color Ramp, Set Material
  domain error     : Store Named Attribute on FACE domain
  structural errors: one MUTED node, one NESTED node group

DO NOT fix these — the point is a rich Validate report.
"""
import bpy

GROUP_NAME = "CrystalGeode_Test"
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


# ---- nested sub-group (structural refusal: GeometryNodeGroup) ----------
def build_core_subgroup():
    sub = fresh_group("GeodeCore_Sub")
    sg = G(sub)
    sock(sub, "Geometry", "OUTPUT", "NodeSocketGeometry")
    out = sg.n("NodeGroupOutput", x=300)
    core = sg.n("GeometryNodeMeshCube", "Core", inputs={"Size": (0.25, 0.25, 0.25)}, x=0)
    sg.l(core, "Mesh", out, "Geometry")
    return sub


def build():
    sub = build_core_subgroup()
    ng = fresh_group(GROUP_NAME)
    g = G(ng)

    sock(ng, "Geometry", "INPUT", "NodeSocketGeometry")
    sock(ng, "Rock Size", "INPUT", "NodeSocketFloat", 1.4)
    sock(ng, "Roughness", "INPUT", "NodeSocketFloat", 0.35)
    sock(ng, "Open Height", "INPUT", "NodeSocketFloat", 0.55)
    sock(ng, "Crystal Density", "INPUT", "NodeSocketFloat", 220.0)
    sock(ng, "Crystal Length", "INPUT", "NodeSocketFloat", 0.55)
    sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    sock(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")

    gin = g.n("NodeGroupInput", "Params", x=-1700)
    gout = g.n("NodeGroupOutput", "Out", x=1500)

    # ---- rock shell: NON-V1 ico sphere + subdivide + noise displacement
    ico = g.n("GeometryNodeMeshIcoSphere", "Shell", inputs={"Subdivisions": 3}, x=-1400, y=300)
    g.l(gin, "Rock Size", ico, "Radius")
    subd = g.n("GeometryNodeSubdivideMesh", "MoreFaces", inputs={"Level": 1}, x=-1220, y=300)
    g.l(ico, "Mesh", subd, "Mesh")

    noise = g.n("ShaderNodeTexNoise", "RockNoise", inputs={"Scale": 2.2, "Detail": 4.0}, x=-1220, y=60)
    centered = g.n("ShaderNodeMath", "fac-0.5", {"operation": "SUBTRACT"}, x=-1040, y=60)
    g.l(noise, "Fac", centered, 0)
    centered.inputs[1].default_value = 0.5
    amp = g.n("ShaderNodeMath", "amp", {"operation": "MULTIPLY"}, x=-880, y=60)
    g.l(centered, "Value", amp, 0)
    g.l(gin, "Roughness", amp, 1)
    nrm = g.n("GeometryNodeInputNormal", "N", x=-1040, y=-80)
    disp = g.n("ShaderNodeVectorMath", "Displace", {"operation": "SCALE"}, x=-720, y=0)
    g.l(nrm, "Normal", disp, 0)
    g.l(amp, "Value", disp, "Scale")
    bump = g.n("GeometryNodeSetPosition", "Bumpy", x=-560, y=300)
    g.l(subd, "Mesh", bump, "Geometry")
    g.l(disp, "Vector", bump, "Offset")

    # muted transform (structural refusal: muted node passes through visually)
    mutet = g.n("GeometryNodeTransform", "MUTED (test)", x=-380, y=300)
    mutet.mute = True
    g.l(bump, "Geometry", mutet, "Geometry")

    # crack the geode open: delete everything above Open Height
    pos = g.n("GeometryNodeInputPosition", "P", x=-380, y=80)
    pz = g.n("ShaderNodeSeparateXYZ", "Pz", x=-220, y=80)
    g.l(pos, "Position", pz, "Vector")
    above = g.n("FunctionNodeCompare", "z>open", {"operation": "GREATER_THAN", "data_type": "FLOAT"},
                x=-60, y=80)
    g.l(pz, "Z", above, "A")
    g.l(gin, "Open Height", above, "B")
    crack = g.n("GeometryNodeDeleteGeometry", "CrackOpen", {"domain": "FACE"}, x=100, y=300)
    g.l(mutet, "Geometry", crack, "Geometry")
    g.l(above, "Result", crack, "Selection")

    # ---- tint: NON-V1 voronoi + color ramp, stored on FACE domain ------
    voro = g.n("ShaderNodeTexVoronoi", "CellTint", inputs={"Scale": 3.5}, x=100, y=-60)
    ramp = g.n("ShaderNodeValToRGB", "TintRamp", x=280, y=-60)
    g.l(voro, "Distance", ramp, "Fac")
    try:
        ramp.color_ramp.elements[0].color = (0.35, 0.1, 0.6, 1.0)
        ramp.color_ramp.elements[1].color = (0.2, 0.85, 0.9, 1.0)
    except Exception as e:
        P("ramp colors: %s" % e)
    tint = g.n("GeometryNodeStoreNamedAttribute", "FaceTint",
               {"data_type": "FLOAT_COLOR", "domain": "FACE"}, {"Name": "tint"}, x=560, y=300)
    g.l(crack, "Geometry", tint, "Geometry")
    g.l(ramp, "Color", tint, "Value")

    mat = bpy.data.materials.get("M_GeodeCrystal") or bpy.data.materials.new("M_GeodeCrystal")
    mat.diffuse_color = (0.45, 0.2, 0.8, 1.0)
    setmat = g.n("GeometryNodeSetMaterial", "CrystalMat", x=740, y=300)
    g.l(tint, "Geometry", setmat, "Geometry")
    try:
        setmat.inputs["Material"].default_value = mat
    except Exception as e:
        P("set material: %s" % e)

    # ---- crystals: distribute inside, grow by NON-V1 proximity to core -
    dist = g.n("GeometryNodeDistributePointsOnFaces", "ShardPts", x=100, y=-400)
    g.l(crack, "Geometry", dist, "Mesh")
    g.l(gin, "Crystal Density", dist, "Density")
    g.l(gin, "Seed", dist, "Seed")

    corept = g.n("GeometryNodePoints", "CorePt", inputs={"Count": 1}, x=100, y=-620)
    prox = g.n("GeometryNodeProximity", "CoreProximity", x=280, y=-620)
    g.l(corept, "Points", prox, "Geometry")
    grow = g.n("ShaderNodeMapRange", "Grow", inputs={1: 0.0, 3: 1.6, 4: 0.5}, x=460, y=-620)
    g.l(prox, "Distance", grow, "Value")
    g.l(gin, "Rock Size", grow, 2)

    shard = g.n("GeometryNodeMeshCube", "Shard", inputs={"Size": (0.07, 0.07, 1.0)}, x=280, y=-400)
    shardb = g.n("GeometryNodeTransform", "ShardB",
                 inputs={"Translation": (0.0, 0.0, 0.5)}, x=460, y=-400)
    g.l(shard, "Mesh", shardb, "Geometry")

    inward = g.n("ShaderNodeVectorMath", "Inward", {"operation": "SCALE"},
                 inputs={"Scale": -1.0}, x=280, y=-260)
    g.l(dist, "Normal", inward, 0)
    align = g.n("FunctionNodeAlignRotationToVector", "AlignIn", {"axis": "Z"}, x=460, y=-260)
    g.l(inward, "Vector", align, "Vector")

    shards = g.n("GeometryNodeInstanceOnPoints", "Shards", x=680, y=-400)
    g.l(dist, "Points", shards, "Points")
    g.l(shardb, "Geometry", shards, "Instance")
    g.l(align, "Rotation", shards, "Rotation")

    ssize = g.n("ShaderNodeMath", "len*grow", {"operation": "MULTIPLY"}, x=680, y=-620)
    g.l(gin, "Crystal Length", ssize, 0)
    g.l(grow, "Result", ssize, 1)
    sscale = g.n("ShaderNodeCombineXYZ", "ShardScale", x=860, y=-620)
    jitter = g.n("FunctionNodeRandomValue", "WidthJit", {"data_type": "FLOAT"},
                 {"Min": 0.6, "Max": 1.4}, x=680, y=-780)
    g.l(gin, "Seed", jitter, "Seed")
    g.l(jitter, "Value", sscale, "X")
    g.l(jitter, "Value", sscale, "Y")
    g.l(ssize, "Value", sscale, "Z")
    sgrow = g.n("GeometryNodeScaleInstances", "ShardGrow", x=880, y=-400)
    g.l(shards, "Instances", sgrow, "Instances")
    g.l(sscale, "Vector", sgrow, "Scale")

    # ---- nested group instance (structural refusal) --------------------
    coreg = g.n("GeometryNodeGroup", "NestedCore", x=740, y=-100)
    try:
        coreg.node_tree = sub
    except Exception as e:
        P("nested group: %s" % e)

    join = g.n("GeometryNodeJoinGeometry", "Geode", x=1200, y=100)
    for src, out in ((setmat, "Geometry"), (sgrow, "Instances"), (coreg, "Geometry")):
        try:
            g.ng.links.new(src.outputs[out], join.inputs["Geometry"])
        except Exception as e:
            P("join %s: %s" % (out, e))
    g.l(join, "Geometry", gout, "Geometry")
    return ng


def attach(ng):
    obj = bpy.data.objects.get("GeodeTest_Demo")
    if obj is None:
        bpy.ops.mesh.primitive_plane_add(size=0.1, location=(0, 20, 1.5))
        obj = bpy.context.active_object
        obj.name = "GeodeTest_Demo"
    for m in list(obj.modifiers):
        obj.modifiers.remove(m)
    obj.modifiers.new("GeodeTest", "NODES").node_group = ng
    return obj


ng = build()
obj = attach(ng)
bpy.context.view_layer.update()
used = sorted({n.bl_idname for n in ng.nodes})
print("BUILD DONE: %s nodes=%d types=%d problems=%d object=%s"
      % (ng.name, len(ng.nodes), len(used), len(PROBLEMS), obj.name))
for p in PROBLEMS:
    print("  P:", p)
