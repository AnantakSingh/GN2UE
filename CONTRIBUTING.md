# Contributing & collaborating on GNue

How two or more people work on this project together without stepping on each
other. Pairs with [ONBOARDING.md](ONBOARDING.md) (what the project is) and
[ROADMAP.md](ROADMAP.md) (what we're building next).

---

## 1. The git workflow (small team, private repo)

We use one shared **private GitHub repo**, branch per task, review by pull request.

**One-time setup (per person)**
1. Get a (free) GitHub account; the repo owner invites you under
   **Settings → Collaborators**.
2. Install **GitHub Desktop** (easiest — no command line) *or* use `git` in the
   terminal. Either works; pick one.
3. **Clone** the repo, then read [ONBOARDING.md](ONBOARDING.md) §5 and stand up your
   own local Unreal project (the UE project is *not* in the repo — you regenerate it
   from the plugin).

**Every task**
1. **Pull** `main` first (get everyone's latest).
2. **Branch** off `main`: name it `node/ico-sphere`, `fix/garden-material`,
   `docs/roadmap` — one branch per node or fix.
3. Do the work. Commit in small, described steps.
4. **Push** the branch and open a **Pull Request** into `main`.
5. The other person reviews (see the checklist in §4), then **merge**.
6. Delete the branch. Pull `main` again before the next task.

**Rules that keep it clean**
- **`main` is always green** — it exports and imports without errors. Never commit
  work-in-progress straight to `main`; that's what branches are for.
- **Small PRs.** One node = one PR. A reviewer can read it in five minutes and the
  merge rarely conflicts.
- **Pull before you start, push when you pause.** Most conflicts come from a branch
  that sat for a week.
- Turn on **branch protection** for `main` (Settings → Branches → require a PR before
  merging) once there are two of you.

**GitHub Desktop mapping** (if you don't use the terminal): *Current Branch → New
Branch* = branch; *Commit to <branch>* + *Push origin* = push; *Preview Pull
Request* = open the PR; *Fetch/Pull* = pull. Same workflow, buttons instead of
commands.

## 2. What is and isn't in the repo

**In:** all source (`.py`, `.cpp`/`.h`, `.md`), build scripts (`tools/`), the atlas,
the schema, the demo `.blend`, and the shipped deliverable zips. The
[.gitignore](.gitignore) keeps out `__pycache__`, logs, and any UE
`Binaries/Intermediate/Saved/`.

**Out:** the live Unreal *project* under `Documents\Unreal Projects\GNtoUE` — it's
regenerated per-person from the plugin (`tools/sync_ue_plugin.py`). Only plugin
*source* is shared. Don't try to commit the whole UE project.

## 3. Claiming work

So two people never take the same node, **claim it before you start**: check the box
in the table below in a tiny `docs/claim` PR (or, once the repo has GitHub Issues on,
open one issue per node and assign yourself). The waves come from
[ROADMAP.md](ROADMAP.md).

### Wave 1 — primitives  ·  **assigned, in progress** (split in [ROADMAP.md](ROADMAP.md#wave-1--mesh--curve-primitives-12--69--in-progress-two-people))
- **Person A — mesh (bake):** [ ] Cylinder · [ ] Cone · [ ] Ico Sphere · [ ] UV Sphere · [ ] Grid · [ ] Mesh Circle
- **Person B — curve (kernel):** [ ] Curve Circle · [ ] Arc · [ ] Quadrilateral · [ ] Star · [ ] Spiral · [ ] Bezier Segment

### Wave 2 — math / logic / fields
- [ ] Index Switch · [ ] Menu Switch · [ ] Vector Rotate · [ ] Float to Integer
- [ ] Axis Angle to Rotation · [ ] Rotation to Euler · [ ] Invert Rotation · [ ] Rotate Rotation
- [ ] Evaluate on Domain · [ ] Evaluate at Index · [ ] Radius · [ ] Set ID

### Wave 3 — conversion / sampling
- [ ] Geometry to Instance · [ ] Bounding Box · [ ] Set Shade Smooth · [ ] Mesh to Points
- [ ] Mesh to Curve · [ ] Merge by Distance · [ ] Flip Faces · [ ] Sample Index
- [ ] Sample Nearest · [ ] Attribute Statistic · [ ] Is Shade Smooth

### Wave 4 — curve editing / mesh reads
- [ ] Curve to Mesh · [ ] Fill Curve · [ ] Fillet Curve · [ ] Set Curve Radius
- [ ] Set Curve Tilt · [ ] Reverse Curve · [ ] Set Spline Cyclic · [ ] Spline Length
- [ ] Face Area · [ ] Edge Angle · [ ] Scale Elements

**Good split for two people:** one takes Wave 1 (bake/primitives), the other takes
Wave 2 (pure kernel math). They touch almost disjoint code, so PRs won't conflict.

## 4. The recipe: adding one node

Every node touches the same handful of places. Follow it end to end for one node
before starting the next.

**Step 0 — confirm the idname.** In the open Blender, read the node's real
`bl_idname` (drop the node in a graph, run a one-line socket read, or check an
existing graph that uses it). The ROADMAP idnames are our best guess; verify before
you code against them.

**Step 1 — whitelist it.** Add the idname to `V1_WHITELIST` (core set) or a new tier
in [gnue_exporter/core.py](gnue_exporter/core.py). If it changes the descriptor
contract, bump `DESCRIPTOR_VERSION` and add a `requires` feature flag so old
importers refuse gracefully (that's what `V1X_WHITELIST` does today).

**Step 2 — lower it.**
- **Geometry node** → add a `geo_GeometryNodeXxx(self, nname, nd)` method to the
  emitter in [core.py](gnue_exporter/core.py) (the dispatch is by method name — see
  `geo_GeometryNodeMeshLine`, `geo_GeometryNodeInstanceOnPoints` as models). It emits
  a descriptor **block**.
- **Math / function node** → extend `expr()` / `evaluate()` in
  [core.py](gnue_exporter/core.py) (see how `ShaderNodeMath` / `FunctionNodeCompare`
  are handled). No new block — it's an expression tree node.
- **Bake node** (a primitive) → produce an asset spec like
  `geo_GeometryNodeMeshCube` / `baked_asset` does.

**Step 3 — import it in UE.** Add the matching block handler in
[ue_importer/import_gnue2.py](ue_importer/import_gnue2.py) so the new block kind
builds real PCG nodes / geometry. Keep deterministic parts in the numeric kernel;
push random/proximity/noise to live PCG nodes.

**Step 4 — prove it end to end.** Add a `build_<node>.py` next to the existing
`build_v1_*.py` / `build_prox*.py` that builds a tiny Blender graph using the node,
exports it, and imports it headless. **Headless only** — never drive the live editor
in a loop (see the footgun in ONBOARDING §9). Confirm the effect appears.

**Step 5 — document it.** Add a row to
[deliverables/SUPPORTED_NODES.md](deliverables/SUPPORTED_NODES.md) and, if it's a
notable capability, the atlas. Bump the node count.

**Step 6 — PR.** Push the branch, open the PR, fill the checklist below.

## 5. PR review checklist

Before requesting review, and what the reviewer checks:

- [ ] `build_<node>.py` runs clean: exports **and** imports headless, effect visible.
- [ ] Unsupported inputs are **refused with a clear message**, never silently guessed
      (e.g. a field-driven switch, an unsupported domain).
- [ ] No new node runs the **live UE editor in a loop** (fork-bomb rule).
- [ ] `SUPPORTED_NODES.md` updated; count bumped; `requires` flag added if the
      descriptor changed.
- [ ] Existing tests still pass (run a couple of `build_v1_*.py`).
- [ ] C++ changes only: built with **Smart App Control OFF** (see §6), binaries
      rebuilt, editor opens with 0 load errors.

## 6. Two footguns that will bite a new collaborator

1. **Smart App Control (SAC) must be OFF to build C++.** With it on, freshly built
   DLLs and UBT assemblies are blocked (error `0x800711C7`, "module could not be
   loaded"). Windows Security → App & browser control → Smart App Control → Off.
   Pure-Python node work (Waves 1–2 mostly) doesn't need C++ builds at all.
2. **Never tight-loop the live Unreal editor over the MCP socket.** It has fork-bombed
   the machine (thousands of python processes, RAM to near zero) more than once. Use
   the **headless** path (`UnrealEditor-Cmd -run=pythonscript`, one process) for
   automated tests. Blender's socket on 9876 is single-shot and safe. If you ever see
   python process count climbing, `taskkill /F /IM python.exe` and check
   `Get-Process python` first.

## 7. Coordination cadence

- **Before a work session:** glance at the claim table (§3) and pull `main`.
- **Daily:** each person's open PRs are the status board — no separate standup needed
  at this size.
- **Weekly:** merge outstanding PRs, re-tag a deliverable if the node count moved
  (`python tools/make_deliverables.py`), update the roadmap checkboxes.
- **Decisions that change the descriptor or the whitelist tiers** get written down —
  a short note in [nextstep.md](nextstep.md) or the PR description — so the reasoning
  survives.
