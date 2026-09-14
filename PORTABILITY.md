# Portability — removing hardcoded machine dependencies

**Status:** approved 2026-09-14 (review amendments folded in), **in progress** — Task 1
landed in PR #2. **Owner:** Person A. **Blocks:** every new collaborator, the V0
public release, and any CI.

GNue was built on one machine, and the build/test tooling still assumes that
machine's layout: a repo at `C:\Projects\GNtoUEresearch`, a UE project at
`C:\Users\User\Documents\Unreal Projects\GNtoUE`, and an engine at
`C:\Program Files\Epic Games\UE_5.8`. **36 references** across 21 files encode
those three paths (revised on review — the three newest test scripts were missing
from the first pass; see C7).

The two shipped plugins are fine — the Blender extension and the UE plugin are
both fully relocatable. What breaks is the **developer loop**: syncing the
plugin, building the C++, running the headless tests, and packaging a release.
A second person cannot currently do any of those without editing source.

This doc is the plan to fix that. It pairs with [ONBOARDING.md](ONBOARDING.md)
(§4 environment, §5 dev loop) and [CONTRIBUTING.md](CONTRIBUTING.md).

---

## 1. What's actually wrong

Three distinct machine-specific values, each needed by a different runtime:

| Value | Who needs it | How it's found today |
|---|---|---|
| **Repo root** | Blender-side scripts run over the socket (`exec(open(...))` — no `__file__`) | hardcoded absolute path |
| **UE project dir** | `sync_ue_plugin.py`, `build_ue_plugin.ps1`, `make_deliverables.py`, all 5 headless tests | hardcoded absolute path |
| **Engine root** | `build_ue_plugin.ps1`, `run_import.ps1` | hardcoded absolute path |

Two of these are already solved *somewhere* in the codebase — the fixes just
weren't applied consistently:

- [`ue_importer/run_import.ps1:11-15`](ue_importer/run_import.ps1) takes
  `-Project` and `-Engine` as **parameters** with defaults. Right shape, wrong
  defaults.
- [`ue_plugin_src/RebuildBinaries.bat:14`](ue_plugin_src/RebuildBinaries.bat)
  **auto-discovers the engine from the Windows registry** and only falls back to
  the Program Files path. This is the correct approach and should be lifted into
  the shared resolver. **Caveat found on review:** on the original machine
  `HKLM\SOFTWARE\EpicGames\Unreal Engine` registers `4.0` and `5.7` but **not
  `5.8`** — the engine the project actually uses — so the per-version key alone
  misses and the `.bat` only survives via its fallback. The parent key's
  `INSTALLDIR` *is* present, so the resolver also tries
  `INSTALLDIR\UE_<EngineAssociation>` before Program Files.
- [`tools/plugin_init_unreal.py:16-19`](tools/plugin_init_unreal.py) `_drops_dir()`
  resolves `GNueDrops` from `unreal.SystemLibrary.get_project_directory()` —
  correct, and exactly what the five headless tests should be doing.

There is also already a **`GNUE_*` environment variable convention** in use
(`GNUE2_DIR`, `GNUE_DEST`, `GNUE_DESCRIPTOR`, `GNUE_DECLARE_PCG`). The design
below extends it rather than inventing a new mechanism.

---

## 2. Proposed design

### 2.1 One resolver module: `tools/gnue_paths.py`

A new, dependency-free module that every repo-side Python script imports. It
resolves each value in a fixed order and fails with an *actionable* message:

```
1. explicit argument    (CLI arg / function parameter)
2. environment variable (GNUE_UE_PROJECT, GNUE_ENGINE, GNUE_BLENDER, GNUE_REPO)
3. gnue.config.json     (repo root, gitignored, per-machine)
4. auto-discovery       (registry for the engine; repo root from __file__)
5. clear error          "Set GNUE_UE_PROJECT or create gnue.config.json — see PORTABILITY.md"
```

Proposed API (keep it small):

