"""Verify per-point rotations + Progress response for the Domino import.

Fixture: <Project>/GNueDrops/Domino (or GNUE_TEST_FOLDER). Skips when absent.
"""
import os

import unreal

import gnue_importer

DEST = "/Game/ZZZ_DominoTest"


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


def rots(folder, progress):
    info = gnue_importer.main(folder, dest=DEST, param_overrides={"Progress": progress})
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


def main(folder):
    res1, r1 = rots(folder, 0.2)
    res2, r2 = rots(folder, 0.8)
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


FOLDER = fixture("Domino", "ROT")
if FOLDER:
    main(FOLDER)
