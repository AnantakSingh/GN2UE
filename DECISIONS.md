# Decision log

Architectural decisions that shape GNue, with the reasoning — so a collaborator
can tell a deliberate constraint from an accident. Newest at the bottom.

**Adding an entry:** copy the template, give it the next `D-nnn`, and reference
it from the PR that implements it. Superseded decisions stay in the log with
their status changed; nothing is deleted.

```
## D-nnn · YYYY-MM-DD · Title
**Status:** accepted | superseded by D-mmm
**Context:** what forced the choice.
**Decision:** what we do.
**Consequences:** what that costs or commits us to.
```

---

## D-001 · 2026-08 · A deterministic compiler, not a guesser
**Status:** accepted
**Context:** Blender has 400+ Geometry Nodes; Unreal spreads the same work across
PCG, materials, Niagara and Blueprints. An "AI-ish" best-effort translation would
silently produce wrong effects.
**Decision:** a whitelisted node set that translates by fixed rules, and refusal
**by name** for everything else — nothing is approximated silently. Randomness is
*statistically* equivalent (same distributions), never identical.
**Consequences:** `deliverables/SUPPORTED_NODES.md` is the contract; the 412-node
atlas documents what everything else *would* map to. Growth is by adding rules
(`ROADMAP.md`), never by loosening the refusal.

## D-002 · 2026-08 · Numeric kernel at import; live PCG only where it must be
**Status:** accepted
**Context:** most of a GN graph is deterministic arithmetic over indices.
**Decision:** the importer evaluates deterministic sub-graphs numerically into
explicit points; only randomness, scatter, proximity and noise become running PCG
nodes.
**Consequences:** graph parameters are applied by **re-running the importer** —
an editor-time rebuild (~1 s), so they are authoring sliders, not runtime
channels (see D-005). Effects are exact where Blender is exact.

## D-003 · 2026-08 · V1.x features are gated by descriptor `requires` flags
**Status:** accepted
**Decision:** any node that needs new importer capability adds a feature flag to
the descriptor's `requires` list; an older importer refuses a newer export
cleanly instead of mis-importing it.

## D-004 · 2026-08 · Custom C++ PCG nodes where stock UE 5.8 nodes fail
**Status:** accepted
**Context:** UE 5.8's whole `PCGMetadata*` op family emits no data, and Spatial
Noise samples only X/Y.
**Decision:** ship *GNue Scale By Attribute* and *GNue Noise 3D* in the plugin's
`GNuePCG` module; the importer wires them automatically and degrades (banded
scale, 2D noise) when the module isn't compiled.
**Consequences:** C++ builds are part of the dev loop (`build_ue_plugin.ps1`);
Smart App Control must be off on Windows.

## D-005 · 2026-09-02 · Real-time motion lives on the GPU, not in PCG regeneration
**Status:** accepted
**Context:** proximity effects must react every frame; PCG regeneration hitches.
**Decision:** per-frame reactions (scale, spin, shake) are material World
Position Offset driven by a Material Parameter Collection that a world subsystem
updates each frame; PCG regenerates **only** when a Blender parameter changes.
**Consequences:** any smooth, triggered effect (e.g. a keypress-driven domino
topple) is built this way. Keyframing PCG parameters is not a path — see D-002.

## D-006 · 2026-09-02 · The road to 100 nodes excludes mesh-authoring nodes
**Status:** accepted
**Context:** the *Stylized Rock Generator* graph: Mesh Boolean, Mesh to Volume,
Distribute Points in Volume produce a unique *mesh*, not a placement of instances.
**Decision:** placement/instance/curve/math nodes are in scope; Boolean, Extrude,
Subdivision Surface and volume ops are out. A mesh-generation workflow belongs to
a static-mesh bake or Geometry Script, not PCG.

## D-007 · 2026-09-02 · Mesh primitives are baked instance sources
**Status:** accepted
**Decision:** Cylinder, Cone, Ico/UV Sphere, Grid, Mesh Circle are supported as
the *Instance* input of Instance on Points, baked to FBX at export-time
parameters through the generic bake path; using one directly as output geometry
is refused with guidance. Faceted shading (no smoothing groups) is accepted for
now — it matches Blender's default flat primitives.

## D-008 · 2026-09-02 · Never drive the live Unreal editor from scripts in loops
**Status:** accepted
**Context:** polling the editor over the MCP socket fork-bombed the machine more
than once (thousands of Python processes, RAM to zero).
**Decision:** automation uses single headless `UnrealEditor-Cmd` processes with
hard timeouts; Blender via headless runs or the single-shot `tools/bl_exec.py`.
Check `Get-Process python` before and after anything that spawns processes.

## D-009 · 2026-09-14 · No machine paths in source
**Status:** accepted
**Context:** the dev loop assumed one machine's layout (36 references, 21 files).
**Decision:** `tools/gnue_paths.py` resolves repo, UE project, engine, Blender and
version (explicit arg → `GNUE_*` env → `gnue.config.json` → auto-discovery →
actionable error). `blender_manifest.toml` is the single version source;
per-machine files are gitignored. Details: `PORTABILITY.md`.
**Consequences:** new scripts import the resolver or, inside Blender/Unreal, use
the host's own API (`__file__` / `GNUE_REPO`, `get_project_directory()`).

## D-010 · 2026-09-14 · Prototypes are archived, not deleted; this log replaces the transcript
**Status:** accepted
**Decision:** pre-V1 experiments live in `archive/prototypes/` (unmaintained, kept
for provenance and as future test cases); the raw planning transcript
(`nextstep.md`) is replaced by this decision log. Empty/unexplained blobs are
removed — git history keeps everything.
