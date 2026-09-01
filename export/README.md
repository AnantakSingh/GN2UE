# SpineTree export package (GN→UE, static_scatter family)

Exported from `SimpleGeoNodes.blend` / node group `SpineTreeGN` (Blender 5.2),
realized in UE 5.8 as a **parametric PCG graph** (decision 2026-08-12: live
sliders in UE over instance-identical geometry; Blender's RNG cannot be
reproduced, so equivalence is *statistical*, not per-instance).

## Files

| File | What |
|---|---|
| `spinetree.gnue.json` | Descriptor — `blocks` (semantic IR, 3 blocks) + `raw_graph` (full node dump). Regenerate with `python ../exporter_spinetree.py` while Blender runs with the blender-mcp addon. |
| `SM_SpineCube.fbx` | Unit 1m cube, simple subdivision level 2 (96 polys). Scaled per instance by the graph. |
| `SM_TreeLeaf.fbx` | Leaf plane + petiole assembly authored at Leaf Size = 1 (all leaf dimensions are linear in Leaf Size, so a uniform scale reproduces every size). |

## What was built in UE (project GNtoUE)

- `/Game/SpineTree/Meshes/SM_SpineCube`, `SM_TreeLeaf` — imported FBX (auto cm conversion verified: cube 100cm, leaf 140×33×7cm)
- `/Game/SpineTree/PCG_SpineTree` — PCG graph, built via the unreal-mcp PCG toolset:

```
SpineOrigin (Create Points, 1 pt)
  → SpineStack (Duplicate Point, iterations=SpineSegments-1, +60cm Z each;
                NOTE: direction must be (0,0,0) — non-zero direction adds the
                point bounds (100cm) to the spacing)
  → SpineWander (Transform Points, random offset/point:
                 min (-50,-50,-5) max (50,50,20) cm = Blender walk step × Wander 0.5;
                 independent jitter, not an accumulated walk)
  → SpineSpline (Create Spline, curved)
      → CubeSampler (Spline Sampler, NumberOfSamples=10, unbounded, SeedFromIndex)
        → CubeScale (Transform Points, absolute scale (1.17, 0.22, 0.22),
                     bUniformScale=false — defaults to true and silently uses X only)
        → CubeSpawner (Static Mesh Spawner → SM_SpineCube)
      → LeafSampler (Spline Sampler, NumberOfSamples=48, unbounded, SeedFromIndex)
        → LeafChance (Attribute Noise, Set $Density 0–1)
        → LeafFilter (Density Filter, keep ≤ 0.35)
        → LeafOrient (Transform Points, absolute rotation yaw 0–360°,
                      tilt roll ±25.8°, pitch −51.6°..11.5°, uniform scale 0.6)
        → LeafSpawner (Static Mesh Spawner → SM_TreeLeaf)
```

- Level `Lvl_FirstPerson` has a `SpineTree_PCG` PCGVolume instance; verified
  executing: 12 spine points, 10 cubes at scale (1.17, 0.22, 0.22),
  18/48 leaves kept (~0.35 ✓).

Mesh assignment on Static Mesh Spawners is not settable through AddNode
jsonParams — it lives on the instanced selector object
(`<node>.PCGStaticMeshSpawnerSettings_N.DefaultSelectorInstance.meshEntries`),
set via ObjectTools.set_properties.

## Graph parameters (declared on the graph, per-instance overridable)

Seed, SpineSegments, Wander, CubeCount, CubeThickness, CubeLength, LeafPoints,
LeafProbability, LeafSize — Blender names and default values.

## Known gaps / TODO

1. **Params are declared but not yet wired to node properties** — node values
   are baked to the Blender defaults. Wiring = per-node property override pins
   fed from Get Graph Parameter (or UpdateNode on instances).
2. **Cube length formula** `max(1.5·splineLen/(CubeCount−1), CubeLength)` is
   baked as 1.17 for the default spline length (~7m); needs an attribute-math
   chain (Attribute Reduce on SplineDistance → maths → $Scale.x).
3. **Spine is jitter, not an accumulated random walk** — no native prefix-sum
   in PCG; Custom HLSL kernel could do it exactly (shader source property not
   exposed via MCP schema).
4. Handedness (Y-negation) not applied — irrelevant for seeded-random output,
   revisit if an effect ever bakes exact positions.
5. Leaves render dark: no material assigned (thin plane backface with default
   material). Assign a two-sided material to SM_TreeLeaf.
6. ~~PCG plugin is **not** in `GNtoUE.uproject`~~ — **done 2026-08-13**: `PCG`
   and `PythonScriptPlugin` added to the uproject (needed for the headless
   importer; also fixes cooking/standalone).

## No-MCP import path (2026-08-13)

`../ue_importer/import_gnue.py` rebuilds this whole package from the descriptor
using UE's native Python — no MCP server. Headless-verified: 12 nodes, 11/11
edges at `/Game/GNueImport/SpineTreeGN/PCG_SpineTreeGN` (non-destructive; the
hand-built `/Game/SpineTree/` assets are untouched). It also assigns a
two-sided material to the leaf mesh (gap #5, for the imported copy). See
`../ue_importer/README.md`.
