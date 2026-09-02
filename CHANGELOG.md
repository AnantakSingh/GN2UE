# Changelog

All notable changes to GNue are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/); the project versions the
deliverable plugins (see `deliverables/`). Each entry is a milestone that is
committed and **pushed to the private GN2UE repo as a backup**.

Node count is the running total of supported Blender nodes (see
[deliverables/SUPPORTED_NODES.md](deliverables/SUPPORTED_NODES.md) and
[ROADMAP.md](ROADMAP.md)).

## [Unreleased] — Wave 1 primitives (branch `person-a/wave1-mesh-primitives`)

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

### Infrastructure
- Added this **CHANGELOG.md** as the milestone/backup ledger.
- Branch `person-a/wave1-mesh-primitives` for the Person A track.

---

## [0.7.0] — baseline (initial commit `9340861`)

The state at repo creation: Blender exporter add-on + UE 5.8 importer plugin,
57 supported nodes (51 V1 core + 6 V1.x), deterministic compiler + numeric
kernel, live proximity dynamics layer (spin/shake/scale), deliverable zips,
node atlas, and the collaboration docs (ONBOARDING / CONTRIBUTING / ROADMAP).