| Function | Returns |
|---|---|
| `repo_root()` | this repo (from `__file__` — always knowable) |
| `ue_project()` | directory containing the `.uproject` |
| `uproject()` | full path to the `.uproject` file (glob inside `ue_project()`) |
| `project_name()` | `.uproject` basename, e.g. `GNtoUE` |
| `editor_target()` | `f"{project_name()}Editor"` — **derived, never hardcoded** |
| `engine_root()` | UE install directory |
| `unreal_cmd()` | `engine_root()/Engine/Binaries/Win64/UnrealEditor-Cmd.exe` |
| `unreal_editor()` | `.../UnrealEditor.exe` (interactive) |
| `engine_association()` | `EngineAssociation` from the `.uproject` (`5.8`, or a GUID for source builds) — keys engine discovery so a multi-engine machine never builds against the wrong one |
| `blender_exe()` | `blender.exe` — newest `Blender Foundation/Blender X.Y` unless configured |
| `plugin_dir()` | `ue_project()/Plugins/GNueImporter` |
| `drops_dir()` | `ue_project()/GNueDrops` |
| `version()` | single source of truth — parsed from `blender_manifest.toml` |

Engine auto-discovery, keyed on the `.uproject`'s `EngineAssociation`:
1. `HKLM\SOFTWARE\EpicGames\Unreal Engine\<assoc>` → `InstalledDirectory`
2. `HKLM\SOFTWARE\EpicGames\Unreal Engine` → `INSTALLDIR` + `UE_<assoc>` (§1 caveat)
3. `HKCU\Software\Epic Games\Unreal Engine\Builds` (`<GUID> = <path>`, source builds)
4. `%ProgramFiles%\Epic Games\UE_<assoc>`

Project auto-discovery: scan `~/Documents/Unreal Projects/*` (and the OneDrive
variant) for a folder with a `.uproject` **and** either `Plugins/GNueImporter` or
`GNueDrops/`. Exactly one match wins; several → an error listing them. (The
original machine has six UE projects, so a bare "first `.uproject`" rule would
misfire.)

`python tools/gnue_paths.py` prints everything it resolves and exits non-zero if
the project or engine can't be found; `python tools/gnue_paths.py engine_root`
prints one value, which is how the `.ps1` scripts consume it.

### 2.2 Per-machine config: `gnue.config.json`

Gitignored, at repo root. Commit a `gnue.config.example.json` next to it.

```json
{
  "ue_project": "C:/Users/<you>/Documents/Unreal Projects/GNtoUE",
  "engine":     "C:/Program Files/Epic Games/UE_5.8",
  "blender":    "C:/Program Files/Blender Foundation/Blender 5.2"
}
```

Every key optional — omit anything auto-discovery or an env var already covers.

### 2.3 UE-side scripts do NOT use the resolver

Scripts running *inside* Unreal (`tools/test_*.py`, `tools/refresh_cubefield.py`)
cannot import from the repo. They must use the engine's own API:

```python
import os, unreal
DROPS = os.path.join(unreal.SystemLibrary.get_project_directory(), "GNueDrops")
FOLDER = os.path.join(DROPS, "cubefield_fx")
```

This is what `plugin_init_unreal.py:_drops_dir()` already does. Consider a tiny
shared `tools/ue_testlib.py` so the five tests don't each re-derive it.

### 2.4 Blender-side scripts take the repo root from the caller

`export_cli.py` and the `build_*.py` scripts are `exec()`'d over the socket, so
`__file__` is unset — that is the real reason they hardcode. They already read
caller-injected globals (`GNUE_GROUP`, `GNUE_OUT`); extend the same pattern:

```python
REPO = (globals().get("GNUE_REPO") or os.environ.get("GNUE_REPO")
        or (os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else None))
if not REPO:
    raise RuntimeError("set GNUE_REPO before exec'ing this script — see PORTABILITY.md")
```

The `__file__` fallback matters (adjust the `dirname` depth per file):
`blender --background --python build_x.py` — how the Wave 1 tests are verified —
*does* set `__file__`, so headless runs need zero config. Only the socket-exec
path needs `GNUE_REPO`, and `tools/bl_exec.py` (C8) injects it.

The docstring examples at the top of each `build_*.py` should show
`GNUE_REPO = r'<your repo>'` rather than a literal `c:/Projects/...`.

---

## 3. Task breakdown

Sized to be split across people. **Task 1 lands first** (everything else imports
it); after that, lanes A, B and C touch disjoint files and can go in parallel.

### Task 1 — the resolver (pattern-setter, do this first) · M

