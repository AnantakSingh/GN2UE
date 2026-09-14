"""Force-reimport CubeField_FX to its real location with the latest importer,
and drop the obsolete centered-cube mesh from the earlier import.

Source: <Project>/GNueDrops/cubefield_fx (or GNUE_TEST_FOLDER). Skips when absent.
"""
import os

import unreal

import gnue_importer


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


def main(folder):
    info = gnue_importer.main(folder)
    print("CFREAL:", info["result"], info["counts"], info["graph"])
    stale = "/Game/GNueImport/CubeField_FX/Meshes/SM_GNue_Cube"
    if unreal.EditorAssetLibrary.does_asset_exist(stale):
        ok = unreal.EditorAssetLibrary.delete_asset(stale)
        print("CFREAL stale centered cube deleted:", ok)
    for w in info["warnings"]:
        print("  warn:", w)


FOLDER = fixture("cubefield_fx", "CFREAL")
if FOLDER:
    main(FOLDER)
