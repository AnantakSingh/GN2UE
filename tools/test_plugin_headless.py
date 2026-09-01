"""Headless plug-and-play test: force-rescan GNueDrops via the plugin's own
bootstrap module and verify the PCG asset exists."""
import unreal

import init_unreal  # the GNueImporter plugin bootstrap (already ran at startup)

done, skipped, failed = init_unreal.scan_drops(show_dialog=False, force=True)
print("PNP SCAN: imported=%s skipped=%s failed=%s" % (done, skipped, failed))
ok = unreal.EditorAssetLibrary.does_asset_exist(
    "/Game/GNueImport/RopeBridge_V1/PCG_RopeBridge_V1")
print("PNP RESULT:", "PASS" if (ok and not failed) else "FAIL")
