"""Verify per-point rotations + Progress response for the Domino import."""
import unreal

import gnue_importer

FOLDER = r"C:\Users\User\Documents\Unreal Projects\GNtoUE\GNueDrops\Domino"
DEST = "/Game/ZZZ_DominoTest"


def rots(progress):
    info = gnue_importer.main(FOLDER, dest=DEST, param_overrides={"Progress": progress})
    graph = unreal.load_asset(info["graph"])
    out = []
    for node in graph.get_editor_property("nodes"):
        s = node.get_settings()
        if s and s.get_class().get_name() == "PCGCreatePointsSettings":
            pts = s.get_editor_property("points_to_create")
            for i in (5, 40, 75, 110, 145):
                if i < len(pts):
                    r = pts[i].get_editor_property("transform").rotation.rotator()
                    out.append((i, round(r.yaw, 1), round(r.pitch, 1), round(r.roll, 1)))
    return info["result"], out


res1, r1 = rots(0.2)
res2, r2 = rots(0.8)
print("ROT TEST P=0.2:", res1)
for row in r1:
    print("  i=%d yaw=%s pitch=%s roll=%s" % row)
print("ROT TEST P=0.8:", res2)
for row in r2:
    print("  i=%d yaw=%s pitch=%s roll=%s" % row)

yaws = {row[1] for row in r1}
diff = any(a[1:] != b[1:] for a, b in zip(r1, r2))
print("ROT RESULT:", "PASS" if (len(yaws) > 2 and diff) else "FAIL",
      "| distinct yaws:", len(yaws), "| progress changes rotations:", diff)
