import bpy
import traceback
import os

try:
    def get_or_create_node_group(name="Card_Spring_Setup"):
        # Create a fresh group, deleting old one if it exists
        if name in bpy.data.node_groups:
            bpy.data.node_groups.remove(bpy.data.node_groups[name])
        group = bpy.data.node_groups.new(name=name, type="GeometryNodeTree")
        
        # CRITICAL FIX for Blender 4.0+: Mark tree as a modifier so it appears in the dropdown!
        if hasattr(group, 'is_modifier'):
            group.is_modifier = True
            
        return group

    def create_socket(group, name, in_out, socket_type, default_value=None):
        if hasattr(group, "interface"):
            sock = group.interface.new_socket(name=name, in_out=in_out, socket_type=socket_type)
            if default_value is not None:
                sock.default_value = default_value
            return sock
        else:
            if in_out == 'INPUT':
                sock = group.inputs.new(socket_type, name)
                if default_value is not None:
                    sock.default_value = default_value
                return sock
            else:
                return group.outputs.new(socket_type, name)

    group = get_or_create_node_group()

    group_in = group.nodes.new("NodeGroupInput")
    group_in.location = (-1200, 0)
    group_out = group.nodes.new("NodeGroupOutput")
    group_out.location = (2000, 0)

    create_socket(group, "Geometry", "INPUT", "NodeSocketGeometry")
    create_socket(group, "Spring Progress", "INPUT", "NodeSocketFloat", 0.0)
    create_socket(group, "Card Spacing", "INPUT", "NodeSocketFloat", 0.015)
    create_socket(group, "Flight Speed", "INPUT", "NodeSocketFloat", 0.3)
    create_socket(group, "Unbend Point", "INPUT", "NodeSocketFloat", 0.1)
    create_socket(group, "Max Bend", "INPUT", "NodeSocketFloat", 5.0)
    create_socket(group, "Card Base Rotation", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    create_socket(group, "Geometry", "OUTPUT", "NodeSocketGeometry")

    def add_node(node_type, location, name=None):
        try:
            node = group.nodes.new(node_type)
        except:
            fallbacks = {
                "FunctionNodeAlignRotationToVector": "FunctionNodeAlignEulerToVector",
                "FunctionNodeRotateRotation": "FunctionNodeRotateEuler",
                "ShaderNodeMix": "ShaderNodeMixRGB"
            }
            node = group.nodes.new(fallbacks.get(node_type, node_type))
        node.location = location
        if name:
            node.label = name
        return node

    def link_sockets(out_node, out_id, in_node, in_id):
        try:
            out_s = out_node.outputs.get(out_id) if isinstance(out_id, str) else out_node.outputs[out_id]
            if out_s is None: out_s = out_node.outputs[0]
            
            in_s = in_node.inputs.get(in_id) if isinstance(in_id, str) else in_node.inputs[in_id]
            if in_s is None:
                for inp in in_node.inputs:
                    if str(in_id).lower() in inp.name.lower():
                        in_s = inp
                        break
            if in_s is None: in_s = in_node.inputs[0]
            
            group.links.new(out_s, in_s)
        except Exception as e:
            pass

    # Block A
    obj_source = add_node("GeometryNodeObjectInfo", (-1000, 600), "HandSource (Select Here)")
    obj_source.transform_space = 'RELATIVE'
    obj_target = add_node("GeometryNodeObjectInfo", (-1000, 450), "HandTarget (Select Here)")
    obj_target.transform_space = 'RELATIVE'

    mix_vec = add_node("ShaderNodeMix", (-800, 500))
    if hasattr(mix_vec, 'data_type'): mix_vec.data_type = 'VECTOR'
    if len(mix_vec.inputs) > 0: mix_vec.inputs[0].default_value = 0.5 

    add_arc = add_node("ShaderNodeVectorMath", (-600, 500))
    add_arc.operation = 'ADD'
    add_arc.inputs[1].default_value = (0, 0, 0.1)

    bezier = add_node("GeometryNodeCurveQuadraticBezier", (-400, 500))

    link_sockets(obj_source, "Location", mix_vec, "A" if "A" in mix_vec.inputs else 4)
    link_sockets(obj_target, "Location", mix_vec, "B" if "B" in mix_vec.inputs else 5)
    link_sockets(mix_vec, "Result" if "Result" in mix_vec.outputs else 0, add_arc, 0)
    link_sockets(obj_source, "Location", bezier, "Start")
    link_sockets(add_arc, "Vector", bezier, "Middle")
    link_sockets(obj_target, "Location", bezier, "End")

    # Block B
    mesh_line = add_node("GeometryNodeMeshLine", (-1000, 200))
    mesh_line.inputs["Count"].default_value = 52
    mesh_line.inputs["Offset"].default_value = (0, 0, 0.0005)

    capture_idx = add_node("GeometryNodeCaptureAttribute", (-800, 200))
    capture_idx.domain = 'POINT'
    if hasattr(capture_idx, 'data_type'): capture_idx.data_type = 'INT'

    inst_points = add_node("GeometryNodeInstanceOnPoints", (-600, 200))
    realize = add_node("GeometryNodeRealizeInstances", (-400, 200))
    set_pos = add_node("GeometryNodeSetPosition", (1600, 200))

    link_sockets(mesh_line, "Mesh", capture_idx, "Geometry")
    link_sockets(capture_idx, "Geometry", inst_points, "Points")
    link_sockets(inst_points, "Instances", realize, "Geometry")
    link_sockets(realize, "Geometry", set_pos, "Geometry")
    link_sockets(set_pos, "Geometry", group_out, "Geometry")

    # Block C
    obj_card = add_node("GeometryNodeObjectInfo", (-1000, 0), "Card Instance (Select Here)")
    obj_card.transform_space = 'RELATIVE'
    if "As Instance" in obj_card.inputs:
        obj_card.inputs["As Instance"].default_value = True

    idx_node = add_node("GeometryNodeInputIndex", (-1000, 100))

    link_sockets(obj_card, "Geometry", inst_points, "Instance")
    link_sockets(idx_node, "Index", capture_idx, "Value")

    # Block D
    mul_spc = add_node("ShaderNodeMath", (-600, -200))
    mul_spc.operation = 'MULTIPLY'
    add_spd = add_node("ShaderNodeMath", (-400, -200))
    add_spd.operation = 'ADD'
    map_fac = add_node("ShaderNodeMapRange", (-200, -200))
    map_fac.clamp = True
    map_fac.inputs["To Min"].default_value = 0.0
    map_fac.inputs["To Max"].default_value = 1.0

    attr_out = "Attribute" if "Attribute" in capture_idx.outputs else 1
    link_sockets(capture_idx, attr_out, mul_spc, 0)
    link_sockets(group_in, "Card Spacing", mul_spc, 1)

    link_sockets(mul_spc, "Value", add_spd, 0)
    link_sockets(group_in, "Flight Speed", add_spd, 1)

    link_sockets(group_in, "Spring Progress", map_fac, "Value")
    link_sockets(mul_spc, "Value", map_fac, "From Min")
    link_sockets(add_spd, "Value", map_fac, "From Max")

    # Block E
    map_bend = add_node("ShaderNodeMapRange", (200, -400))
    map_bend.inputs["From Min"].default_value = 0.0
    map_bend.inputs["To Max"].default_value = 0.0

    link_sockets(map_fac, "Result", map_bend, "Value")
    link_sockets(group_in, "Unbend Point", map_bend, "From Max")
    link_sockets(group_in, "Max Bend", map_bend, "To Min")

    pos_node = add_node("GeometryNodeInputPosition", (200, -600))
    dot_prod = add_node("ShaderNodeVectorMath", (400, -600))
    dot_prod.operation = 'DOT_PRODUCT'
    dot_prod.inputs[1].default_value = (-0.707, 0.707, 0.0)
    link_sockets(pos_node, "Position", dot_prod, 0)

    mul_sq = add_node("ShaderNodeMath", (600, -600))
    mul_sq.operation = 'MULTIPLY'
    link_sockets(dot_prod, "Value", mul_sq, 0)
    link_sockets(dot_prod, "Value", mul_sq, 1)

    mul_bend = add_node("ShaderNodeMath", (800, -600))
    mul_bend.operation = 'MULTIPLY'
    link_sockets(mul_sq, "Value", mul_bend, 0)
    link_sockets(map_bend, "Result", mul_bend, 1)

    comb_z = add_node("ShaderNodeCombineXYZ", (1000, -600))
    link_sockets(mul_bend, "Value", comb_z, "Z")

    add_bent = add_node("ShaderNodeVectorMath", (1200, -600))
    add_bent.operation = 'ADD'
    link_sockets(pos_node, "Position", add_bent, 0)
    link_sockets(comb_z, "Vector", add_bent, 1)

    # Block F
    samp_curve = add_node("GeometryNodeSampleCurve", (200, 400))
    link_sockets(bezier, "Curve", samp_curve, "Curve")
    link_sockets(map_fac, "Result", samp_curve, "Factor")

    align_z = add_node("FunctionNodeAlignRotationToVector", (400, 300))
    align_z.axis = 'Z'
    align_z.pivot_axis = 'AUTO'
    link_sockets(samp_curve, "Normal", align_z, "Vector")

    align_x = add_node("FunctionNodeAlignRotationToVector", (600, 300))
    align_x.axis = 'X'
    align_x.pivot_axis = 'Z'
    link_sockets(align_z, "Rotation", align_x, "Rotation")
    link_sockets(samp_curve, "Tangent", align_x, "Vector")

    rot_rot = add_node("FunctionNodeRotateRotation", (800, 300))
    if hasattr(rot_rot, 'space'): rot_rot.space = 'LOCAL'
    link_sockets(align_x, "Rotation", rot_rot, 0) 
    link_sockets(group_in, "Card Base Rotation", rot_rot, 1) 

    vec_rot = add_node("ShaderNodeVectorRotate", (1000, 300))
    try:
        vec_rot.rotation_type = 'EULER_XYZ'
    except TypeError:
        vec_rot.rotation_type = 'EULER'
    link_sockets(add_bent, "Vector", vec_rot, "Vector")
    link_sockets(rot_rot, 0, vec_rot, "Rotation")

    add_fin = add_node("ShaderNodeVectorMath", (1200, 300))
    add_fin.operation = 'ADD'
    link_sockets(vec_rot, "Vector", add_fin, 0)
    link_sockets(samp_curve, "Position", add_fin, 1)

    link_sockets(add_fin, "Vector", set_pos, "Position")

    import tempfile
    error_path = os.path.join(os.path.dirname(bpy.data.filepath), "blender_error.txt") if bpy.data.filepath else os.path.join(tempfile.gettempdir(), "blender_error.txt")
    with open(error_path, "w") as f:
        f.write("SUCCESS")
except Exception as e:
    import tempfile
    error_path = os.path.join(os.path.dirname(bpy.data.filepath), "blender_error.txt") if bpy.data.filepath else os.path.join(tempfile.gettempdir(), "blender_error.txt")
    with open(error_path, "w") as f:
        f.write(traceback.format_exc())
