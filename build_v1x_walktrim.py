"""WalkTrim_Test — V1.x test effect: accumulate (random walk) + trim curve.

Points -> Set Position(offset = Accumulate(Random vec, leading)) -> Points to
Curves -> Catmull -> Trim Curve(Start/End params) -> Curve to Points -> cubes.
Exercises the new kernel series machinery and arc-length trim end to end.
"""
import bpy

GROUP_NAME = "WalkTrim_Test"
PROBLEMS = []


def P(msg):
    PROBLEMS.append(msg)
    print("PROBLEM:", msg)


def fresh_group():
    old = bpy.data.node_groups.get(GROUP_NAME)
    if old:
        bpy.data.node_groups.remove(old)
    return bpy.data.node_groups.new(GROUP_NAME, "GeometryNodeTree")


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


ng = fresh_group()
g = G(ng)
sock(ng, "Geometry", "INPUT", "NodeSocketGeometry")
sock(ng, "Steps", "INPUT", "NodeSocketInt", 24)
sock(ng, "Trim Start", "INPUT", "NodeSocketFloat", 0.1)
sock(ng, "Trim End", "INPUT", "NodeSocketFloat", 0.85)
sock(ng, "Cubes", "INPUT", "NodeSocketInt", 20)
sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
sock(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")

gin = g.n("NodeGroupInput", "Params", x=-1500)
gout = g.n("NodeGroupOutput", "Out", x=900)

pts = g.n("GeometryNodePoints", "WalkPts", x=-1200, y=200)
g.l(gin, "Steps", pts, "Count")

step = g.n("FunctionNodeRandomValue", "Step", {"data_type": "FLOAT_VECTOR"},
           {"Min": (-0.5, -0.5, 0.15), "Max": (0.5, 0.5, 0.55)}, x=-1200, y=0)
g.l(gin, "Seed", step, "Seed")
acc = g.n("GeometryNodeAccumulateField", "Walk",
          {"data_type": "FLOAT_VECTOR", "domain": "POINT"}, x=-1000, y=0)
g.l(step, "Value", acc, "Value")
walk = g.n("GeometryNodeSetPosition", "ApplyWalk", x=-800, y=200)
g.l(pts, "Points", walk, "Geometry")
g.l(acc, "Leading", walk, "Offset")

crv = g.n("GeometryNodePointsToCurves", "ToCurve", x=-600, y=200)
g.l(walk, "Geometry", crv, "Points")
smooth = g.n("GeometryNodeCurveSplineType", "Catmull", {"spline_type": "CATMULL_ROM"},
             x=-440, y=200)
g.l(crv, "Curves", smooth, "Curve")

trim = g.n("GeometryNodeTrimCurve", "Trim", {"mode": "FACTOR"}, x=-280, y=200)
g.l(smooth, "Curve", trim, "Curve")
g.l(gin, "Trim Start", trim, "Start")
g.l(gin, "Trim End", trim, "End")

topts = g.n("GeometryNodeCurveToPoints", "Samples", {"mode": "COUNT"}, x=-100, y=200)
g.l(trim, "Curve", topts, "Curve")
g.l(gin, "Cubes", topts, "Count")

cube = g.n("GeometryNodeMeshCube", "Cube", inputs={"Size": (0.18, 0.18, 0.18)}, x=-100, y=0)
inst = g.n("GeometryNodeInstanceOnPoints", "Cubes", x=100, y=200)
g.l(topts, "Points", inst, "Points")
g.l(cube, "Mesh", inst, "Instance")
g.l(topts, "Rotation", inst, "Rotation")

join = g.n("GeometryNodeJoinGeometry", "OutJoin", x=600, y=200)
g.l(inst, "Instances", join, "Geometry")
try:
    g.ng.links.new(gin.outputs["Geometry"], join.inputs["Geometry"])
except Exception as e:
    P("join input: %s" % e)
g.l(join, "Geometry", gout, "Geometry")

obj = bpy.data.objects.get("V1xWalkTrim_Demo")
if obj is None:
    bpy.ops.mesh.primitive_plane_add(size=2, location=(75, 0, 0))
    obj = bpy.context.active_object
    obj.name = "V1xWalkTrim_Demo"
for m in list(obj.modifiers):
    obj.modifiers.remove(m)
obj.modifiers.new("WalkTrim", "NODES").node_group = ng
bpy.context.view_layer.update()
print("BUILD DONE: %s nodes=%d problems=%d" % (ng.name, len(ng.nodes), len(PROBLEMS)))
for p in PROBLEMS:
    print("  P:", p)
