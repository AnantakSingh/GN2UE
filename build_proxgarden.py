"""ProxGarden — a phyllotaxis 'spire garden' that reacts to a proximity
controller. ~120 tall spires in a sunflower (golden-angle) spiral with varied
heights; near the controller they shrink and settle, far from it they stand
tall and (via the imported dynamics material) spin + shake. Blender only
expresses layout + proximity->scale; supported nodes only.
"""
import bpy

GROUP_NAME = "ProxGarden"
CTRL_NAME = "GardenCtrl"
GOLDEN = 2.39996322973   # golden angle (radians)
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


ctrl = bpy.data.objects.get(CTRL_NAME)
if ctrl is None:
    ctrl = bpy.data.objects.new(CTRL_NAME, None)
    ctrl.empty_display_size = 0.5
    bpy.context.scene.collection.objects.link(ctrl)
ctrl.location = (3.0, 0.0, 1.0)

ng = fresh_group(GROUP_NAME)
sock(ng, "Geometry", "INPUT", "NodeSocketGeometry")
sock(ng, "Spires", "INPUT", "NodeSocketInt", 120)
sock(ng, "Spacing", "INPUT", "NodeSocketFloat", 0.52)
sock(ng, "Influence Radius", "INPUT", "NodeSocketFloat", 5.0)
sock(ng, "Near Scale", "INPUT", "NodeSocketFloat", 0.15)
sock(ng, "Height Min", "INPUT", "NodeSocketFloat", 0.55)
sock(ng, "Height Max", "INPUT", "NodeSocketFloat", 1.5)
sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
sock(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")

g = G(ng)
gin = g.n("NodeGroupInput", "In", x=-1800)
gout = g.n("NodeGroupOutput", "Out", x=1000)

# ---- phyllotaxis points: angle = i*golden, radius = Spacing*sqrt(i) ----
pts = g.n("GeometryNodePoints", "Pts", x=-1600, y=240)
g.l(gin, "Spires", pts, "Count")
idx = g.n("GeometryNodeInputIndex", "Idx", x=-1600, y=-40)
ang = g.math("MULTIPLY", a=(idx, "Index"), c2=GOLDEN, x=-1440, y=40, label="angle")
rsq = g.math("SQRT", a=(idx, "Index"), x=-1440, y=-160, label="sqrt_i")
rad = g.math("MULTIPLY", a=(rsq, "Value"), x=-1280, y=-160, label="radius")
g.l(gin, "Spacing", rad, 1)
cx = g.math("COSINE", a=(ang, "Value"), x=-1120, y=120)
sy = g.math("SINE", a=(ang, "Value"), x=-1120, y=-40)
px = g.math("MULTIPLY", a=(cx, "Value"), b=(rad, "Value"), x=-960, y=120, label="x")
py = g.math("MULTIPLY", a=(sy, "Value"), b=(rad, "Value"), x=-960, y=-40, label="y")
posv = g.n("ShaderNodeCombineXYZ", "Pos", x=-800, y=40)
g.l(px, "Value", posv, "X")
g.l(py, "Value", posv, "Y")
setpos = g.n("GeometryNodeSetPosition", "Place", x=-620, y=240)
g.l(pts, "Points", setpos, "Geometry")
g.l(posv, "Vector", setpos, "Position")

# ---- spire instance (tall thin) --------------------------------------
spire = g.n("GeometryNodeMeshCube", "Spire", inputs={"Size": (0.4, 0.4, 3.0)}, x=-800, y=500)
spireb = g.n("GeometryNodeTransform", "SpireBase", inputs={"Translation": (0, 0, 1.5)}, x=-620, y=500)
g.l(spire, "Mesh", spireb, "Geometry")
inst = g.n("GeometryNodeInstanceOnPoints", "Spires", x=-420, y=240)
g.l(setpos, "Geometry", inst, "Points")
g.l(spireb, "Geometry", inst, "Instance")

# ---- per-spire random height -----------------------------------------
hr = g.n("FunctionNodeRandomValue", "HRand", {"data_type": "FLOAT"}, x=-620, y=-260)
g.l(gin, "Height Min", hr, 2)
g.l(gin, "Height Max", hr, 3)
g.l(gin, "Seed", hr, "Seed")

# ---- proximity -> scale (near small, far full) -----------------------
objinfo = g.n("GeometryNodeObjectInfo", "Controller", {"transform_space": "RELATIVE"},
              x=-1120, y=-420)
try:
    objinfo.inputs["Object"].default_value = ctrl
except Exception as e:
    P("controller ref: %s" % e)
pos2 = g.n("GeometryNodeInputPosition", "PtPos", x=-1120, y=-560)
dvec = g.n("ShaderNodeVectorMath", "ToCtl", {"operation": "SUBTRACT"}, x=-940, y=-480)
g.l(pos2, "Position", dvec, 0)
g.l(objinfo, "Location", dvec, 1)
distc = g.n("ShaderNodeVectorMath", "Dist", {"operation": "LENGTH"}, x=-780, y=-480)
g.l(dvec, "Vector", distc, 0)
factor = g.n("ShaderNodeMapRange", "Prox", {"interpolation_type": "SMOOTHSTEP"},
             inputs={1: 0.3, 4: 1.0}, x=-600, y=-480)
g.l(distc, "Value", factor, "Value")
g.l(gin, "Influence Radius", factor, 2)
g.l(gin, "Near Scale", factor, 3)

# scale: X,Y = factor ; Z = factor * heightRandom  (proximity + baked height)
sz = g.math("MULTIPLY", a=(factor, "Result"), b=(hr, "Value"), x=-380, y=-300, label="sz")
svec = g.n("ShaderNodeCombineXYZ", "SVec", x=-200, y=-380)
g.l(factor, "Result", svec, "X")
g.l(factor, "Result", svec, "Y")
g.l(sz, "Value", svec, "Z")
scal = g.n("GeometryNodeScaleInstances", "ProxScale", x=200, y=240)
g.l(inst, "Instances", scal, "Instances")
g.l(svec, "Vector", scal, "Scale")
g.l(scal, "Instances", gout, "Geometry")

# ---- host object -----------------------------------------------------
obj = bpy.data.objects.get("ProxGarden_Demo")
if obj is None:
    bpy.ops.mesh.primitive_plane_add(size=1, location=(105, 0, 0))
    obj = bpy.context.active_object
    obj.name = "ProxGarden_Demo"
for m in list(obj.modifiers):
    obj.modifiers.remove(m)
obj.modifiers.new("ProxGarden", "NODES").node_group = ng

print("PROXGARDEN BUILD:", "OK" if not PROBLEMS else "PROBLEMS")
for p in PROBLEMS:
    print("  ", p)
print("nodes:", len(ng.nodes), "controller:", CTRL_NAME, "at", tuple(ctrl.location))
