"""Verify accumulate (random walk) + trim in the numeric kernel."""
import unreal

import gnue_importer

FOLDER = r"C:\Users\User\Documents\Unreal Projects\GNtoUE\GNueDrops\walktrim_test"
DEST = "/Game/ZZZ_WalkTrimTest"


def first_last(overrides):
    info = gnue_importer.main(FOLDER, dest=DEST, param_overrides=overrides)
    graph = unreal.load_asset(info["graph"])
    for node in graph.get_editor_property("nodes"):
        s = node.get_settings()
        if s and s.get_class().get_name() == "PCGCreatePointsSettings":
            pts = s.get_editor_property("points_to_create")
            ps = [pts[i].get_editor_property("transform").translation for i in
                  (0, len(pts) // 2, len(pts) - 1)]
            return info["result"], len(pts), [(round(p.x, 1), round(p.y, 1), round(p.z, 1))
                                              for p in ps]
    return info["result"], 0, []


r1, n1, p1 = first_last(None)
r2, n2, p2 = first_last({"Trim Start": 0.5, "Seed": 0})
r3, n3, p3 = first_last({"Seed": 7})
print("WT default:", r1, "cubes:", n1, "first/mid/last:", p1)
print("WT trim=0.5:", r2, "cubes:", n2, "first/mid/last:", p2)
print("WT seed=7:", r3, "first/mid/last:", p3)
rising = n1 > 0 and p1[0][2] < p1[1][2] < p1[2][2]
trim_moves = p1[0] != p2[0]
seed_changes = p1 != p3
print("WT checks: rising-walk", rising, "| trim-moves-start", trim_moves,
      "| seed-changes-walk", seed_changes, "| count", n1 == 20)
print("WT RESULT:", "PASS" if (rising and trim_moves and seed_changes and n1 == 20)
      else "FAIL")
