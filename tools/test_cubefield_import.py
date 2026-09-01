"""Headless V1.x import test: CubeField_FX -> PCG with live actor/noise chains.

Asserts the *behaviour* the Blender graph asks for, not just node presence:
per-instance size variety, matched noise frequency, and smooth proximity
falloff (exact via the GNuePCG module, banded when it isn't compiled in).
"""
import unreal

import gnue_importer

FOLDER = r"C:\Users\User\Documents\Unreal Projects\GNtoUE\GNueDrops\cubefield_fx"
DEST = "/Game/ZZZ_CubeFieldTest"

info = gnue_importer.main(FOLDER, dest=DEST)
print("CF IMPORT:", info["result"], "groups:", info["groups"], "counts:", info["counts"])

graph = unreal.load_asset(info["graph"])
types = {}
varying_scale = []      # TransformPoints with a real min..max spread
noise_freq = []         # spatial-noise feature sizes actually configured
for node in graph.get_editor_property("nodes"):
    s = node.get_settings()
    if not s:
        continue
    t = s.get_class().get_name()
    types[t] = types.get(t, 0) + 1
    if t == "PCGTransformPointsSettings":
        lo = s.get_editor_property("scale_min")
        hi = s.get_editor_property("scale_max")
        if (hi.x - lo.x) > 1e-6 or (hi.y - lo.y) > 1e-6 or (hi.z - lo.z) > 1e-6:
            varying_scale.append((node.get_name(),
                                  (round(lo.x, 3), round(lo.y, 3), round(lo.z, 3)),
                                  (round(hi.x, 3), round(hi.y, 3), round(hi.z, 3))))
    if t == "PCGSpatialNoiseSettings":
        try:
            noise_freq.append((node.get_name(),
                               round(s.get_editor_property("transform").scale3d.x, 2)))
        except Exception:
            noise_freq.append((node.get_name(), None))

for t in sorted(types):
    print("  node:", t, "x", types[t])
for v in varying_scale:
    print("  varying scale:", v)
print("  noise transform scales:", noise_freq)

has_custom = types.get("GNueScaleByAttributeSettings", 0) > 0
need = {
    "actor binding": any("DataFromActor" in t or "GetActorData" in t for t in types),
    "spatial noise": any("SpatialNoise" in t for t in types),
    "distance": any(t.startswith("PCGDistance") for t in types),
    "remap": any("AttributeRemap" in t for t in types),
    # UE 5.8's whole PCGMetadata* op family emits no data - we must never use it
    "no dead maths nodes": types.get("PCGMetadataMathsSettings", 0) == 0,
    # exact smooth falloff, or the banded approximation when GNuePCG is absent
    "proximity falloff": has_custom or types.get("PCGAttributeFilteringRangeSettings", 0) >= 3,
    # greebles must vary per instance (random * Greeble Size), not all be identical
    "per-instance size variety": len(varying_scale) >= 2,
    # noise must not sit at UE's ~100m default feature size
    "noise frequency set": all(f not in (None, 1.0) for _n, f in noise_freq) and bool(noise_freq),
    "copy points (greebles)": any("CopyPoints" in t for t in types),
    "density filter (coverage)": any("DensityFilter" in t for t in types),
    "spawners x2": types.get("PCGStaticMeshSpawnerSettings", 0) >= 2,
}
bad = [k for k, v in need.items() if not v]
for k, v in need.items():
    print("  check:", k, "->", "OK" if v else "MISSING")
print("CF falloff mode:", "EXACT (GNuePCG)" if has_custom else "BANDED fallback")
print("CF RESULT:", "PASS" if not bad else "FAIL %s" % bad)
for w in info["warnings"]:
    print("  warn:", w)
