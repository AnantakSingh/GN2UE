"""Headless test of per-volume graph copies: load the level (read-only), apply
custom parameters to one bridge volume, verify the copy asset + divergence.
The map is NEVER saved — level changes stay in commandlet memory."""
import unreal

import init_unreal  # GNueImporter plugin bootstrap (fresh code in this process)

ok = unreal.EditorLoadingAndSavingUtils.load_map("/Game/FirstPerson/Lvl_FirstPerson")
print("PV MAP LOADED:", bool(ok))

comps = init_unreal._gnue_components()
print("PV GNUE VOLUMES:", [(a.get_actor_label(), e) for a, c, g, gr, e in comps])
if not comps:
    print("PV RESULT: FAIL (no volumes)")
else:
    actor, comp, gi, graph, effect = comps[0]
    base_path = graph.get_path_name()
    folder = init_unreal._drop_folder_for(effect)
    desc = init_unreal._load_desc(folder)
    values = {p["name"]: p["default"] for p in desc["parameters"]}
    values["Bridge Width"] = 3.0
    values["Sag"] = 0.3
    info = init_unreal._apply_to_volume(actor, comp, gi, effect, values)
    print("PV APPLY:", info["result"] if info else None, info["counts"] if info else None)

    gi2 = comp.get_editor_property("graph_instance")
    new_graph = gi2.get_editor_property("graph")
    print("PV REASSIGNED:", new_graph.get_path_name())
    print("PV DIVERGED:", new_graph.get_path_name() != base_path
          and "/Instances/" in new_graph.get_path_name())

    h = unreal.PCGGraphParametersHelpers
    w = h.get_double_parameter(new_graph, "Bridge_Width")
    s = h.get_double_parameter(new_graph, "Sag")
    print("PV COPY PARAMS: Bridge_Width=%s Sag=%s" % (w, s))

    base = unreal.EditorAssetLibrary.load_asset(base_path)
    wb = h.get_double_parameter(base, "Bridge_Width")
    print("PV BASE UNTOUCHED: Bridge_Width=%s" % wb)
    good = (info and info["result"].startswith("PASS") and abs(w - 3.0) < 1e-4
            and abs(s - 0.3) < 1e-4 and abs(wb - 1.15) < 1e-2)
    print("PV RESULT:", "PASS" if good else "FAIL")
# deliberately no map save
