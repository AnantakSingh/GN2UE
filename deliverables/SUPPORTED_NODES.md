# Supported Geometry Nodes — GNue 0.6.0

This is the exact set of Blender Geometry Nodes the exporter will translate to
Unreal, taken from the whitelists in `gnue_exporter/core.py` (the single source
of truth). **57 nodes**: 51 in the V1 core, plus a 6-node V1.x tier gated behind
descriptor feature flags.

**How translation works.** The bridge is a deterministic compiler, not an AI
guess. A graph exports only if *every* node in it is on this list; anything else
is **refused by name** in the export report — nothing is approximated silently.
Most nodes are evaluated by the importer's numeric kernel at import time (they
compute where the geometry ends up), and the parts that must stay live —
randomness, scatter, proximity, noise — become real PCG nodes in the generated
graph. Randomness is *statistically* equivalent to Blender (same distributions,
different exact placement), never identical.

Legend for the **In UE** column:
- **kernel** — evaluated numerically at import (baked into explicit points)
- **live PCG** — becomes a running node in the PCG graph
- **parameter** — surfaces as an editable value on the volume's Details panel

---

## V1 core (51 nodes)

### Group & input values
| Blender node | Menu | In UE |
|---|---|---|
| Group Input | *(node group interface)* | **parameter** — every input becomes an editable Graph Parameter |
| Group Output | *(node group interface)* | graph output |
| Boolean | Input > Constant | kernel |
| Integer | Input > Constant | kernel |
| Value | Input > Constant | kernel |
| Vector | Input > Constant | kernel |

### Attributes
| Blender node | Menu | In UE |
|---|---|---|
| Capture Attribute | Attribute | kernel |
| Store Named Attribute | Attribute | kernel (point-domain; instance/face-domain attrs are dropped with a note) |
| Named Attribute | Input > Attribute | kernel |
| ID | Input | kernel |
| Index | Input | kernel |
| Normal | Input | kernel |
| Position | Input | kernel |

### Geometry operations
| Blender node | Menu | In UE |
|---|---|---|
| Join Geometry | Geometry | kernel (merges point streams) |
| Set Position | Geometry > Write | kernel |
| Delete Geometry | Geometry > Operations | kernel |
| Duplicate Elements | Geometry > Operations | kernel |
| Separate Geometry | Geometry > Operations | kernel |
| Transform Geometry | Geometry > Operations | kernel (Y-mirror to UE's left-handed space) |
| Triangulate | Mesh > Operations | kernel |

### Curves
| Blender node | Menu | In UE |
|---|---|---|
| Curve Length | Curve > Read | kernel |
| Curve Tangent | Curve > Read | kernel |
| Spline Parameter | Curve > Read | kernel |
| Sample Curve | Curve > Sample | kernel (arc-length interpolation) |
| Set Spline Type | Curve > Operations | kernel (Catmull-Rom densified) |
| Curve to Points | Curve > Operations | kernel (aligns +Z to tangent, like Blender) |
| Resample Curve | Curve > Operations | kernel |
| Curve Line | Curve > Primitives | kernel |
| Points to Curves | Points | kernel |

### Instances
| Blender node | Menu | In UE |
|---|---|---|
| Instance on Points | Instances | kernel + **live PCG** Static Mesh Spawner |
| Instances to Points | Instances | kernel |
| Rotate Instances | Instances | kernel (deterministic runs folded into point frames; live random → Transform Points) |
| Scale Instances | Instances | kernel / **live PCG** (proximity- or noise-driven scale stays live) |
| Translate Instances | Instances | kernel |

### Mesh & points
| Blender node | Menu | In UE |
|---|---|---|
| Cube | Mesh > Primitives | baked FBX (deduped to a shared unit cube) |
| Mesh Line | Mesh > Primitives | kernel |
| Distribute Points on Faces | Point | **live PCG** Surface Sampler (or Mesh Sampler when the surface ships with the effect) |
| Points | Point | kernel |

### Utility & math
| Blender node | Menu | In UE |
|---|---|---|
| Switch | Utilities | kernel |
| Random Value | Utilities > Field | **live PCG** (Transform Points min/max range) or kernel series for random walks |
| Boolean Math | Utilities > Math | kernel |
| Clamp | Utilities > Math | kernel |
| Compare | Utilities > Math | kernel (also used to lower scatter masks) |
| Map Range | Utilities > Math | kernel (linear + smoothstep) |
| Math | Utilities > Math | kernel |
| Mix | Utilities | kernel |
| Vector Math | Utilities > Vector | kernel |
| Combine XYZ | Utilities > Vector | kernel |
| Separate XYZ | Utilities > Vector | kernel |
| Align Rotation to Vector | Utilities > Rotation | kernel |
| Euler to Rotation | Utilities > Rotation | kernel |

---

## V1.x tier (6 nodes)

These require a matching feature flag in the descriptor's `requires` list, so an
older importer refuses a newer export cleanly instead of mis-importing it.

| Blender node | Menu | Feature flag | In UE |
|---|---|---|---|
| Object Info | Input > Scene | `actor_binding` | **live PCG** — the referenced object becomes a tagged actor; tag any UE actor with its name to drive the effect live (proximity, etc.) |
| Noise Texture | Texture | `noise` | **live PCG** — lowered to the *GNue Noise 3D* node (true 3D Perlin; Unreal's stock Spatial Noise is 2D-only) |
| Realize Instances | Instances | `instance_surface_scatter` | kernel + scatter (enables greebles on instance surfaces) |
| Set Material | Material | `materials` | material name reference (a matching `/Game` material is applied if present) |
| Trim Curve | Curve > Operations | `trim` | kernel (arc-length clip) |
| Accumulate Field | Utilities > Field | `accumulate` | kernel series (prefix sums; seeded random walks — a new Seed regenerates the walk) |

---

## Custom UE nodes the importer builds for you

Two things Blender does that stock UE 5.8 PCG cannot, so the plugin ships them
as C++ nodes in the GNuePCG module and wires them up automatically:

- **GNue Noise 3D** — 3D Perlin FBM per point. UE's Spatial Noise samples only
  X/Y, which stripes on vertical surfaces; this matches Blender's Noise Texture.
- **GNue Scale By Attribute** — multiplies point scale by a per-point attribute.
  UE 5.8's stock Attribute Maths Op silently produces no output, so proximity/
  noise-driven scaling isn't possible with the shipped nodes without it.

If the GNuePCG module isn't compiled for your engine build, both fall back
(noise → 2D, proximity → stepped bands) with a note in the Output Log.

---

## Not on the list?

If your graph uses a node not shown here, the export is **refused** and the
export report names every offending node — it is never guessed at. To translate
it, either rebuild that part with supported nodes, or file it as a request. The
full 412-node Blender → UE translation atlas (`atlas/gn-ue-atlas.html`) shows
what each unsupported node *would* map to and why it isn't in V1 yet.

Known structural limits, independent of the node list:
- Nested node groups must be ungrouped/applied first (not yet inlined).
- Repeat Zone and Simulation Zone are not supported (no loop unrolling yet).
- Attributes on the instance or face domain are dropped (point domain only).
