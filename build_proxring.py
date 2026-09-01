"""ProxRing — a ring of upright monoliths that react to a proximity controller.

Deliberately minimal + low instance count (48 stones) as a clean test of the
UE dynamics layer: near the controller the stones are small/still/calm, far
from it they scale up and (via the imported dynamics material) spin + shake.
Blender only expresses the proximity->scale binding; the spin/shake is added
by the importer's M_GNueDyn material. Uses only supported nodes.
"""
import bpy

GROUP_NAME = "ProxRing"
CTRL_NAME = "RingCtrl"
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


# controller object the effect binds to (its NAME becomes the UE actor tag)
ctrl = bpy.data.objects.get(CTRL_NAME)
if ctrl is None:
    ctrl = bpy.data.objects.new(CTRL_NAME, None)   # empty; only its position matters
    ctrl.empty_display_size = 0.5
    bpy.context.scene.collection.objects.link(ctrl)
ctrl.location = (2.0, 0.0, 1.0)

ng = fresh_group(GROUP_NAME)
sock(ng, "Geometry", "INPUT", "NodeSocketGeometry")
sock(ng, "Stones", "INPUT", "NodeSocketInt", 48)
sock(ng, "Radius", "INPUT", "NodeSocketFloat", 6.0)
sock(ng, "Influence Radius", "INPUT", "NodeSocketFloat", 4.0)
sock(ng, "Near Scale", "INPUT", "NodeSocketFloat", 0.2)
sock(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")

g = G(ng)
gin = g.n("NodeGroupInput", "In", x=-1600)
gout = g.n("NodeGroupOutput", "Out", x=900)

# ---- ring of points: index -> angle -> (cos,sin)*Radius --------------
pts = g.n("GeometryNodePoints", "RingPts", x=-1400, y=200)
g.l(gin, "Stones", pts, "Count")
idx = g.n("GeometryNodeInputIndex", "Idx", x=-1400, y=-40)
frac = g.math("DIVIDE", a=(idx, "Index"), x=-1240, y=-40)
g.l(gin, "Stones", frac, 1)
ang = g.math("MULTIPLY", a=(frac, "Value"), c2=6.2831853, x=-1080, y=-40, label="angle")
cx = g.math("COSINE", a=(ang, "Value"), x=-920, y=60)
sy = g.math("SINE", a=(ang, "Value"), x=-920, y=-140)
px = g.math("MULTIPLY", a=(cx, "Value"), x=-760, y=60, label="x")
g.l(gin, "Radius", px, 1)
py = g.math("MULTIPLY", a=(sy, "Value"), x=-760, y=-140, label="y")
g.l(gin, "Radius", py, 1)
posv = g.n("ShaderNodeCombineXYZ", "Pos", x=-600, y=-20)
g.l(px, "Value", posv, "X")
g.l(py, "Value", posv, "Y")
setpos = g.n("GeometryNodeSetPosition", "Place", x=-440, y=200)
g.l(pts, "Points", setpos, "Geometry")
g.l(posv, "Vector", setpos, "Position")

# ---- upright stone instance ------------------------------------------
stone = g.n("GeometryNodeMeshCube", "Stone", inputs={"Size": (0.55, 0.55, 2.4)}, x=-600, y=460)
stoneb = g.n("GeometryNodeTransform", "StoneBase", inputs={"Translation": (0, 0, 1.2)}, x=-440, y=460)
g.l(stone, "Mesh", stoneb, "Geometry")
inst = g.n("GeometryNodeInstanceOnPoints", "Stones", x=-240, y=200)
g.l(setpos, "Geometry", inst, "Points")
g.l(stoneb, "Geometry", inst, "Instance")

# ---- proximity -> scale (near small, far full) -----------------------
objinfo = g.n("GeometryNodeObjectInfo", "Controller", {"transform_space": "RELATIVE"},
              x=-1080, y=-360)
try:
    objinfo.inputs["Object"].default_value = ctrl
except Exception as e:
    P("controller ref: %s" % e)
pos2 = g.n("GeometryNodeInputPosition", "PtPos", x=-1080, y=-520)
dvec = g.n("ShaderNodeVectorMath", "ToCtl", {"operation": "SUBTRACT"}, x=-900, y=-440)
g.l(pos2, "Position", dvec, 0)
g.l(objinfo, "Location", dvec, 1)
distc = g.n("ShaderNodeVectorMath", "Dist", {"operation": "LENGTH"}, x=-740, y=-440)
g.l(dvec, "Vector", distc, 0)
factor = g.n("ShaderNodeMapRange", "Prox", {"interpolation_type": "SMOOTHSTEP"},
             inputs={1: 0.3, 4: 1.0}, x=-560, y=-440)   # 2:from_max, 3:to_min set below
g.l(distc, "Value", factor, "Value")
g.l(gin, "Influence Radius", factor, 2)
g.l(gin, "Near Scale", factor, 3)
svec = g.n("ShaderNodeCombineXYZ", "SVec", x=-360, y=-440)
g.l(factor, "Result", svec, "X")
g.l(factor, "Result", svec, "Y")
g.l(factor, "Result", svec, "Z")
scal = g.n("GeometryNodeScaleInstances", "ProxScale", x=100, y=200)
g.l(inst, "Instances", scal, "Instances")
g.l(svec, "Vector", scal, "Scale")
g.l(scal, "Instances", gout, "Geometry")

# ---- host object -----------------------------------------------------
obj = bpy.data.objects.get("ProxRing_Demo")
if obj is None:
    bpy.ops.mesh.primitive_plane_add(size=1, location=(90, 0, 0))
    obj = bpy.context.active_object
    obj.name = "ProxRing_Demo"
for m in list(obj.modifiers):
    obj.modifiers.remove(m)
obj.modifiers.new("ProxRing", "NODES").node_group = ng

print("PROXRING BUILD:", "OK" if not PROBLEMS else "PROBLEMS")
for p in PROBLEMS:
    print("  ", p)
print("nodes:", len(ng.nodes), "controller:", CTRL_NAME, "at", tuple(ctrl.location))
