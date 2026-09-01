"""Headless GNueParams test: declare on import, read back, override rebuild."""
import unreal

import gnue_importer  # from the GNueImporter plugin (Content/Python on sys.path)

FOLDER = r"C:\Users\User\Documents\Unreal Projects\GNtoUE\GNueDrops\ropebridge_v1"

lib = getattr(unreal, "GNueParamLibrary", None)
print("PARAMS LIB LOADED:", lib is not None)

info = gnue_importer.main(FOLDER)
print("PARAMS IMPORT:", info["result"], info["counts"])

# one-time repair: earlier spaced-name declares left broken zero defaults —
# rewrite every parameter to its descriptor default
import json
with open(FOLDER + r"\effect.gnue.json", "r", encoding="utf-8") as f:
    desc = json.load(f)
g0 = unreal.EditorAssetLibrary.load_asset("/Game/GNueImport/RopeBridge_V1/PCG_RopeBridge_V1")
spec = [{"name": gnue_importer.param_bag_name(p["name"]),
         "type": str(p["type"]).lower(), "default": p["default"]}
        for p in desc["parameters"]]
n = unreal.GNueParamLibrary.declare_parameters(g0, json.dumps(spec), True)
print("PARAMS REPAIR (reset to defaults):", n)

g = unreal.EditorAssetLibrary.load_asset("/Game/GNueImport/RopeBridge_V1/PCG_RopeBridge_V1")
h = unreal.PCGGraphParametersHelpers
checks = []
try:
    checks.append(("Bridge_Width", h.get_double_parameter(g, "Bridge_Width")))
    checks.append(("Sag", h.get_double_parameter(g, "Sag")))
    checks.append(("Seed", h.get_int32_parameter(g, "Seed")))
    checks.append(("Lanterns", h.get_bool_parameter(g, "Lanterns")))
    v = h.get_vector_parameter(g, "Plank_Size")
    checks.append(("Plank_Size", (v.x, v.y, v.z)))
except Exception as e:
    print("PARAMS READBACK ERROR:", e)
for name, val in checks:
    print("PARAMS READBACK: %s = %s" % (name, val))

info2 = gnue_importer.main(FOLDER, param_overrides={"Bridge Width": 2.5, "Sag": 1.5})
print("PARAMS OVERRIDE IMPORT:", info2["result"], info2["counts"])

# restore descriptor defaults so the level effect stays as authored
info3 = gnue_importer.main(FOLDER)
print("PARAMS RESTORED:", info3["result"])
print("PARAMS TEST DONE")
