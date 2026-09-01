# V1 core node set (53 nodes)

Source of truth: `gnue_map_data.js` rows with `v1: 1` (regenerate with:
`node -e` filter on `r.v1===1`). Criterion: exact/close fidelity AND low
complexity AND exercised (or directly implied) by the proven descriptor
families — `static_scatter` (SpineTree) and `curve-travel`.

Fidelity: E = exact, C = close (unit/axis/RNG conversion applies).

## Inputs & parameters (4)
| Node | Fid | UE |
|---|---|---|
| Boolean | E | Create Attribute / graph parameter |
| Integer | E | Create Attribute / graph parameter |
| Value | E | Create Attribute / graph parameter |
| Vector | E | Create Attribute / graph parameter (m→cm, handedness) |

## Attributes (2)
| Capture Attribute | C | implicit — PCG metadata persists on points |
| Store Named Attribute | E | Attribute Set / Create Attribute |

## Geometry (12)
| Geometry Input | C | PCG Input node / volume bounds |
| Join Geometry | E | Merge (PCG) / AppendMesh (GS) |
| ID | C | $Seed |
| Index | C | implicit index / seed-from-index |
| Named Attribute | E | Get Attribute |
| Normal | C | point orientation (transform up axis) |
| Position | E | $Position |
| Set Position | E | Transform Points / Attribute Set |
| Delete Geometry | C | Point/Density Filter |
| Duplicate Elements | C | Duplicate Point (direction (0,0,0)!) |
| Separate Geometry | C | Point Filter, two outputs |
| Transform Geometry | E | Transform Points / GS ApplyTransform |

## Curves (8)
| Curve Length | C | spline length (sampler distance attrs) |
| Curve Tangent | C | Spline Sampler orientation (UE X = tangent) |
| Spline Parameter | E | sampler alpha/distance |
| Sample Curve | E | Spline Sampler |
| Set Spline Type | C | Create Spline linear flag |
| Curve to Points | E | Spline Sampler count/distance |
| Resample Curve | C | sample + rebuild spline |
| Curve Line | E | two-point spline |

## Instances (6)
| Instance on Points | E | Static Mesh Spawner |
| Instances to Points | E | trivial (transforms are points upstream) |
| Randomize Transforms | E | Transform Points random min/max |
| Rotate Instances | E | Transform Points (rotation) |
| Scale Instances | E | Transform Points (uniform_scale gotcha) |
| Translate Instances | E | Transform Points (offset) |

## Mesh (3 — bake-friendly)
| Triangulate | E | implicit (UE meshes are triangles) |
| Cube | E | GS AppendBox / bake to FBX (SM_SpineCube) |
| Mesh Line | C | Duplicate Point stack (SpineTree spine) |

## Points (3)
| Distribute Points on Faces | C | Surface/Mesh Sampler (statistical RNG) |
| Points | E | Create Points / Grid |
| Points to Curves | C | Create Spline from points |

## Utilities (14)
| Switch | C | Branch / Select |
| Random Value | C | Attribute Noise / seeded random (statistical) |
| Boolean Math | E | attribute boolean ops |
| Clamp | E | attribute clamp |
| Compare | E | Attribute Compare / Filter |
| Map Range | C | Attribute Remap / composed ops |
| Math | C | Attribute Maths Op (~40 float ops) |
| Mix | E | attribute lerp |
| Vector Math | C | attribute vector ops |
| Combine XYZ | E | make-vector |
| Separate XYZ | E | break-vector |
| Mix Vector | E | attribute lerp |
| Align Rotation to Vector | C | rotator ops (axis permute) |
| Euler to Rotation | C | rotator make (rad→deg + axis mapping) |

## Generate (1)
| Scatter on Surface | C | Surface Sampler + spawner (= static_scatter family) |

## Notes
- Every row is PCG-only except Join/Delete/Transform Geometry (GS variant for
  mesh data), Triangulate, and Cube — and those are covered by the FBX-bake
  policy in practice.
- The 53 are the *translator's* target list: descriptor block types + importer
  builders. SpineTree already exercises ~20 of them end to end.
- Nearest upgrades once these are done (V1.x, 70 nodes): Object Info /
  actor binding, Image Texture density masks, Trim Curve, Repeat Zone loops,
  Accumulate Field (one HLSL kernel), Distribute Points in Volume, material
  references.
