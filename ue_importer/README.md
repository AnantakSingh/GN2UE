# GN→UE importer (native UE Python, no MCP)

> **v2 (2026-08-14):** `import_gnue2.py` consumes descriptor v2 ("graph"
> family) from `gnue_exporter` — a numeric kernel evaluates deterministic
> geometry (curves, duplication, per-point math) from the descriptor's
> expression trees into explicit PCG point lists; randomness stays live in PCG
> (Transform Points ranges, Surface Sampler). Applies proper Y-negation
> handedness conversion (closes gap #4 for deterministic effects). Verified
> headless on `export/ropebridge_v1`: 6 spawn groups, 23 planks / 138 rope
> segments / 4 posts / 8 lanterns + 2 live scatter chains, 0 property or edge
> failures. Since plugin v0.2.0, `main()` also declares the Blender parameters
> on the graph (GNueParams C++ module) and accepts `param_overrides` +
> `meshes_dest` — used by the plugin's auto-apply/per-volume graph copies.
> Descriptor folder via `GNUE2_DIR` env var.

Builds a parametric PCG graph inside Unreal from a `.gnue.json` descriptor,
using only the engine's built-in **Python Editor Script Plugin** — no
unreal-mcp server involved. This grew into the shipped client plugin:
`GNtoUE/Plugins/GNueImporter` is generated from these files by
`tools/sync_ue_plugin.py` (edit here, sync, never edit the plugin copies).

## Files

| File | What |
|---|---|
| `import_gnue.py` | The importer. Family-dispatching (`static_scatter` v1.1 today). Reads the descriptor, imports FBX meshes, creates the PCG graph, assigns spawner meshes, declares graph parameters (best effort), saves everything under `/Game/GNueImport/<NodeGroup>/`. |
| `run_import.ps1` | Headless runner: `UnrealEditor-Cmd.exe … -run=pythonscript`. Works with the editor closed (CI-able). |

## Usage

In-editor (Output Log → Cmd set to Python, or `py` console command):

```
py "c:/Projects/GNtoUEresearch/ue_importer/import_gnue.py"
```

Headless:

```
powershell -File run_import.ps1                      # default: ../export/spinetree.gnue.json
powershell -File run_import.ps1 -Descriptor <path>
```

Descriptor selection: `GNUE_DESCRIPTOR` env var → argv[1] → default
`../export/spinetree.gnue.json`. Destination override: `GNUE_DEST` env var
(default `/Game/GNueImport/<node_group>`).

Requires `PCG` and `PythonScriptPlugin` enabled in the uproject (added
2026-08-13; also closes export/README.md gap #6 for cooking).

## What it builds (static_scatter)

Same topology as the hand-built `/Game/SpineTree/PCG_SpineTree`
(see `../export/README.md` for the node-by-node recipe and gotchas):

- `curve.random_walk` → Create Points → Duplicate Point (direction **(0,0,0)**,
  step in `point_transform`) → Transform Points (jitter) → Create Spline
- `scatter.on_curve` → Spline Sampler (count, unbounded, seed-from-index)
  → [Attribute Noise `$Density` + Density Filter, when the block has a
  random_bool selection] → Transform Points (scale/rotation, `uniform_scale`
  explicitly set) → Static Mesh Spawner (weighted selector entry)

It also creates/assigns `M_GNue_TwoSided` to the leaf mesh (closes gap #5 for
the imported copy).

Imports are **non-destructive**: everything lands under `/Game/GNueImport/`,
the existing hand-built `/Game/SpineTree/` assets are untouched.

## Known limits (inherited from the family, not the script)

- Statistical equivalence only — Blender RNG is not reproducible in UE.
- Spine is per-point jitter, not an accumulated walk (no prefix-sum in PCG).
- `segment_overlap` expressions are baked from an *estimated* curve length
  (mean-step × steps); the hand-built graph used the measured length
  (1.24 est vs 1.17 measured for the default SpineTree).
- Graph parameters cannot be declared from Python on UE 5.8
  (`PCGGraphParametersHelpers` only has get/set, no add) — **solved** since
  plugin v0.2.0 by the C++ `GNueParams` module (`declare_parameters`).

## Verified

Headless run 2026-08-13 against UE 5.8 / `GNtoUE.uproject`:
`PASS_WITH_WARNINGS — /Game/GNueImport/SpineTreeGN/PCG_SpineTreeGN (12 nodes,
11/11 edges)`, both spawner meshes assigned, all node settings confirmed by
re-loading the saved asset (iterations/offsets/rotators/filter bounds match the
hand-built graph). Only warning: the parameter limitation above.

UE 5.8 Python API notes (differ from older docs):
- edges: `node.add_edge_to(out_label, to_node, in_label)` — there is no
  `PCGGraph.add_labeled_edge`; real pin labels are on `node.output_pins[i]
  .properties.label`
- node layout: `node.set_node_position(x, y)` (no `position_x/y` properties)
- spawner meshes: mutate `mesh_selector_parameters` (the `DefaultSelectorInstance`)
  **in place**; the property itself is read-only
- attribute selectors: use `selector.set_point_property(...)`; the `selection`
  field is protected
- commandlet exit code is 1 whenever any error hits the log — with the
  interactive editor open, the MCP toolset's port-8000 bind failure does exactly
  that, so `run_import.ps1` judges success by the `GNUE IMPORT RESULT` line.

## v2 importer (`import_gnue2.py`) — UE 5.8 behaviours worth knowing

These are engine constraints found by testing, not preferences; changing them
silently breaks output, so they are called out here.

- **`Attribute Maths Op` — and every other `PCGMetadata*` op (`Attribute
  Transform Op`, `Make Vector Attribute`, …) — produces NO output data.** The
  node configures and executes without any log error, and the downstream chain
  simply receives nothing. Per-point scale math therefore uses our own node,
  `GNue Scale By Attribute` (GNuePCG module). If that module isn't compiled,
  `emit_falloff_bands` falls back to discrete scale bands and the report says so.
- **Create Points defaults to World space.** We bake Blender-absolute
  coordinates, so in World space every explicit-geometry effect generates at the
  world origin and ignores its volume (multiple effects pile up in one spot).
  The importer sets `coordinate_space = LocalComponent`; the volume's *scale*
  then multiplies such effects, so those volumes want scale 1.
- **Spatial Noise defaults to a ~100 m feature size** (it samples world cm times
  `MAGIC_SCALE_FACTOR` 1e-4), which reads as a constant across a normal effect.
  Blender's Noise Texture *Scale* maps on as `transform.scale = 100 * scale`;
  `brightness 0.5` centres the engine's Perlin (~[0.14, 0.50] raw) into [0, 1].
- **Never route surface data through a Union node into Surface Sampler**
  ("No surfaces found from which to generate") — connect each source directly
  to the `Surface` pin instead.
- **`always_requery_actors = True` on Get Actor Data**, or PCG caches the
  actor's transform and regenerations keep using its old position.
- **Copy Points inherits the target's scale**, so greeble clouds are divided by
  `_typical_scale` of their target chain to land on Blender's absolute size
  while still collapsing with it.
- Scale expressions are lowered via `_comp_bounds` (random leaves taken at
  min/max), so products like `random(0.4, 1.6) * Size` keep varying per
  instance instead of collapsing to a constant.

## Path to the client plugin — done

1. ~~Wrap as a content-only UE plugin~~ → `GNueImporter` ships with two C++
   modules (GNueParams, GNuePCG) plus `Content/Python/init_unreal.py` (menu +
   GNueDrops auto-scan). Assemble it with `tools/sync_ue_plugin.py`.
2. ~~Blender N-panel addon~~ → `gnue_exporter/` (extension, Validate/Export).
3. Note: the repo already vendors a third-party `GeometryNodesBridge` plugin
   (live-sync/bake approach, currently disabled in the uproject) — different
   architecture from this descriptor/parametric approach; keep them separate.