- [x] Add `tools/gnue_paths.py` implementing §2.1.
- [x] Add `gnue.config.example.json`; add `gnue.config.json` to `.gitignore`.
- [x] Unit-check: `python -c "import tools.gnue_paths as p; print(p.ue_project(), p.engine_root(), p.editor_target())"`
      resolves on a machine with **no** env vars and **no** config (auto-discovery),
      and gives a readable error when the project genuinely can't be found.

### Lane A — build & packaging scripts

- [x] **A1** `tools/sync_ue_plugin.py:22` — replace the hardcoded default with
      `gnue_paths.ue_project()`; keep `argv[1]` as the highest-priority override.
- [x] **A2** `tools/build_ue_plugin.ps1:10-11` — add `param([string]$Engine, [string]$Project)`
      following [`run_import.ps1`](ue_importer/run_import.ps1)'s shape. When not passed,
      shell out to the resolver rather than duplicating discovery logic:
      `python -c "import tools.gnue_paths as p; print(p.engine_root())"`.
      **Also line 24:** `GNtoUEEditor` is a hardcoded build target — derive it from the
      `.uproject` name (`editor_target()`). This is the one that silently breaks for
      anyone whose UE project isn't literally called `GNtoUE`.
- [x] **A3** `tools/make_deliverables.py:15` — take the plugin dir from
      `gnue_paths.plugin_dir()`.
- [x] **A4** `tools/make_deliverables.py:16` — **kill the duplicated version string.**
      `0.7.0` currently lives in three places (`make_deliverables.py:16`,
      `sync_ue_plugin.py:140`, `blender_manifest.toml:4`) and a *fourth,
      already-stale* one: `gnue_exporter/__init__.py:9` still says `(0, 4, 0)`.
      Make `blender_manifest.toml` the single source and have the others read it.
      Fixes the drift and removes a step from the release checklist.
- [x] **A5** `ue_importer/run_import.ps1:13-14` — swap the hardcoded defaults for
      resolver lookups (parameter shape is already correct).

### Lane B — headless test scripts

All five use `unreal.SystemLibrary.get_project_directory()` per §2.3. No resolver
dependency, so this lane can start immediately alongside Task 1.

- [ ] **B1** `tools/test_cubefield_import.py:11`
- [ ] **B2** `tools/test_domino_rotations.py:6`
- [ ] **B3** `tools/test_params_headless.py:6`
- [ ] **B4** `tools/test_walktrim_import.py:6`
- [ ] **B5** `tools/refresh_cubefield.py:7`
- [ ] **B6** Optional: factor the shared line into `tools/ue_testlib.py`.

> These tests also depend on specific drop folders (`cubefield_fx`, `Domino`,
> `ropebridge_v1`, `walktrim_test`) existing in *someone's* `GNueDrops`. Fixing
> the paths makes them runnable; making them **reproducible** means each test
> should point at a fixture in the repo (`export/`) or skip with a clear message
> when its folder is absent. Worth doing in the same pass.

### Lane C — Blender-side, docs, hygiene

- [ ] **C1** `gnue_exporter/export_cli.py:3,14,25` — `GNUE_REPO` per §2.4; make the
      default output `<repo>/export/ropebridge_v1` relative.
- [ ] **C2** `build_v1_bridge.py:4`, `build_v1_stonecircle.py:4` — update the docstring
      exec examples to use `GNUE_REPO`.
- [ ] **C3** `ue_importer/import_gnue.py:5,7` and `ue_importer/README.md:34` — docstring
      paths → `<repo>/ue_importer/import_gnue.py`.
- [ ] **C4** **Repo identity.** Docs call this repo `GNtoUEresearch` at
      `C:\Projects\GNtoUEresearch`; it is actually **GN2UE**. Fix
      `ONBOARDING.md:93,95,104,105,125` and `ue_plugin_src/README.md:170`, and point
      ONBOARDING §4 at this document for path setup.
- [x] **C5 — P0, done in PR #2.** **Untrack `.claude/settings.local.json`.** It carries the original
      author's absolute paths, username, a session UUID, and a permission entry that
      launches a background `remote-control` process. `*.local.json` is per-machine by
      convention: `git rm --cached .claude/settings.local.json` and add it to
      `.gitignore`.
- [x] **C6 — done in PR #2.** **Add a LICENSE file.** `blender_manifest.toml:12` already declares
      `SPDX:MIT` but no LICENSE exists. Flagged in ONBOARDING §8 as a V0 blocker.
