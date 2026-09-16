"""Sea of Probabilities — UE-side asset builder (runs inside UnrealEditor-Cmd).

    UnrealEditor-Cmd <uproject> -run=pythonscript -script=<this> [env SEA_STEP=1,3,5]
    env SEA_REPO = repo root (the launcher sets it; scripts inside UE can't know it)

Steps are idempotent and gated by SEA_STEP (default: all implemented steps):
  1  import build/SM_Die.fbx -> /Game/SeaOfProbabilities/Meshes/SM_Die, verify
  3  materials (M_DieBody / M_DiePips / M_DieAce with the shared WPO, post materials)
  5  level L_SeaOfProbabilities (actor, sun, sky, post volume), saved + reload-verified
Prints one 'SEA STEP n: PASS|FAIL ...' line per step; the launcher greps them.
"""
import os

import unreal

REPO = os.environ.get("SEA_REPO")
if not REPO:
    raise RuntimeError("SEA_REPO not set - the launcher must pass the repo root")
SHOW = os.path.join(REPO, "showcase", "sea_of_probabilities")
ROOT = "/Game/SeaOfProbabilities"
MESH_PATH = ROOT + "/Meshes/SM_Die"
STEPS = {int(s) for s in os.environ.get("SEA_STEP", "1").split(",") if s.strip()}
EAL = unreal.EditorAssetLibrary


def log(*a):
    print("SEA", *a)


# ---------------------------------------------------------------- step 1: die mesh

def step1_import_die():
    fbx = os.path.join(SHOW, "build", "SM_Die.fbx")
    if not os.path.isfile(fbx):
        return False, "missing %s (run blender/make_die.py first)" % fbx
    task = unreal.AssetImportTask()
    task.filename = fbx
    task.destination_path = ROOT + "/Meshes"
    task.destination_name = "SM_Die"
    task.automated = True
    task.save = True
    task.replace_existing = True
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    if not EAL.does_asset_exist(MESH_PATH):
        return False, "import produced no asset at %s" % MESH_PATH
    sm = EAL.load_asset(MESH_PATH)
    # UE 5.8 imports static meshes with Nanite ON; the die is 256 tris and animates
    # through WPO + per-instance custom data, so keep it a classic ISM mesh.
    try:
        ns = sm.get_editor_property("nanite_settings")
        ns.set_editor_property("enabled", False)
        unreal.get_editor_subsystem(unreal.StaticMeshEditorSubsystem).set_nanite_settings(sm, ns, True)
    except Exception as e:  # noqa: BLE001
        log("nanite disable skipped: %s" % e)
    mats = list(sm.static_materials)
    slots = [str(m.material_slot_name) for m in mats]
    box = sm.get_bounding_box()
    size = box.max - box.min
    verts = sm.get_num_vertices(0)
    tris = sm.get_num_triangles(0)
    EAL.save_asset(MESH_PATH)
    info = "slots=%s verts=%d tris=%d size_cm=(%.1f, %.1f, %.1f)" % (slots, verts, tris, size.x, size.y, size.z)
    ok = len(mats) == 3 and all(abs(v - 100.8) < 1.0 for v in (size.x, size.y, size.z))
    return ok, info


# ---------------------------------------------------------------- main

RESULTS = {}
if 1 in STEPS:
    RESULTS[1] = step1_import_die()
if 3 in STEPS:
    import sys
    sys.path.insert(0, os.path.join(SHOW, 'tools'))
    import importlib, sea_materials
    importlib.reload(sea_materials)
    try:
        RESULTS[3] = sea_materials.build_all(SHOW, MESH_PATH)
    except Exception as e:
        import traceback; traceback.print_exc()
        RESULTS[3] = (False, 'exception: %s' % e)
if 5 in STEPS:
    import sys
    sys.path.insert(0, os.path.join(SHOW, 'tools'))
    import importlib, sea_level
    importlib.reload(sea_level)
    try:
        RESULTS[5] = sea_level.build(MESH_PATH)
    except Exception as e:
        import traceback; traceback.print_exc()
        RESULTS[5] = (False, 'exception: %s' % e)
for n in sorted(RESULTS):
    ok, info = RESULTS[n]
    log("STEP %d: %s %s" % (n, "PASS" if ok else "FAIL", info))
log("DONE")
