"""Sea of Probabilities — die mesh generator (Blender, headless).

Rebuilds the web version's buildDie() exactly (index.html ~l.708): a
RoundedBoxGeometry(1,1,1, segments=2, radius=bevel) plus pip discs (radius
0.078, 10 segments, PIP_OFF 0.205, EPS 0.004) laid out per the spec's face
table, all authored in THREE's frame and converted to Blender's so that the
FBX -> UE import lands with UE = (-z, x, y): top face (+Z UE) = 1 pip, spin
axis three +X = UE +Y.

Vertex colours are replaced by MATERIAL SLOTS (survive FBX reliably):
    0 M_DieBody   1 M_DiePips   2 M_DieAce (the face-1 pip; redAce = material swap)

    blender --background --python make_die.py
    env: SEA_BEVEL (0.18), SEA_FBX (output path; default ../build/SM_Die.fbx)
"""
import math
import os

import bmesh
import bpy
from mathutils import Vector

BEVEL = float(os.environ.get("SEA_BEVEL", "0.18"))
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("SEA_FBX") or os.path.normpath(os.path.join(HERE, "..", "build", "SM_Die.fbx"))

PIP_R, PIP_OFF, EPS, PIP_SEGS = 0.078, 0.205, 0.004, 10
LAYOUTS = {
    1: [(0, 0)],
    2: [(-1, -1), (1, 1)],
    3: [(-1, -1), (0, 0), (1, 1)],
    4: [(-1, -1), (-1, 1), (1, -1), (1, 1)],
    5: [(-1, -1), (-1, 1), (0, 0), (1, -1), (1, 1)],
    6: [(-1, -1), (-1, 0), (-1, 1), (1, -1), (1, 0), (1, 1)],
}
# (normal in three's frame, pip count) — spec §4.3
FACES = [((0, 1, 0), 1), ((0, -1, 0), 6), ((0, 0, 1), 2), ((0, 0, -1), 5), ((1, 0, 0), 3), ((-1, 0, 0), 4)]


def q_from_unit_vectors(a, b):
    """three.js Quaternion.setFromUnitVectors, bit-for-bit (incl. the antiparallel branch)."""
    r = a.dot(b) + 1.0
    if r < 1e-6:
        r = 0.0
        if abs(a.x) > abs(a.z):
            x, y, z = -a.y, a.x, 0.0
        else:
            x, y, z = 0.0, -a.z, a.y
    else:
        c = a.cross(b)
        x, y, z = c.x, c.y, c.z
    w = r
    n = math.sqrt(x * x + y * y + z * z + w * w)
    return (x / n, y / n, z / n, w / n)


def q_apply(q, v):
    """three.js Vector3.applyQuaternion."""
    x, y, z = v
    qx, qy, qz, qw = q
    ix = qw * x + qy * z - qz * y
    iy = qw * y + qz * x - qx * z
    iz = qw * z + qx * y - qy * x
    iw = -qx * x - qy * y - qz * z
    return Vector((ix * qw + iw * -qx + iy * -qz - iz * -qy,
                   iy * qw + iw * -qy + iz * -qx - ix * -qz,
                   iz * qw + iw * -qz + ix * -qy - iy * -qx))


def three_to_blender(v):
    """three (x,y,z) -> Blender (-z, -x, y): a proper rotation (det +1), so after
    the FBX Y-flip UE sees exactly spec §2: UE = (-z, x, y)."""
    return Vector((-v.z, -v.x, v.y))


def main():
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.0))
    body = bpy.context.active_object
    body.name = "SM_Die"
    bev = body.modifiers.new("Bevel", "BEVEL")
    bev.width, bev.segments, bev.limit_method, bev.use_clamp_overlap = BEVEL, 2, "NONE", True
    bpy.ops.object.modifier_apply(modifier="Bevel")
    me = body.data
    for name, rgb in (("M_DieBody", (1, 1, 1)), ("M_DiePips", (0.09, 0.09, 0.11)), ("M_DieAce", (0.78, 0.21, 0.21))):
        m = bpy.data.materials.new(name)
        m.diffuse_color = (*rgb, 1.0)
        me.materials.append(m)

    bm = bmesh.new()
    bm.from_mesh(me)
    for f in bm.faces:
        f.material_index = 0
    z_axis = Vector((0.0, 0.0, 1.0))
    npips = 0
    for n3, count in FACES:
        n = Vector(n3)
        q = q_from_unit_vectors(z_axis, n)
        tan = q_apply(q, (1.0, 0.0, 0.0))
        bit = q_apply(q, (0.0, 1.0, 0.0))
        for u, v in LAYOUTS[count]:
            centre = n * (0.5 + EPS) + tan * (u * PIP_OFF) + bit * (v * PIP_OFF)
            verts = []
            for k in range(PIP_SEGS):
                a = 2.0 * math.pi * k / PIP_SEGS          # CircleGeometry: thetaStart 0, CCW
                p = centre + q_apply(q, (PIP_R * math.cos(a), PIP_R * math.sin(a), 0.0))
                verts.append(bm.verts.new(three_to_blender(p)))
            face = bm.faces.new(verts)
            face.material_index = 2 if count == 1 else 1
            npips += 1
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = True
    me.update()

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    for o in bpy.data.objects:
        o.select_set(o is body)
    bpy.context.view_layer.objects.active = body
    bpy.ops.export_scene.fbx(filepath=OUT, use_selection=True, apply_scale_options="FBX_SCALE_ALL",
                             bake_space_transform=True, use_mesh_modifiers=True, add_leaf_bones=False,
                             mesh_smooth_type="FACE")
    xs = [v.co.x for v in me.vertices]; ys = [v.co.y for v in me.vertices]; zs = [v.co.z for v in me.vertices]
    print("DIE OK: verts=%d faces=%d pips=%d slots=%d bevel=%.3f bounds=(%.3f..%.3f, %.3f..%.3f, %.3f..%.3f) -> %s"
          % (len(me.vertices), len(me.polygons), npips, len(me.materials), BEVEL,
             min(xs), max(xs), min(ys), max(ys), min(zs), max(zs), OUT))


main()
