# GNue node roadmap — the path from 57 to 100+

**Where we are:** 57 supported nodes (51 in `V1_WHITELIST`, 6 in `V1X_WHITELIST`,
see [gnue_exporter/core.py](gnue_exporter/core.py)).

**Where this doc takes us:** 103 nodes, in four waves. Each wave is a coherent
capability, roughly a dozen nodes, and the count climbs 57 → 69 → 81 → 92 → 103.
Waves are independent — a wave can ship on its own, and nodes inside a wave can be
split across people (see [CONTRIBUTING.md](CONTRIBUTING.md)).

## The selection principle (read this first)

We add nodes that **fit the compiler model**: the exporter evaluates deterministic
parts into explicit points/instances (the numeric kernel) and leaves random /
proximity / noise to live PCG. Every node below is one of:

- **kernel** — pure math / attribute / curve maths, evaluated numerically. Cheapest.
- **bake** — generates explicit geometry we already know how to emit (like Mesh Cube).
- **live** — maps to a stock PCG node or a small custom node in the GNuePCG module.

We deliberately **do not** chase mesh-authoring operations — **Mesh Boolean,
Extrude Mesh, Subdivision Surface, Mesh to Volume, Distribute Points in Volume,
Volume to Mesh**. Those need real CSG / voxel / topology processing and produce a
unique output *mesh*, not a placement of instances — a different kind of tool
(that's the lesson from the *Stylized Rock Generator* graph). Leaving them out is a
scope decision, not a gap. If a rock-mesh workflow is ever needed in UE, the right
path is baking a static mesh or Geometry Script, not PCG.

> **idnames** below are Blender `bl_idname`s. Several are already confirmed against
> the live Blender socket (they showed up as "unsupported" in the rock-generator
> scan); the rest get confirmed at implementation time — one socket read per node,
> the recipe in CONTRIBUTING.md step 0.

---

## Wave 1 — Mesh & curve primitives (+12 → 69)  ·  **IN PROGRESS, two people**

Generators we bake to explicit geometry the way we already bake Mesh Cube / Mesh
Line / Curve Line. Highest "unblocks real graphs" value — primitives are everywhere.

**The split is by lowering path, so the two tracks touch disjoint code and have no
dependency on each other:**

- **Person A — mesh track (bake path).** All six ride the FBX-bake / asset-spec flow
  that `geo_GeometryNodeMeshCube` + `baked_asset` already use. A works only in the
  mesh-bake code and adds `geo_GeometryNodeMesh*` methods.
- **Person B — curve track (kernel path).** All six emit control points that feed the
  existing curve kernel (resample / trim / to-points). B works only in the curve /
  kernel code and adds `geo_GeometryNodeCurve*` methods.

Neither track's nodes consume the other's output, so A and B can work fully in
parallel and merge in any order.

### Person A — mesh primitives (bake) → +6

| Order | Node | idname | How it lowers | Effort |
|---|------|--------|---------------|--------|
| A1 (pattern-setter) | Cylinder | `GeometryNodeMeshCylinder` | bake | S |
| A2 | Cone | `GeometryNodeMeshCone` | bake | S |
| A3 | Ico Sphere | `GeometryNodeMeshIcoSphere` | bake | S |
| A4 | UV Sphere | `GeometryNodeMeshUVSphere` | bake | S |
| A5 | Grid | `GeometryNodeMeshGrid` | bake | S |
| A6 | Mesh Circle | `GeometryNodeMeshCircle` | bake | S |

Start with **Cylinder** — it has the representative parametric inputs (radius, depth,
segments), so it establishes the pattern the other five copy. Mesh primitives can
bake to an FBX asset spec (like Cube) *or*, for the low-poly ones, emit explicit
verts numerically — A picks one approach on A1 and reuses it.

### Person B — curve primitives (kernel) → +6

| Order | Node | idname | How it lowers | Effort |
|---|------|--------|---------------|--------|
| B1 (pattern-setter) | Curve Circle | `GeometryNodeCurvePrimitiveCircle` | kernel | S |
| B2 | Arc | `GeometryNodeCurveArc` | kernel | S |
| B3 | Quadrilateral | `GeometryNodeCurvePrimitiveQuadrilateral` | kernel | S |
| B4 | Star | `GeometryNodeCurvePrimitiveStar` | kernel | S |
| B5 | Spiral | `GeometryNodeCurveSpiral` | kernel | M |
| B6 | Bezier Segment | `GeometryNodeCurvePrimitiveBezierSegment` | kernel | M |

Start with **Curve Circle** — simplest control-point emitter; once it round-trips,
the others are variations. Do the two **M**-effort ones (Spiral, Bezier Segment)
last, after the pattern is proven.

### The one shared file — coordinate here

Both tracks add their idnames to `V1_WHITELIST` in
[gnue_exporter/core.py](gnue_exporter/core.py) — the only file both people touch. To
avoid a merge conflict:

- Add mesh idnames and curve idnames on **separate lines** of the set (A appends a
  "Wave 1 mesh" line, B appends a "Wave 1 curve" line). Git merges different lines
  cleanly.
- Whoever merges **first** just merges; the second **pulls `main`** before opening
  their PR so the whitelist is already up to date. No other file overlaps.

Everything else — the `geo_*` methods, the importer block handlers in
[import_gnue2.py](ue_importer/import_gnue2.py), and the `build_<node>.py` tests — is
per-node and per-track, so there's nothing else to coordinate.

## Wave 2 — Math, logic & field utilities (+12 → 81)

The cheapest wave — pure `expr()` / `evaluate()` extensions in the kernel, no new
geometry semantics. Unblocks the "wiring glue" that appears in almost every graph.

| # | Node | idname | How it lowers | Effort |
|---|------|--------|---------------|--------|
| 1 | Index Switch | `GeometryNodeIndexSwitch` | kernel (const/param selector) | S |
| 2 | Menu Switch | `GeometryNodeMenuSwitch` | kernel (const/param selector) | S |
| 3 | Vector Rotate | `ShaderNodeVectorRotate` | kernel | S |
| 4 | Float to Integer | `FunctionNodeFloatToInt` | kernel | S |
| 5 | Axis Angle to Rotation | `FunctionNodeAxisAngleToRotation` | kernel | S |
| 6 | Rotation to Euler | `FunctionNodeRotationToEuler` | kernel | S |
| 7 | Invert Rotation | `FunctionNodeInvertRotation` | kernel | S |
| 8 | Rotate Rotation | `FunctionNodeRotateRotation` | kernel | S |
| 9 | Evaluate on Domain | `GeometryNodeFieldOnDomain` | kernel/live | M |
| 10 | Evaluate at Index | `GeometryNodeFieldAtIndex` | kernel | M |
| 11 | Radius (input) | `GeometryNodeInputRadius` | kernel | S |
| 12 | Set ID | `GeometryNodeSetID` | kernel | S |

Switches only translate when the selector is a **constant or a parameter** (the
branch is decided at export). A field-driven switch stays refused — that's correct.

## Wave 3 — Geometry conversion & attribute sampling (+11 → 92)

Cheap conversions and the sampling nodes that let one geometry read another.

| # | Node | idname | How it lowers | Effort |
|---|------|--------|---------------|--------|
| 1 | Geometry to Instance | `GeometryNodeGeometryToInstance` | kernel/live | S |
| 2 | Bounding Box | `GeometryNodeBoundBox` | kernel | S |
| 3 | Set Shade Smooth | `GeometryNodeSetShadeSmooth` | bake flag (near no-op) | S |
| 4 | Mesh to Points | `GeometryNodeMeshToPoints` | kernel | S |
| 5 | Mesh to Curve | `GeometryNodeMeshToCurve` | kernel | M |
| 6 | Merge by Distance | `GeometryNodeMergeByDistance` | kernel (weld) | M |
| 7 | Flip Faces | `GeometryNodeFlipFaces` | bake flag | S |
| 8 | Sample Index | `GeometryNodeSampleIndex` | kernel | M |
| 9 | Sample Nearest | `GeometryNodeSampleNearest` | kernel | M |
| 10 | Attribute Statistic | `GeometryNodeAttributeStatistic` | kernel | M |
| 11 | Is Shade Smooth (read) | `GeometryNodeInputShadeSmooth` | kernel | S |

## Wave 4 — Curve editing & mesh reads (+11 → 103)

Rounds out the curve toolset (profiles, radius, cyclic) and the mesh-topology reads
that drive selections. **Curve to Mesh** is the marquee item — profile sweeps.

| # | Node | idname | How it lowers | Effort |
|---|------|--------|---------------|--------|
| 1 | Curve to Mesh | `GeometryNodeCurveToMesh` | kernel/bake | L |
| 2 | Fill Curve | `GeometryNodeFillCurve` | kernel | M |
| 3 | Fillet Curve | `GeometryNodeFilletCurve` | kernel | M |
| 4 | Set Curve Radius | `GeometryNodeSetCurveRadius` | kernel | S |
| 5 | Set Curve Tilt | `GeometryNodeSetCurveTilt` | kernel | S |
| 6 | Reverse Curve | `GeometryNodeReverseCurve` | kernel | S |
| 7 | Set Spline Cyclic | `GeometryNodeSetSplineCyclic` | kernel | S |
| 8 | Spline Length (input) | `GeometryNodeInputSplineLength` | kernel | S |
| 9 | Face Area (input) | `GeometryNodeInputMeshFaceArea` | kernel | S |
| 10 | Edge Angle (input) | `GeometryNodeInputMeshEdgeAngle` | kernel | M |
| 11 | Scale Elements | `GeometryNodeScaleElements` | kernel | M |

Effort key: **S** ≈ hours (one dispatch method + a test), **M** ≈ a day,
**L** ≈ multi-day (Curve to Mesh needs a profile-sweep kernel).

---

## Explicitly out of scope (the mesh-authoring nodes)

Refused on purpose — do not add these to reach the count:

`GeometryNodeMeshBoolean`, `GeometryNodeExtrudeMesh`,
`GeometryNodeSubdivisionSurface`, `GeometryNodeSubdivideMesh`,
`GeometryNodeMeshToVolume`, `GeometryNodeDistributePointsInVolume`,
`GeometryNodeVolumeToMesh`, `GeometryNodeDualMesh`.

These produce unique meshes via CSG / voxels / topology change — outside the
placement-and-instance model. If a real need appears, it's a separate track
(static-mesh bake or Geometry Script), not a whitelist entry.

## Tracking

The checkbox table lives in [CONTRIBUTING.md](CONTRIBUTING.md#claiming-work) so
two people never take the same node. Each node ships as its own small PR:
whitelist entry + lowering + importer handling + a `build_*.py` test + a line in
[deliverables/SUPPORTED_NODES.md](deliverables/SUPPORTED_NODES.md).