- [ ] **C7** **The newer test scripts (P0).** `build_cylinder.py:21`,
      `build_mesh_primitives.py:20`, `build_primzoo.py:15` hardcode `REPO`, and each
      writes its result file to the original author's **Claude scratchpad path,
      session UUID included** (`C:\Users\User\AppData\Local\Temp\claude\…\ed4cc928-…`).
      On any other machine that directory does not exist. Resolve `REPO` per §2.4 and
      write results to `export/<name>/result.txt` (or `GNUE_RESULT` when set).
- [ ] **C8** **Commit the socket runner.** Scripts are described as "exec'd over the
      socket", but the runner (`bl.py`) only ever lived in a scratchpad. Add
      `tools/bl_exec.py <script>`: connects to the Blender MCP addon on port 9876,
      injects `GNUE_REPO`, runs the file, prints the output. Without it a
      collaborator has no way to use that path.
- [x] **C9 — done in PR #2.** gitignore `export/primzoo/` (the pattern only covered `*_test_a/`).

### Lane D — dead code (decide, then act) · S

Not path fixes; these files reference machines and projects that no longer exist
and will mislead the next reader.

- [ ] **D1** `create_spring_niagara.py:16` points at `C:\Projects\4D hands research\` —
      **a different project entirely.** With `create_spring_nodes.py`, these are
      pre-V1 Niagara prototypes superseded by the descriptor pipeline.
      **Delete, or move to `archive/` with a README noting they predate V1.**
- [ ] **D2** `tentacle_gn.py:16,17,24` — orphaned experiment writing to
      `C:\Projects\GNtoUEresearch`. Same decision.
- [ ] **D3** `nextstep.md` is a raw AI chat transcript from before V1 scoping, full of
      `file:///c%3A/Projects/...` links. **CONTRIBUTING §7 tells people to record
      design decisions here**, so replace it with a real decision log rather than
      deleting it.
- [ ] **D4** `prompt.txt` is empty (0 bytes); `downloadables/files.zip` is an
      unexplained blob. Identify or remove.

---

## 4. Known non-issues (don't "fix" these)

- **`export/*.gnue.json` and `manifest.json` embed an absolute `.blend` path**
  (`export/ropebridge_v1/effect.gnue.json:8`, `manifest.json:6`,
  `export/spinetree.gnue.json:7`). This comes from `bpy.data.filepath` and is
  **provenance only** — the importer never reads `source.file`, it only uses
  `source.node_group` ([import_gnue2.py:2213](ue_importer/import_gnue2.py)). Harmless
  for import. Worth knowing that it leaks the author's directory layout into every
  shipped descriptor, so consider storing just the basename before the public release.
- **`ONBOARDING.md:104-105` path assumptions** are documentation of an *expected*
  environment, not code. They should be softened to "typical install location" once
  auto-discovery lands, but they don't break anything.
- **Windows-only helpers** — `os.startfile` (`plugin_init_unreal.py:159`) and the
  PowerShell folder picker (`:110-121`) are already guarded and documented as
  Windows-only in `deliverables/README.md`. Out of scope here; the GNueDrops flow
  works cross-platform.

---

## 5. Definition of done

A new collaborator on a clean Windows machine, with only UE 5.8 + Blender 4.2+ +
VS2022 installed, can run this end to end **without editing a single source file**:

```bash
git clone <repo> && cd GN2UE
cp gnue.config.example.json gnue.config.json   # edit ue_project only
python tools/sync_ue_plugin.py
powershell -ExecutionPolicy Bypass -File tools/build_ue_plugin.ps1
python tools/make_deliverables.py
```

Checklist:

- [ ] `sync_ue_plugin.py` with no arguments targets the right project.
- [ ] `build_ue_plugin.ps1` finds the engine with **no** config file present
      (registry auto-discovery), and builds the correct `<Project>Editor` target
      for a UE project **not** named `GNtoUE`.
- [ ] All five headless tests run against the local project, or skip with a clear
      message when their fixture folder is absent.
- [ ] `make_deliverables.py` produces both zips with a version read from one place.
- [ ] A grep for `C:\Users\User` and `C:\Projects\GNtoUEresearch` across
      `*.py`, `*.ps1`, `*.bat` returns **nothing**.
- [ ] ONBOARDING §4/§5 match reality and point here.

---

## 6. Full inventory (36 references, 21 files)

