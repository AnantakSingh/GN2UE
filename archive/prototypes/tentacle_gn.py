"""
Procedural Tentacle Geometry Nodes builder  (Blender 5.1)
---------------------------------------------------------
Spawns tentacles from a cube. Roots are distributed on the cube surface, each
given a noise-driven outward direction. A Repeat Zone iteratively grows limbs:
every iteration spawns one more limb segment on each growth tip (a stretched,
subdivided, tapered cube), curls the direction using a noise field, tapers the
radius, and at chosen iterations branches (duplicates tips) so the number of
limbs increases progressively.

Exposed modifier inputs (reflected by the GN->UE bridge):
  Segments, Segment Length, Thickness, Taper, Bend Strength,
  Noise Scale, Root Density, Seed, Branch

Writes:
  <this folder>\\tentacle.blend
  <this folder>\\tentacle_status.txt   (SUCCESS / ERROR + traceback)
"""

import bpy
import os
import traceback

OUT_DIR = (os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals()
           else os.getcwd())   # archived: writes next to itself
STATUS = os.path.join(OUT_DIR, "tentacle_status.txt")


def write_status(msg):
    try:
        with open(STATUS, "w") as f:
            f.write(msg)
    except Exception:
        pass


try:
    NG_NAME = "Tentacle_Growth"
    if NG_NAME in bpy.data.node_groups:
        bpy.data.node_groups.remove(bpy.data.node_groups[NG_NAME])

    ng = bpy.data.node_groups.new(NG_NAME, "GeometryNodeTree")
    if hasattr(ng, "is_modifier"):
        ng.is_modifier = True
    nodes = ng.nodes
    links = ng.links

    # ---------------- helpers ----------------
    def iface(name, in_out, stype, default=None, minv=None, maxv=None):
        s = ng.interface.new_socket(name=name, in_out=in_out, socket_type=stype)
        if default is not None:
            try:
                s.default_value = default
            except Exception:
                pass
        if minv is not None:
            try:
                s.min_value = minv
            except Exception:
                pass
        if maxv is not None:
            try:
                s.max_value = maxv
            except Exception:
                pass
        return s

    def add(idname, loc=(0, 0), label=None, **props):
        try:
            n = nodes.new(idname)
        except RuntimeError:
            fb = {"FunctionNodeAlignRotationToVector": "FunctionNodeAlignEulerToVector"}
            n = nodes.new(fb.get(idname, idname))
        n.location = loc
        if label:
            n.label = label
        for k, v in props.items():
            try:
                setattr(n, k, v)
            except Exception:
                pass
        return n

    def _find_in(n, key):
        s = None
        try:
            s = n.inputs.get(key) if isinstance(key, str) else n.inputs[key]
        except Exception:
            s = None
        if s is None and isinstance(key, str):
            for i in n.inputs:
                if key.lower() in i.name.lower():
                    s = i
                    break
        if s is None:
            s = n.inputs[0]
        return s

    def _find_out(n, key):
        s = None
        try:
            s = n.outputs.get(key) if isinstance(key, str) else n.outputs[key]
        except Exception:
            s = None
        if s is None and isinstance(key, str):
            for o in n.outputs:
                if key.lower() in o.name.lower():
                    s = o
                    break
        if s is None:
            s = n.outputs[0]
        return s

    def link(a, aout, b, bin):
        return links.new(_find_out(a, aout), _find_in(b, bin))

    def setin(n, key, val):
        try:
            _find_in(n, key).default_value = val
        except Exception:
            pass

    def link_value(store, a, aout):
        """Link into the currently-enabled 'Value' socket of a StoreNamedAttribute."""
        target = None
        for i in store.inputs:
            if i.name == "Value" and getattr(i, "enabled", True):
                target = i
                break
        if target is None:
            for i in store.inputs:
                if i.name == "Value":
                    target = i
                    break
        return links.new(_find_out(a, aout), target)

    # ---------------- interface ----------------
    iface("Geometry", "INPUT", "NodeSocketGeometry")
    iface("Segments", "INPUT", "NodeSocketInt", 8, 1, 20)
    iface("Segment Length", "INPUT", "NodeSocketFloat", 0.25, 0.0)
    iface("Thickness", "INPUT", "NodeSocketFloat", 0.09, 0.0)
    iface("Taper", "INPUT", "NodeSocketFloat", 0.82, 0.0, 1.0)
    iface("Bend Strength", "INPUT", "NodeSocketFloat", 0.6, 0.0)
    iface("Noise Scale", "INPUT", "NodeSocketFloat", 1.5, 0.0)
    iface("Root Density", "INPUT", "NodeSocketFloat", 12.0, 0.0)
    iface("Seed", "INPUT", "NodeSocketInt", 0)
    iface("Branch", "INPUT", "NodeSocketBool", True)
    iface("Geometry", "OUTPUT", "NodeSocketGeometry")

    gin = add("NodeGroupInput", (-1500, 0))
    gout = add("NodeGroupOutput", (2600, 0))

    # ---------------- LIMB PROTOTYPE (stretched, subdivided, tapered cube) ----------------
    cube = add("GeometryNodeMeshCube", (-1500, -520), "Limb base cube")
    setin(cube, "Size", (1.0, 1.0, 1.0))
    xf = add("GeometryNodeTransform", (-1320, -520), "Stretch to 0..1 Z")
    setin(xf, "Translation", (0.0, 0.0, 0.5))
    link(cube, "Mesh", xf, "Geometry")
    subd = add("GeometryNodeSubdivideMesh", (-1140, -520), "Subdivide (bendable)")
    setin(subd, "Level", 4)
    link(xf, "Geometry", subd, "Mesh")

    pos_p = add("GeometryNodeInputPosition", (-1140, -720))
    sep = add("ShaderNodeSeparateXYZ", (-960, -720))
    link(pos_p, "Position", sep, "Vector")
    tfac = add("ShaderNodeMath", (-780, -760), "1 - Z*0.8", operation="MULTIPLY_ADD")
    setin(tfac, 1, -0.8)
    setin(tfac, 2, 1.0)
    link(sep, "Z", tfac, 0)
    mulx = add("ShaderNodeMath", (-600, -680), operation="MULTIPLY")
    link(sep, "X", mulx, 0)
    link(tfac, "Value", mulx, 1)
    muly = add("ShaderNodeMath", (-600, -820), operation="MULTIPLY")
    link(sep, "Y", muly, 0)
    link(tfac, "Value", muly, 1)
    comb = add("ShaderNodeCombineXYZ", (-420, -740))
    link(mulx, "Value", comb, "X")
    link(muly, "Value", comb, "Y")
    link(sep, "Z", comb, "Z")
    proto = add("GeometryNodeSetPosition", (-240, -520), "Taper cube")
    link(subd, "Mesh", proto, "Geometry")
    link(comb, "Vector", proto, "Position")

    # ---------------- ROOTS on cube ----------------
    dist = add("GeometryNodeDistributePointsOnFaces", (-1150, 320), "Root points",
               distribute_method='RANDOM')
    link(gin, "Geometry", dist, "Mesh")
    link(gin, "Root Density", dist, "Density")
    link(gin, "Seed", dist, "Seed")

    pos_r = add("GeometryNodeInputPosition", (-1150, 120))
    nsc0 = add("ShaderNodeVectorMath", (-980, 120), "pos * noise scale", operation="SCALE")
    link(pos_r, "Position", nsc0, 0)
    link(gin, "Noise Scale", nsc0, "Scale")
    noise0 = add("ShaderNodeTexNoise", (-800, 120), "Dir noise", noise_dimensions='3D')
    link(nsc0, "Vector", noise0, "Vector")
    ctr0 = add("ShaderNodeVectorMath", (-620, 120), "center to [-.5,.5]", operation="SUBTRACT")
    link(noise0, "Color", ctr0, 0)
    setin(ctr0, 1, (0.5, 0.5, 0.5))
    dirmix = add("ShaderNodeVectorMath", (-440, 200), "noise + face normal", operation="ADD")
    link(ctr0, "Vector", dirmix, 0)
    link(dist, "Normal", dirmix, 1)
    dnorm = add("ShaderNodeVectorMath", (-260, 200), operation="NORMALIZE")
    link(dirmix, "Vector", dnorm, 0)

    st_dir0 = add("GeometryNodeStoreNamedAttribute", (-80, 320), "store dir",
                  data_type='FLOAT_VECTOR', domain='POINT')
    setin(st_dir0, "Name", "dir")
    link(dist, "Points", st_dir0, "Geometry")
    link_value(st_dir0, dnorm, "Vector")
    st_rad0 = add("GeometryNodeStoreNamedAttribute", (120, 320), "store radius",
                  data_type='FLOAT', domain='POINT')
    setin(st_rad0, "Name", "radius")
    link(st_dir0, "Geometry", st_rad0, "Geometry")
    link_value(st_rad0, gin, "Thickness")

    # ---------------- REPEAT ZONE: iterative limb spawning ----------------
    rin = add("GeometryNodeRepeatInput", (320, 0))
    rout = add("GeometryNodeRepeatOutput", (2000, 0))
    rin.pair_with_output(rout)
    rout.repeat_items.clear()
    for stype, nm in [("GEOMETRY", "Skeleton"), ("GEOMETRY", "Tips"),
                       ("GEOMETRY", "Limb"), ("FLOAT", "SegLen"),
                       ("FLOAT", "Taper"), ("FLOAT", "BendStr"),
                       ("FLOAT", "NoiseScale"), ("BOOLEAN", "DoBranch"),
                       ("INT", "Iter")]:
        rout.repeat_items.new(stype, nm)

    link(gin, "Segments", rin, "Iterations")
    empty = add("GeometryNodeJoinGeometry", (150, -80), "empty (init skeleton)")
    link(empty, "Geometry", rin, "Skeleton")
    link(st_rad0, "Geometry", rin, "Tips")
    link(proto, "Geometry", rin, "Limb")
    link(gin, "Segment Length", rin, "SegLen")
    link(gin, "Taper", rin, "Taper")
    link(gin, "Bend Strength", rin, "BendStr")
    link(gin, "Noise Scale", rin, "NoiseScale")
    link(gin, "Branch", rin, "DoBranch")
    setin(rin, "Iter", 0)

    # ----- inside zone: spawn a limb at each current tip -----
    a_dir = add("GeometryNodeInputNamedAttribute", (520, -240), "dir", data_type='FLOAT_VECTOR')
    setin(a_dir, "Name", "dir")
    a_rad = add("GeometryNodeInputNamedAttribute", (520, -360), "radius", data_type='FLOAT')
    setin(a_rad, "Name", "radius")
    align = add("FunctionNodeAlignRotationToVector", (720, -240), "align Z -> dir")
    try:
        align.axis = 'Z'
    except Exception:
        pass
    link(a_dir, "Attribute", align, "Vector")
    sscale = add("ShaderNodeCombineXYZ", (720, -400), "limb scale (r,r,len)")
    link(a_rad, "Attribute", sscale, "X")
    link(a_rad, "Attribute", sscale, "Y")
    link(rin, "SegLen", sscale, "Z")
    iop = add("GeometryNodeInstanceOnPoints", (940, -120), "spawn limb")
    link(rin, "Tips", iop, "Points")
    link(rin, "Limb", iop, "Instance")
    link(align, "Rotation", iop, "Rotation")
    link(sscale, "Vector", iop, "Scale")
    joinsk = add("GeometryNodeJoinGeometry", (1160, 40), "accumulate skeleton")
    link(rin, "Skeleton", joinsk, "Geometry")
    link(iop, "Instances", joinsk, "Geometry")
    link(joinsk, "Geometry", rout, "Skeleton")

    # ----- advance tips: curl direction with noise, step forward, taper radius -----
    t_pos = add("GeometryNodeInputPosition", (520, 300))
    it_off = add("ShaderNodeMath", (520, 170), "iter offset", operation="MULTIPLY")
    link(rin, "Iter", it_off, 0)
    setin(it_off, 1, 13.7)
    nsc1 = add("ShaderNodeVectorMath", (700, 300), "pos * noise scale", operation="SCALE")
    link(t_pos, "Position", nsc1, 0)
    link(rin, "NoiseScale", nsc1, "Scale")
    offv = add("ShaderNodeCombineXYZ", (700, 170))
    link(it_off, "Value", offv, "X")
    addoff = add("ShaderNodeVectorMath", (880, 260), operation="ADD")
    link(nsc1, "Vector", addoff, 0)
    link(offv, "Vector", addoff, 1)
    noise1 = add("ShaderNodeTexNoise", (1060, 260), "bend noise", noise_dimensions='3D')
    link(addoff, "Vector", noise1, "Vector")
    bctr = add("ShaderNodeVectorMath", (1240, 260), "center", operation="SUBTRACT")
    link(noise1, "Color", bctr, 0)
    setin(bctr, 1, (0.5, 0.5, 0.5))
    bmul = add("ShaderNodeVectorMath", (1420, 260), "* bend strength", operation="SCALE")
    link(bctr, "Vector", bmul, 0)
    link(rin, "BendStr", bmul, "Scale")
    a_dir2 = add("GeometryNodeInputNamedAttribute", (1240, 440), "dir", data_type='FLOAT_VECTOR')
    setin(a_dir2, "Name", "dir")
    dadd = add("ShaderNodeVectorMath", (1420, 440), "dir + bend", operation="ADD")
    link(a_dir2, "Attribute", dadd, 0)
    link(bmul, "Vector", dadd, 1)
    ndir = add("ShaderNodeVectorMath", (1600, 440), "normalize", operation="NORMALIZE")
    link(dadd, "Vector", ndir, 0)
    stepv = add("ShaderNodeVectorMath", (1600, 300), "dir * len", operation="SCALE")
    link(ndir, "Vector", stepv, 0)
    link(rin, "SegLen", stepv, "Scale")
    npos = add("ShaderNodeVectorMath", (1780, 320), "pos + step", operation="ADD")
    link(t_pos, "Position", npos, 0)
    link(stepv, "Vector", npos, 1)

    setpos_t = add("GeometryNodeSetPosition", (940, 300), "move tips")
    link(rin, "Tips", setpos_t, "Geometry")
    link(npos, "Vector", setpos_t, "Position")
    st_dir1 = add("GeometryNodeStoreNamedAttribute", (1120, 360), "store new dir",
                  data_type='FLOAT_VECTOR', domain='POINT')
    setin(st_dir1, "Name", "dir")
    link(setpos_t, "Geometry", st_dir1, "Geometry")
    link_value(st_dir1, ndir, "Vector")
    a_rad2 = add("GeometryNodeInputNamedAttribute", (940, 180), "radius", data_type='FLOAT')
    setin(a_rad2, "Name", "radius")
    radmul = add("ShaderNodeMath", (1120, 200), "radius * taper", operation="MULTIPLY")
    link(a_rad2, "Attribute", radmul, 0)
    link(rin, "Taper", radmul, 1)
    st_rad1 = add("GeometryNodeStoreNamedAttribute", (1300, 300), "store radius",
                  data_type='FLOAT', domain='POINT')
    setin(st_rad1, "Name", "radius")
    link(st_dir1, "Geometry", st_rad1, "Geometry")
    link_value(st_rad1, radmul, "Value")

    # ----- branch: progressively more limbs at chosen iterations -----
    eq2 = add("ShaderNodeMath", (1460, 120), "iter==2", operation="COMPARE")
    link(rin, "Iter", eq2, 0)
    setin(eq2, 1, 2.0)
    setin(eq2, 2, 0.5)
    eq4 = add("ShaderNodeMath", (1460, 20), "iter==4", operation="COMPARE")
    link(rin, "Iter", eq4, 0)
    setin(eq4, 1, 4.0)
    setin(eq4, 2, 0.5)
    orb = add("ShaderNodeMath", (1640, 80), "or", operation="MAXIMUM")
    link(eq2, "Value", orb, 0)
    link(eq4, "Value", orb, 1)
    bflag = add("ShaderNodeMath", (1820, 40), "and Branch", operation="MULTIPLY")
    link(orb, "Value", bflag, 0)
    link(rin, "DoBranch", bflag, 1)
    amt = add("ShaderNodeMath", (2000, 40), "amount = 1 + flag", operation="ADD")
    link(bflag, "Value", amt, 0)
    setin(amt, 1, 1.0)
    dupe = add("GeometryNodeDuplicateElements", (1480, 300), "branch (duplicate tips)",
               domain='POINT')
    link(st_rad1, "Geometry", dupe, "Geometry")
    link(amt, "Value", dupe, "Amount")

    a_dir3 = add("GeometryNodeInputNamedAttribute", (1660, 460), "dir", data_type='FLOAT_VECTOR')
    setin(a_dir3, "Name", "dir")
    crs = add("ShaderNodeVectorMath", (1840, 460), "lateral = dir x up", operation="CROSS_PRODUCT")
    link(a_dir3, "Attribute", crs, 0)
    setin(crs, 1, (0.0, 0.0, 1.0))
    idxc = add("ShaderNodeMath", (1840, 320), "idx-0.5", operation="MULTIPLY_ADD")
    link(dupe, "Duplicate Index", idxc, 0)
    setin(idxc, 1, 1.0)
    setin(idxc, 2, -0.5)
    idxg = add("ShaderNodeMath", (2020, 320), "* flag", operation="MULTIPLY")
    link(idxc, "Value", idxg, 0)
    link(bflag, "Value", idxg, 1)
    idxs = add("ShaderNodeMath", (2200, 320), "* splay", operation="MULTIPLY")
    link(idxg, "Value", idxs, 0)
    setin(idxs, 1, 1.1)
    lats = add("ShaderNodeVectorMath", (2200, 460), "lateral * amt", operation="SCALE")
    link(crs, "Vector", lats, 0)
    link(idxs, "Value", lats, "Scale")
    cadd = add("ShaderNodeVectorMath", (2380, 460), "dir + lateral", operation="ADD")
    link(a_dir3, "Attribute", cadd, 0)
    link(lats, "Vector", cadd, 1)
    cdir = add("ShaderNodeVectorMath", (2560, 460), "normalize", operation="NORMALIZE")
    link(cadd, "Vector", cdir, 0)
    st_dir2 = add("GeometryNodeStoreNamedAttribute", (2560, 300), "store child dir",
                  data_type='FLOAT_VECTOR', domain='POINT')
    setin(st_dir2, "Name", "dir")
    link(dupe, "Geometry", st_dir2, "Geometry")
    link_value(st_dir2, cdir, "Vector")
    link(st_dir2, "Geometry", rout, "Tips")

    # ----- pass-through constants + increment iter -----
    link(rin, "Limb", rout, "Limb")
    link(rin, "SegLen", rout, "SegLen")
    link(rin, "Taper", rout, "Taper")
    link(rin, "BendStr", rout, "BendStr")
    link(rin, "NoiseScale", rout, "NoiseScale")
    link(rin, "DoBranch", rout, "DoBranch")
    iadd = add("ShaderNodeMath", (1820, -80), "iter + 1", operation="ADD")
    link(rin, "Iter", iadd, 0)
    setin(iadd, 1, 1.0)
    link(iadd, "Value", rout, "Iter")

    # ---------------- finalize ----------------
    real = add("GeometryNodeRealizeInstances", (2200, 0), "realize")
    link(rout, "Skeleton", real, "Geometry")
    link(real, "Geometry", gout, "Geometry")

    # ---------------- scene object ----------------
    for o in list(bpy.data.objects):
        if o.name.startswith("Tentacle"):
            bpy.data.objects.remove(o, do_unlink=True)
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, 0))
    obj = bpy.context.active_object
    obj.name = "Tentacle_Source"
    mod = obj.modifiers.new("Tentacles", type='NODES')
    mod.node_group = ng

    try:
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                for region in area.regions:
                    if region.type == 'WINDOW':
                        with bpy.context.temp_override(area=area, region=region):
                            bpy.ops.view3d.view_selected()
                break
    except Exception:
        pass

    blend_path = os.path.join(OUT_DIR, "tentacle.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend_path)
    write_status("SUCCESS\nnodes=%d\nblend=%s\n" % (len(ng.nodes), blend_path))

except Exception:
    write_status("ERROR\n" + traceback.format_exc())
