# archive/prototypes — pre-V1 experiments (unmaintained)

Kept for provenance and as future test material; **not** part of the shipped
plugins or the dev loop, and not held to the repo's portability rules beyond
"no machine paths". Nothing here is run by any tool or test. See
`DECISIONS.md` D-010.

| File | What it is | Why it's kept |
|---|---|---|
| `create_spring_nodes.py` | Blender GN builder for the original **Card Spring** effect — the cardistry spring that started the project. | The origin story; the effect the interview film opens on. |
| `create_spring_niagara.py` | The Unreal-side counterpart as a hand-built **Niagara** system (UE 5.8.1, Python). | Documents the pre-descriptor approach that D-002/D-005 replaced. |
| `tentacle_gn.py` | Procedural tentacle builder using a **Repeat Zone** (Blender 5.1). | Repeat/Simulation Zones are unsupported by the exporter (no loop unrolling yet); this is a ready test case for when that lands. Writes its outputs next to itself. |
| `golden_bake.py` | "M1 golden-data bake": evaluates the depsgraph at fixed parameter values and dumps every instance transform to `golden.json`. | The validation idea behind the numeric kernel (D-002), before the exporter existed. |
| `export_raw_graph.py` | "M1 raw-graph layer": walks a GN group and dumps a structure-only `.gnue.json` (no evaluation). | Ancestor of `gnue_exporter/frontend_bpy.py:read_group`. |

The two `golden_bake` / `export_raw_graph` scripts came out of `downloadables/files.zip`
(removed; it also held a stale copy of the descriptor schema — the live one is `schema/`).
