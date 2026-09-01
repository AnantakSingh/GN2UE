import bpy

# ---------- helpers ----------
def get_in(node, ident):
    for s in node.inputs:
        if s.identifier == ident:
            return s
    for s in node.inputs:
        if s.name == ident and s.enabled:
            return s
    raise KeyError(f"{node.name}: no input '{ident}' (have: {[s.identifier for s in node.inputs]})")

def get_out(node, ident):
    for s in node.outputs:
        if s.identifier == ident:
            return s
    for s in node.outputs:
        if s.name == ident and s.enabled:
            return s
    raise KeyError(f"{node.name}: no output '{ident}' (have: {[s.identifier for s in node.outputs]})")

# ---------- clean up previous runs ----------
if "SpineTree" in bpy.data.objects:
    bpy.data.objects.remove(bpy.data.objects["SpineTree"], do_unlink=True)
if "SpineTreeGN" in bpy.data.node_groups:
    bpy.data.node_groups.remove(bpy.data.node_groups["SpineTreeGN"])

# ---------- object + modifier ----------
mesh = bpy.data.meshes.new("SpineTreeMesh")
obj = bpy.data.objects.new("SpineTree", mesh)
bpy.context.scene.collection.objects.link(obj)

ng = bpy.data.node_groups.new("SpineTreeGN", "GeometryNodeTree")
mod = obj.modifiers.new("SpineTreeGN", "NODES")
mod.node_group = ng

# ---------- group interface ----------
ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")

def int_in(name, default, mn, mx):
    s = ng.interface.new_socket(name, in_out="INPUT", socket_type="NodeSocketInt")
    s.default_value = default; s.min_value = mn; s.max_value = mx
    return s

def float_in(name, default, mn, mx):
    s = ng.interface.new_socket(name, in_out="INPUT", socket_type="NodeSocketFloat")
    s.default_value = default; s.min_value = mn; s.max_value = mx
    return s

int_in("Seed", 0, 0, 10000)
int_in("Spine Segments", 12, 2, 100)
float_in("Wander", 0.5, 0.0, 3.0)
int_in("Cube Count", 10, 1, 200)
float_in("Cube Thickness", 0.22, 0.01, 2.0)
float_in("Cube Length", 0.85, 0.05, 5.0)
int_in("Leaf Points", 48, 1, 500)
float_in("Leaf Probability", 0.35, 0.0, 1.0)
float_in("Leaf Size", 0.6, 0.05, 3.0)

nodes, links = ng.nodes, ng.links
def N(t, x, y, **props):
    n = nodes.new(t)
    n.location = (x, y)
    for k, v in props.items():
        setattr(n, k, v)
    return n

gin = N("NodeGroupInput", -1400, 0)
gout = N("NodeGroupOutput", 1500, 0)

# ---------- spine: upward random walk ----------
line = N("GeometryNodeMeshLine", -1100, 300, mode="OFFSET")
get_in(line, "Offset").default_value = (0.0, 0.0, 0.6)
links.new(gin.outputs["Spine Segments"], get_in(line, "Count"))

rand_walk = N("FunctionNodeRandomValue", -1100, 60, data_type="FLOAT_VECTOR")
get_in(rand_walk, "Max").default_value = (1.0, 1.0, 0.25)
links.new(gin.outputs["Seed"], get_in(rand_walk, "Seed"))
# min = -max*wander asymmetric: instead scale symmetric noise by Wander
wander_min = N("ShaderNodeVectorMath", -1250, -80, operation="SCALE")
wander_min.inputs[0].default_value = (-1.0, -1.0, -0.1)
links.new(gin.outputs["Wander"], get_in(wander_min, "Scale"))
links.new(wander_min.outputs["Vector"], get_in(rand_walk, "Min"))
wander_max = N("ShaderNodeVectorMath", -1250, -220, operation="SCALE")
wander_max.inputs[0].default_value = (1.0, 1.0, 0.4)
links.new(gin.outputs["Wander"], get_in(wander_max, "Scale"))
links.new(wander_max.outputs["Vector"], get_in(rand_walk, "Max"))

accum = N("GeometryNodeAccumulateField", -850, 60, data_type="FLOAT_VECTOR", domain="POINT")
links.new(get_out(rand_walk, "Value"), get_in(accum, "Value"))

set_pos = N("GeometryNodeSetPosition", -650, 300)
links.new(line.outputs["Mesh"], get_in(set_pos, "Geometry"))
links.new(get_out(accum, "Leading"), get_in(set_pos, "Offset"))

to_curve = N("GeometryNodeMeshToCurve", -450, 300)
links.new(set_pos.outputs["Geometry"], get_in(to_curve, "Mesh"))

spline_type = N("GeometryNodeCurveSplineType", -280, 300, spline_type="CATMULL_ROM")
links.new(to_curve.outputs["Curve"], get_in(spline_type, "Curve"))

smooth = N("GeometryNodeResampleCurve", -100, 300)
get_in(smooth, "Count").default_value = 128
links.new(spline_type.outputs["Curve"], get_in(smooth, "Curve"))

# ---------- cubes along the spine ----------
cube_resample = N("GeometryNodeResampleCurve", 150, 500)
links.new(smooth.outputs["Curve"], get_in(cube_resample, "Curve"))
links.new(gin.outputs["Cube Count"], get_in(cube_resample, "Count"))

cube_pts = N("GeometryNodeCurveToPoints", 350, 500, mode="EVALUATED")
links.new(cube_resample.outputs["Curve"], get_in(cube_pts, "Curve"))

