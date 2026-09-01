"""Force-reimport CubeField_FX to its real location with the latest importer,
and drop the obsolete centered-cube mesh from the earlier import."""
import unreal

import gnue_importer

info = gnue_importer.main(r"C:\Users\User\Documents\Unreal Projects\GNtoUE\GNueDrops\cubefield_fx")
print("CFREAL:", info["result"], info["counts"], info["graph"])
stale = "/Game/GNueImport/CubeField_FX/Meshes/SM_GNue_Cube"
if unreal.EditorAssetLibrary.does_asset_exist(stale):
    ok = unreal.EditorAssetLibrary.delete_asset(stale)
    print("CFREAL stale centered cube deleted:", ok)
for w in info["warnings"]:
    print("  warn:", w)
