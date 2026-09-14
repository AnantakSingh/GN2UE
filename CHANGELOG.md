# Changelog

All notable changes to GNue are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/); the project versions the
deliverable plugins (see `deliverables/`). Each entry is a milestone that is
committed and **pushed to the private GN2UE repo as a backup**.

Node count is the running total of supported Blender nodes (see
[deliverables/SUPPORTED_NODES.md](deliverables/SUPPORTED_NODES.md) and
[ROADMAP.md](ROADMAP.md)).

## [Unreleased] — Portability (see PORTABILITY.md)

### Added
- `tools/gnue_paths.py` — one resolver for repo / UE project / engine / Blender /
  version: explicit arg → `GNUE_*` env → `gnue.config.json` → auto-discovery →
  actionable error. Engine discovery is keyed on the `.uproject`'s
  `EngineAssociation`; project discovery requires the GNue plugin or `GNueDrops/`.
- `gnue.config.example.json` (per-machine config template) and `LICENSE` (MIT).
### Changed
- `.claude/settings.local.json` untracked (per-machine); `gnue.config.json` and
  `export/primzoo/` gitignored.
- Lane A: `sync_ue_plugin.py`, `build_ue_plugin.ps1` (UBT target derived from the
  `.uproject`; `-DryRun`), `make_deliverables.py` (`--dry-run`; refuses to package on
  version drift), `run_import.ps1` (`-DryRun`) take their paths from the resolver.
  `bl_info` version corrected 0.4.0 -> 0.7.0.

## Wave 1 primitives — merged to `main` in PR #1

Person A track: mesh primitives added as baked instance sources. The exporter's
`bake_subgraph` and the importer's FBX asset loop are already generic, so each
primitive is unblocked by whitelisting it and proven with an end-to-end
`build_<prim>.py` test.

### Added
- **Cylinder** (`GeometryNodeMeshCylinder`) — node **58/100**. Supported as a
  baked instance source via the generic `bake_subgraph` path; recognised by a new
  `BAKED_PRIMITIVES` set in `core.py` (wired into validation and the dead-branch
  check). Proven end-to-end by `build_cylinder.py` (headless Blender export →
  real 11 KB FBX + `instance.on_points` block, no false warnings). Direct
  (non-instanced) geometry use is refused with a clear message.

- **Cone, Ico Sphere, UV Sphere, Grid, Mesh Circle** (`GeometryNodeMeshCone`,
  `…MeshIcoSphere`, `…MeshUVSphere`, `…MeshGrid`, `…MeshCircle`) — nodes
  **59–63/100**. Same baked-instance-source mechanism as Cylinder; added to
  `BAKED_PRIMITIVES`. Proven by `build_mesh_primitives.py`, the parameterized
  Person A regression test (headless Blender, **6/6 PASS**, real FBX for each).
  **Person A's Wave 1 mesh track is complete (57 → 63).**

### Fixed
- **`MeshLine` now imports** — added the missing `k_point_line` kernel handler in
  `import_gnue2.py`. `GeometryNodeMeshLine` emits a `point.line` block, but the
  importer had no handler (only `point.create` for `GeometryNodePoints`), so any
  effect using Mesh Line as its points source refused at import with
  `no handler for point.line`. Surfaced by importing the primitive test effects
  into UE. Handler places point `i` at `start + offset*i` (Offset mode).

### Verified in Unreal (headless, single-process — no MCP)
- **PrimZoo** (`build_primzoo.py`, all six primitives in one effect) imported into
  UE 5.8: all 6 FBX → real `StaticMesh` assets, PCG graph `PCG_PrimZoo` built
  (12 nodes, 6 instance groups), **GNUE2 IMPORT RESULT: PASS**, no errors.
- **CylTestA** (Mesh Line path) re-imported after the `k_point_line` fix:
  **PASS**, `counts=[6]` (6 cylinders along the line). Confirms both points
  sources (`point.create`, `point.line`) round-trip.

### Known / deferred
- Baked primitives import **faceted** (FBX carries no smoothing groups) — matches
  Blender's default flat GN primitives; smooth-shading export deferred by choice.
- `GeometryNodeTransform` has no general geometry rule (only the instance-source
  origin-shift case); move points with `Set Position` instead. Pre-existing.
- The **deliverable plugin's** bundled importer copy still needs a re-sync
  (`tools/sync_ue_plugin.py`) to carry the `k_point_line` fix before the next
  packaged release.

### Infrastructure
- Added this **CHANGELOG.md** as the milestone/backup ledger.
- Branch `person-a/wave1-mesh-primitives` for the Person A track.
- `build_mesh_primitives.py` (export regression) and `build_primzoo.py`
  (UE import verification, all six primitives) — the Person A test artifacts.

---

## [0.7.0] — baseline (initial commit `9340861`)

The state at repo creation: Blender exporter add-on + UE 5.8 importer plugin,
57 supported nodes (51 V1 core + 6 V1.x), deterministic compiler + numeric
kernel, live proximity dynamics layer (spin/shake/scale), deliverable zips,
node atlas, and the collaboration docs (ONBOARDING / CONTRIBUTING / ROADMAP).