cube = N("GeometryNodeMeshCube", 150, 250)
get_in(cube, "Size").default_value = (1.0, 1.0, 1.0)

subdiv = N("GeometryNodeSubdivideMesh", 350, 250)
get_in(subdiv, "Level").default_value = 2
links.new(cube.outputs["Mesh"], get_in(subdiv, "Mesh"))

cube_scale = N("ShaderNodeCombineXYZ", 350, 100)
links.new(gin.outputs["Cube Thickness"], get_in(cube_scale, "X"))
links.new(gin.outputs["Cube Thickness"], get_in(cube_scale, "Y"))
links.new(gin.outputs["Cube Length"], get_in(cube_scale, "Z"))

cube_inst = N("GeometryNodeInstanceOnPoints", 620, 400)
links.new(cube_pts.outputs["Points"], get_in(cube_inst, "Points"))
links.new(subdiv.outputs["Mesh"], get_in(cube_inst, "Instance"))
links.new(cube_pts.outputs["Rotation"], get_in(cube_inst, "Rotation"))
links.new(cube_scale.outputs["Vector"], get_in(cube_inst, "Scale"))

# ---------- leaves ----------
leaf_resample = N("GeometryNodeResampleCurve", 150, -200)
links.new(smooth.outputs["Curve"], get_in(leaf_resample, "Curve"))
links.new(gin.outputs["Leaf Points"], get_in(leaf_resample, "Count"))

leaf_pts = N("GeometryNodeCurveToPoints", 350, -200, mode="EVALUATED")
links.new(leaf_resample.outputs["Curve"], get_in(leaf_pts, "Curve"))

seed1 = N("ShaderNodeMath", 150, -420, operation="ADD")
seed1.inputs[1].default_value = 1.0
links.new(gin.outputs["Seed"], seed1.inputs[0])
seed2 = N("ShaderNodeMath", 150, -580, operation="ADD")
seed2.inputs[1].default_value = 2.0
links.new(gin.outputs["Seed"], seed2.inputs[0])

leaf_select = N("FunctionNodeRandomValue", 380, -420, data_type="BOOLEAN")
links.new(gin.outputs["Leaf Probability"], get_in(leaf_select, "Probability"))
links.new(seed1.outputs["Value"], get_in(leaf_select, "Seed"))

leaf_angle = N("FunctionNodeRandomValue", 380, -620, data_type="FLOAT")
get_in(leaf_angle, "Max").default_value = 6.2832
links.new(seed2.outputs["Value"], get_in(leaf_angle, "Seed"))

leaf_rot = N("ShaderNodeCombineXYZ", 580, -620)
links.new(get_out(leaf_angle, "Value"), get_in(leaf_rot, "Z"))

# flat plane (lies in XY = horizontal), elongated outward along X
leaf_width = N("ShaderNodeMath", 150, -750, operation="MULTIPLY")
leaf_width.inputs[1].default_value = 0.33
links.new(gin.outputs["Leaf Size"], leaf_width.inputs[0])

leaf_plane = N("GeometryNodeMeshGrid", 380, -800)
get_in(leaf_plane, "Vertices X").default_value = 2
get_in(leaf_plane, "Vertices Y").default_value = 2
links.new(gin.outputs["Leaf Size"], get_in(leaf_plane, "Size X"))
links.new(leaf_width.outputs["Value"], get_in(leaf_plane, "Size Y"))

leaf_inst = N("GeometryNodeInstanceOnPoints", 620, -300)
links.new(leaf_pts.outputs["Points"], get_in(leaf_inst, "Points"))
links.new(get_out(leaf_select, "Value"), get_in(leaf_inst, "Selection"))
links.new(leaf_plane.outputs["Mesh"], get_in(leaf_inst, "Instance"))
links.new(leaf_rot.outputs["Vector"], get_in(leaf_inst, "Rotation"))

# push each leaf outward along its own (rotated) X axis so it sticks out of the spine
leaf_offset = N("ShaderNodeMath", 620, -550, operation="MULTIPLY")
leaf_offset.inputs[1].default_value = 0.55
links.new(gin.outputs["Leaf Size"], leaf_offset.inputs[0])
leaf_offset_vec = N("ShaderNodeCombineXYZ", 800, -550)
links.new(leaf_offset.outputs["Value"], get_in(leaf_offset_vec, "X"))

leaf_translate = N("GeometryNodeTranslateInstances", 900, -300)
links.new(leaf_inst.outputs["Instances"], get_in(leaf_translate, "Instances"))
links.new(leaf_offset_vec.outputs["Vector"], get_in(leaf_translate, "Translation"))
get_in(leaf_translate, "Local Space").default_value = True

# ---------- join + output ----------
join = N("GeometryNodeJoinGeometry", 1200, 100)
links.new(leaf_translate.outputs["Instances"], get_in(join, "Geometry"))
links.new(cube_inst.outputs["Instances"], get_in(join, "Geometry"))
links.new(join.outputs["Geometry"], gout.inputs["Geometry"])

# Blender 5.2: modifier input values are created as 0 when the interface is
# built after node-group assignment — sync them to the interface defaults.
for item in ng.interface.items_tree:
    if item.item_type == "SOCKET" and item.in_out == "INPUT" and item.socket_type != "NodeSocketGeometry":
        mod.properties.inputs[item.identifier]["value"] = item.default_value

obj.update_tag()
bpy.context.view_layer.update()
obj.select_set(True)
bpy.context.view_layer.objects.active = obj
print("OK: built", obj.name, "with node group", ng.name, "| nodes:", len(nodes))
