# gnue_exporter — Blender-side plugin (extension) for GN→UE export

Deterministic transpiler: V1-core Geometry Nodes graph → descriptor folder that
`ue_importer/import_gnue2.py` rebuilds as a PCG graph. No AI at export time —
closed node vocabulary + fixed lowering rules; anything outside V1 is refused
with a per-node report (never guessed).

## Layout

| File | Role |
|---|---|
| `core.py` | **bpy-free.** V1 whitelist validation, expression lowering (field trees → op trees), block lowering (geometry nodes → semantic blocks), asset rules (cube→shared unit cube + scale expr; half-z-shift → bottom origin), numeric evaluator, descriptor/report emission. |
| `frontend_bpy.py` | bpy graph reader → IR (reroutes resolved, enabled-socket aware, version-tolerant prop reads), FBX baker (unit cubes + depsgraph subgraph bake), export driver. |
| `__init__.py` | N-panel UI (3D View + Node Editor sidebars, "GN to UE" tab): node-group picker, folder picker, **Validate** / **Export** operators, report text block. |
| `blender_manifest.toml` | Blender 4.2+ extension manifest (`files` permission declared). |
| `export_cli.py` | UI-less driver for socket/headless testing. |

## Output folder contract

```
effect.gnue.json    descriptor v2 (family "graph"): params, blocks, expression
                    trees, asset refs — full parametric structure preserved
meshes/*.fbx        baked instance meshes (deduped; unit cubes shared)
manifest.json       versions, source blend, node group, asset list
export_report.txt   what translated, what was approximated, what was refused
```

## Install as extension

Zip the `gnue_exporter` folder (manifest at zip root) → Blender Preferences →
Extensions → Install from Disk. Or for dev: run `export_cli.py` through the
blender-mcp socket / `register()` via script.

## Risk handling (from the design review)

- **Version drift**: sockets read by name with `enabled` flags (Mix/Random/
  Compare per-type duplicates), props read defensively, Blender version stamped
  into manifest + descriptor.
- **Domain crossing**: validator rejects non-POINT/INSTANCE domains.
- **Switch branches**: both geometry branches lowered and validated.
- **Capture**: explicit `attribute.capture` blocks; leaves are `capture:<name>`.
- **Muted nodes / nested groups**: refused with instructions (not silently skipped).
- **Nonlinear bake dependence**: assets that can't reduce to unit-cube+scale are
  baked at current values and reported as frozen.

## Golden fixtures

- `RopeBridge_V1` (built by `../build_v1_bridge.py`): 115 nodes → 41 blocks,
  2 shared assets, 0 errors — the positive fixture.
- `SpineTreeGN`: refused with exact node list (Accumulate Field, Grid, Cylinder,
  Mesh to Curve, Subdivide Mesh) — the negative fixture.