Reference list for whoever picks this up. Severity: **P0** blocks a new machine ·
**P1** blocks release/tests · **P2** docs & hygiene.

| Sev | File:line | Hardcoded value | Task |
|---|---|---|---|
| P0 | `tools/build_ue_plugin.ps1:10` | engine root | A2 |
| P0 | `tools/build_ue_plugin.ps1:11` | UE project | A2 |
| P0 | `tools/build_ue_plugin.ps1:24` | `GNtoUEEditor` build target | A2 |
| P0 | `tools/sync_ue_plugin.py:22` | UE project (as default) | A1 |
| P0 | `gnue_exporter/export_cli.py:3` | repo (docstring exec) | C1 |
| P0 | `gnue_exporter/export_cli.py:14` | repo (`REPO =`) | C1 |
| P0 | `gnue_exporter/export_cli.py:25` | repo (default `OUT`) | C1 |
| P0 | `build_cylinder.py:21,24` | repo + scratchpad result path (session UUID) | C7 |
| P0 | `build_mesh_primitives.py:20,22` | repo + scratchpad result path (session UUID) | C7 |
| P0 | `build_primzoo.py:15,18` | repo + scratchpad result path (session UUID) | C7 |
| P1 | `tools/make_deliverables.py:15` | plugin dir | A3 |
| P1 | `tools/make_deliverables.py:16` | duplicated `VERSION` | A4 |
| P1 | `tools/sync_ue_plugin.py:140` | duplicated `VersionName` | A4 |
| P1 | `gnue_exporter/__init__.py:9` | **stale** `bl_info` `(0,4,0)` | A4 |
| P1 | `ue_importer/run_import.ps1:13` | UE project (default) | A5 |
| P1 | `ue_importer/run_import.ps1:14` | engine root (default) | A5 |
| P1 | `tools/test_cubefield_import.py:11` | GNueDrops path | B1 |
| P1 | `tools/test_domino_rotations.py:6` | GNueDrops path | B2 |
| P1 | `tools/test_params_headless.py:6` | GNueDrops path | B3 |
| P1 | `tools/test_walktrim_import.py:6` | GNueDrops path | B4 |
| P1 | `tools/refresh_cubefield.py:7` | GNueDrops path | B5 |
| P2 | `build_v1_bridge.py:4` | repo (docstring) | C2 |
| P2 | `build_v1_stonecircle.py:4` | repo (docstring) | C2 |
| P2 | `ue_importer/import_gnue.py:5,7` | repo (docstring) | C3 |
| P2 | `ue_importer/README.md:34` | repo | C3 |
| P2 | `ONBOARDING.md:93,95` | repo + UE project | C4 |
| P2 | `ONBOARDING.md:104,105,125` | engine / Blender / cmd line | C4 |
| P2 | `ue_plugin_src/README.md:170` | repo name | C4 |
| P0 | `.claude/settings.local.json` | author paths, session UUID, background-process permission | C5 ✅ |
| P2 | `ue_plugin_src/RebuildBinaries.bat:15` | engine fallback (**has registry discovery — OK as-is**) | — |
| P2 | `create_spring_niagara.py:16` | **unrelated project** | D1 |
| P2 | `tentacle_gn.py:16,17,24` | repo (orphaned) | D2 |
| P2 | `nextstep.md` (throughout) | `file:///c%3A/Projects/...` | D3 |

---

## 7. Suggested sequencing

0. **Merge the open Wave 1 branch first** (done — PR #1). Portability touches
   `.gitignore`, `build_*.py` and `tools/`, so every lane branches off a `main` that
   already contains Person A's work; otherwise the lanes manufacture conflicts.
1. **Task 1** (resolver) + C5 + C6 + C9 — one small PR (`fix/portability-resolver`,
   PR #2), unblocks everything. One person.
2. **Lane A + Lane B in parallel** — disjoint files, two people, no merge conflicts.
   B needs no resolver, so it can start at the same time as Task 1.
3. **Lane C** — mechanical; good first PR for a new collaborator, and forces them
   through the setup the doc describes (the best test of whether it works).
4. **Lane D** — needs a team decision on what to keep, not just a code change.

Per [CONTRIBUTING.md](CONTRIBUTING.md) §1: branch per task
(`fix/portability-resolver`, `fix/portability-build`, `fix/portability-tests`,
`fix/portability-blender-docs`), small PRs, `main` stays green.
