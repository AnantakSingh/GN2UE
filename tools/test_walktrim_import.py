"""Verify accumulate (random walk) + trim in the numeric kernel.

Fixture: <Project>/GNueDrops/walktrim_test (or GNUE_TEST_FOLDER). Skips when absent.
"""
import os

import unreal

import gnue_importer

DEST = "/Game/ZZZ_WalkTrimTest"


def fixture(name, tag):
    """<Project>/GNueDrops/<name> (or GNUE_TEST_FOLDER); None + SKIP line if absent.
    Resolved from the engine, never hardcoded — see PORTABILITY.md §2.3."""
    folder = os.environ.get("GNUE_TEST_FOLDER") or os.path.join(
        unreal.SystemLibrary.get_project_directory(), "GNueDrops", name)
    if not os.path.isfile(os.path.join(folder, "effect.gnue.json")):
        print("%s RESULT: SKIP - no effect.gnue.json at %s (export '%s' into GNueDrops/ "
              "or set GNUE_TEST_FOLDER)" % (tag, folder, name))
        return None
    return folder


def first_last(folder, overrides):
    info = gnue_importer.main(folder, dest=DEST, param_overrides=overrides)
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


def main(folder):
    r1, n1, p1 = first_last(folder, None)
    r2, n2, p2 = first_last(folder, {"Trim Start": 0.5, "Seed": 0})
    r3, n3, p3 = first_last(folder, {"Seed": 7})
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


FOLDER = fixture("walktrim_test", "WT")
if FOLDER:
    main(FOLDER)
