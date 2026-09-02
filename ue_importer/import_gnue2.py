r"""import_gnue2.py — build PCG from a v2 "graph"-family gnue descriptor.

Strategy: a numeric kernel evaluates every DETERMINISTIC part of the graph
(curve construction, duplication, offsets, per-point math) in Python using the
descriptor's expression trees, and emits explicit point lists; RANDOM parts
stay live in PCG (Transform Points ranges, Surface Sampler density/seed) so
regenerating with a new seed still varies — the same statistical-equivalence
contract as the v1 families.

Run (headless):
  UnrealEditor-Cmd.exe <project> -run=pythonscript -script="...\import_gnue2.py"
  descriptor folder via GNUE2_DIR env var (folder containing effect.gnue.json).

Coordinate conversion: pos (x,-y,z) * 100, frames rebuilt from converted axes
(applies the Y-negation handedness rule — v1's known gap #4).
"""

import json
import math
import os
import sys

import unreal

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for p in (_HERE, _REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

from gnue_exporter.core import evaluate, NonConstant           # noqa: E402
from import_gnue import (add_node, connect, import_fbx,        # noqa: E402
                         set_spawner_mesh, safe_set, log, warn, WARNINGS)

M2CM = 100.0
R2D = 180.0 / math.pi


class ImportError2(Exception):
    pass


def param_bag_name(name):
    """Descriptor parameter name -> PCG property-bag identifier."""
    import re
    return re.sub(r"[^0-9A-Za-z_]", "_", name)


# ------------------------------------------------------------- vector helpers

def vsub(a, b):
    return [a[i] - b[i] for i in range(3)]


def vadd(a, b):
    return [a[i] + b[i] for i in range(3)]


def vmul(a, s):
    return [a[i] * s for i in range(3)]


def vlen(a):
    return math.sqrt(sum(c * c for c in a))


def vnorm(a):
    n = vlen(a)
    return [c / n for c in a] if n > 1e-12 else [0.0, 0.0, 1.0]


def vcross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def catmull(p0, p1, p2, p3, t):
    t2, t3 = t * t, t * t * t
    return [0.5 * ((2 * p1[i]) + (-p0[i] + p2[i]) * t
                   + (2 * p0[i] - 5 * p1[i] + 4 * p2[i] - p3[i]) * t2
                   + (-p0[i] + 3 * p1[i] - 3 * p2[i] + p3[i]) * t3) for i in range(3)]


def densify(pts, smooth, per_seg=8):
    if not smooth or len(pts) < 3:
        return list(pts)
    out = []
    n = len(pts)
    for i in range(n - 1):
        p0 = pts[max(i - 1, 0)]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[min(i + 2, n - 1)]
        for k in range(per_seg):
            out.append(catmull(p0, p1, p2, p3, k / per_seg))
    out.append(pts[-1])
    return out


def arclength_sample(pts, count):
    """count evenly spaced (by arclength) samples + factors along a polyline."""
    if count < 2:
        return [pts[0]], [0.0]
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + vlen(vsub(pts[i], pts[i - 1])))
    total = cum[-1] or 1.0
    out, fac = [], []
    j = 0
    for k in range(count):
        d = total * k / (count - 1)
        while j < len(cum) - 2 and cum[j + 1] < d:
            j += 1
        seg = cum[j + 1] - cum[j] or 1.0
        t = (d - cum[j]) / seg
        out.append([pts[j][i] + (pts[j + 1][i] - pts[j][i]) * t for i in range(3)])
        fac.append(d / total)
    return out, fac


def tangents_of(pts):
    n = len(pts)
    out = []
    for i in range(n):
        a = pts[max(i - 1, 0)]
        b = pts[min(i + 1, n - 1)]
        out.append(vnorm(vsub(b, a)))
    return out


def factors_of(pts):
    """Normalized arclength factor of each existing point."""
    cum = [0.0]
    for i in range(1, len(pts)):
        cum.append(cum[-1] + vlen(vsub(pts[i], pts[i - 1])))
    total = cum[-1] or 1.0
    return [c / total for c in cum]


def splines_of(g):
    return g.get("splines") or [g["P"]]


# ------------------------------------------------------------- numeric kernel

class Kernel:
    """Evaluates deterministic geometry blocks to explicit point/curve data."""

    def __init__(self, desc, params):
        self.blocks = {b["id"]: b for b in desc["blocks"]}
        self.params = params
        self.cache = {}

    def block(self, bid):
        return self.blocks[bid.split(":")[0]]

    def ex(self, expr, env=None):
        """evaluate() + on-demand numeric aux blocks (curve.length/sample)."""
        env = dict(env or {})
        self._fill_aux(expr, env)
        return evaluate(expr, self.params, env)

    def _fill_aux(self, expr, env):
        if not isinstance(expr, dict):
            return
        if "block_output" in expr:
            bo = expr["block_output"]
            key = "%s.%s" % (bo["block"], bo["output"])
            if key not in env:
                env[key] = self.aux_value(bo["block"], bo["output"])
        for v in expr.values():
            if isinstance(v, dict):
                self._fill_aux(v, env)
            elif isinstance(v, list):
                for it in v:
                    self._fill_aux(it, env)

    def aux_value(self, bid, output):
        b = self.block(bid)
        if b["type"] == "curve.length":
            g = self.geo(b["curve"])
            total = 0.0
            for sp in splines_of(g):
                pts = densify(sp, g.get("smooth"))
                total += sum(vlen(vsub(pts[i + 1], pts[i])) for i in range(len(pts) - 1))
            return total
        if b["type"] == "curve.sample":
            g = self.geo(b["curve"])
            pts = densify(g["P"], g.get("smooth"))
            f = float(self.ex(b["factor"]))
            samples, _ = arclength_sample(pts, 201)
            idx = min(200, max(0, int(round(f * 200))))
            if output == "position":
                return samples[idx]
            if output == "tangent":
                t = tangents_of(samples)
                return t[idx]
            raise ImportError2("curve.sample output %r" % output)
        raise ImportError2("aux block %s (%s)" % (bid, b["type"]))

    def env_for(self, g, i):
        env = {"index": float(i), "position": g["P"][i]}
        if "factors" in g:
            env["spline_factor"] = g["factors"][i]
        if "T" in g:
            env["tangent"] = g["T"][i]
        for name, vals in g.get("attrs", {}).items():
            env[name] = vals[i]
        return env

    def geo(self, bid):
        base = bid.split(":")[0]
        inverted = bid.endswith(":inverted")
        key = (base, inverted)
        if key in self.cache:
            return self.cache[key]
        b = self.block(base)
        h = getattr(self, "k_" + b["type"].replace(".", "_"), None)
        if h is None:
            raise ImportError2("numeric kernel: no handler for %s (%s)" % (b["type"], base))
        g = h(b, inverted)
        self.cache[key] = g
        return g

    # ---- per-index series (random walks / accumulate) -------------------
    def _rewrite_series(self, e, n, env_fn, series, salt):
        """Replace random/accumulate leaves with precomputed per-index series
        (seeded python RNG — statistical equivalence, deterministic per import,
        regenerates with Seed). Returns the rewritten expr."""
        import random as _random
        if isinstance(e, dict):
            if "random" in e:
                r = e["random"]
                try:
                    seed = int(float(self.ex(r.get("seed", {"const": 0})) or 0))
                except NonConstant:
                    seed = 0
                lo = self.ex(self._const_only(r.get("min", {"const": 0.0})))
                hi = self.ex(self._const_only(r.get("max", {"const": 1.0})))
                key = "__s%d" % len(series)
                vals = []
                for i in range(n):
                    rr = _random.Random((seed * 2654435761 + i * 40503 + salt * 97) & 0x7fffffff)
                    if isinstance(lo, list):
                        vals.append([rr.uniform(float(lo[c]), float(hi[c])) for c in range(3)])
                    else:
                        vals.append(rr.uniform(float(lo), float(hi)))
                series[key] = vals
                return {"attr": key}
            if "accumulate" in e:
                inner = self._rewrite_series(e["accumulate"]["value"], n, env_fn,
                                             series, salt + 13)
                vals = []
                for i in range(n):
                    env = dict(env_fn(i))
                    for k in series:
                        env[k] = series[k][i]
                    vals.append(self.ex(inner, env))
                out_mode = e["accumulate"].get("out", "leading")
                acc, run = [], None
                for v in vals:
                    if out_mode == "leading":       # sum BEFORE current element
                        acc.append([0, 0, 0] if isinstance(v, list) and run is None
                                   else (0.0 if run is None else run))
                        if isinstance(v, list):
                            if run is None or not isinstance(run, list):
                                run = [0.0, 0.0, 0.0]
                            acc[-1] = list(run)
                            run = [run[c] + float(v[c]) for c in range(3)]
                        else:
                            run = (0.0 if run is None else run) + float(v)
                    else:                            # trailing: includes current
                        if isinstance(v, list):
                            run = [float(v[c]) + (run[c] if isinstance(run, list) else 0.0)
                                   for c in range(3)]
                            acc.append(list(run))
                        else:
                            run = float(v) + (run or 0.0)
                            acc.append(run)
                if out_mode == "total" and acc:
                    acc = [acc[-1]] * n
                key = "__s%d" % len(series)
                series[key] = acc
                return {"attr": key}
            return {k: self._rewrite_series(v, n, env_fn, series, salt)
                    for k, v in e.items()}
        if isinstance(e, list):
            return [self._rewrite_series(v, n, env_fn, series, salt) for v in e]
        return e

    def _const_only(self, e):
        """min/max of a random leaf must be param/const — nested randomness
        inside random bounds is refused."""
        if expr_has_random(e):
            raise ImportError2("random bounds may not themselves be random")
        return e

    def series_eval(self, expr, n, env_fn, salt=1):
        series = {}
        rew = self._rewrite_series(expr, n, env_fn, series, salt)
        out = []
        for i in range(n):
            env = dict(env_fn(i))
            for k in series:
                env[k] = series[k][i]
            out.append(self.ex(rew, env))
        return out

    # ---- handlers
    def k_curve_line(self, b, inv):
        s = [float(c) for c in self.ex(b["start"])]
        e = [float(c) for c in self.ex(b["end"])]
        return {"P": [s, e], "smooth": False, "factors": [0.0, 1.0]}

    def k_curve_resample(self, b, inv):
        g = self.geo(b["curve"])
        n = max(2, int(round(float(self.ex(b["count"])))))
        P, fac, splines = [], [], []
        for sp in splines_of(g):
            dense = densify(sp, g.get("smooth"))
            pts, f = arclength_sample(dense, n)
            splines.append(pts)
            P.extend(pts)
            fac.extend(f)
        out = {"P": P, "smooth": False, "factors": fac}
        if len(splines) > 1:
            out["splines"] = splines
        return out

    def k_curve_set_type(self, b, inv):
        g = dict(self.geo(b["curve"]))
        g["smooth"] = b.get("spline_type", "").startswith("catmull")
        return g

    def k_geometry_set_position(self, b, inv):
        g = dict(self.geo(b["geometry"]))
        n = len(g["P"])
        env_fn = lambda i: self.env_for(g, i)  # noqa: E731
        pos_series = off_series = None
        if "position" in b:
            pos_series = self.series_eval(b["position"], n, env_fn, salt=3)
        if b.get("offset") is not None:
            off_series = self.series_eval(b["offset"], n, env_fn, salt=5)
        P = []
        for i in range(n):
            p = pos_series[i] if pos_series is not None else g["P"][i]
            off = off_series[i] if off_series is not None else [0, 0, 0]
            if not isinstance(off, list):
                off = [0, 0, 0]
            P.append(vadd([float(c) for c in p], [float(c) for c in off]))
        g["P"] = P
        return g

    def k_curve_trim(self, b, inv):
        g = self.geo(b["curve"])
        f0 = float(self.ex(b["start"]) or 0.0)
        f1 = float(self.ex(b["end"]) or 1.0)
        mode = b.get("mode", "factor")
        splines, P = [], []
        for sp in splines_of(g):
            dense = densify(sp, g.get("smooth"))
            L = [0.0]
            for i in range(len(dense) - 1):
                L.append(L[-1] + vlen(vsub(dense[i + 1], dense[i])))
            total = L[-1] or 1.0
            a, z = (f0, f1) if mode == "factor" else (f0 / total, f1 / total)
            a, z = max(0.0, min(1.0, a)), max(0.0, min(1.0, z))
            if z < a:
                a, z = z, a
            ta, tz = a * total, z * total

            def sample_at(tl):
                for i in range(len(L) - 1):
                    if L[i + 1] >= tl:
                        seg = (L[i + 1] - L[i]) or 1e-12
                        t = (tl - L[i]) / seg
                        return [dense[i][c] + (dense[i + 1][c] - dense[i][c]) * t
                                for c in range(3)]
                return list(dense[-1])

            pts = [sample_at(ta)]
            for i in range(len(dense)):
                if ta < L[i] < tz:
                    pts.append(list(dense[i]))
            pts.append(sample_at(tz))
            splines.append(pts)
            P.extend(pts)
        out = {"P": P, "smooth": False,
               "factors": [f for sp in splines for f in factors_of(sp)]}
        if len(splines) > 1:
            out["splines"] = splines
        return out

    def k_attribute_capture(self, b, inv):
        g = dict(self.geo(b["geometry"]))
        attrs = dict(g.get("attrs", {}))
        for name, expr in b.get("items", {}).items():
            vals = []
            for i in range(len(g["P"])):
                vals.append(self.ex(expr, self.env_for(g, i)))
            attrs["capture:" + name] = vals
            # exporter names capture leaves by the socket name; also index them
            attrs.setdefault("capture:Value", vals)
        g["attrs"] = attrs
        return g

    def k_curve_to_points(self, b, inv):
        g = self.geo(b["curve"])
        mode = b.get("mode", "count")
        P, T, fac = [], [], []
        if mode == "evaluated":
            for sp in splines_of(g):
                pts = densify(sp, g.get("smooth")) if g.get("smooth") else list(sp)
                P.extend(pts)
                T.extend(tangents_of(pts))
                fac.extend(factors_of(pts))
            out = {"P": P, "T": T, "factors": fac}
            if len(P) == len(g["P"]):
                out["attrs"] = dict(g.get("attrs", {}))
            return out
        n = max(2, int(round(float(self.ex(b["count"])))))
        for sp in splines_of(g):
            dense = densify(sp, g.get("smooth"))
            pts, f = arclength_sample(dense, n)
            P.extend(pts)
            T.extend(tangents_of(pts))
            fac.extend(f)
        return {"P": P, "T": T, "factors": fac}

    def k_points_duplicate(self, b, inv):
        g = self.geo(b["geometry"])
        amount = max(1, int(round(float(self.ex(b["amount"])))))
        P, attrs = [], {}
        names = list(g.get("attrs", {}).keys())
        for nme in names + ["duplicate_index"]:
            attrs[nme] = []
        T = [] if "T" in g else None
        fac = [] if "factors" in g else None
        for i in range(len(g["P"])):
            for d in range(amount):
                P.append(list(g["P"][i]))
                attrs["duplicate_index"].append(float(d))
                for nme in names:
                    attrs[nme].append(g["attrs"][nme][i])
                if T is not None:
                    T.append(g["T"][i])
                if fac is not None:
                    fac.append(g["factors"][i])
        out = {"P": P, "attrs": attrs}
        if T is not None:
            out["T"] = T
        if fac is not None:
            out["factors"] = fac
        return out

    def k_points_to_curves(self, b, inv):
        g = self.geo(b["points"])
        groups = {}
        for i in range(len(g["P"])):
            gid = self.ex(b["group_id"], self.env_for(g, i))
            groups.setdefault(round(float(gid), 4), []).append(g["P"][i])
        splines = [groups[k] for k in sorted(groups)]
        # kernel keeps one polyline per curve; consumers densify per spline
        return {"P": [p for s in splines for p in s], "splines": splines, "smooth": False}

    def k_curve_set_type_multi(self, b, inv):  # pragma: no cover
        return self.geo(b["curve"])

    def k_point_create(self, b, inv):
        n = max(0, int(round(float(self.ex(b["count"])))))
        env_fn = lambda i: {"index": float(i)}  # noqa: E731
        vals = self.series_eval(b["position"], n, env_fn, salt=9)
        P = [[float(c) for c in p] if isinstance(p, list) else [0, 0, 0] for p in vals]
        return {"P": P}

    def k_point_line(self, b, inv):
        # Mesh Line, Offset mode: point i sits at start + offset*i. (The exporter
        # emits only start/offset, i.e. offset semantics; End-Points mode would
        # arrive pre-resolved as start/offset.)
        n = max(0, int(round(float(self.ex(b["count"])))))
        start = [float(c) for c in self.ex(b["start"])]
        offset = [float(c) for c in self.ex(b["offset"])]
        P = [[start[c] + offset[c] * i for c in range(3)] for i in range(n)]
        return {"P": P}

    def k_instances_to_points(self, b, inv):
        chain = b["instances"]
        blk = self.block(chain)
        while blk["type"] in ("instance.rotate", "instance.translate", "instance.scale",
                              "attribute.store"):
            chain = blk.get("instances") or blk.get("geometry")
            blk = self.block(chain)
        if blk["type"] != "instance.on_points":
            raise ImportError2("instances.to_points: chain base is %s" % blk["type"])
        return self.geo(blk["points"])

    def k_geometry_separate(self, b, inv):
        g = self.geo(b["geometry"])
        keep, attrs = [], {}
        names = list(g.get("attrs", {}).keys())
        for nme in names:
            attrs[nme] = []
        for i in range(len(g["P"])):
            sel = bool(self.ex(b["selection"], self.env_for(g, i)))
            if sel != inv:
                keep.append(list(g["P"][i]))
                for nme in names:
                    attrs[nme].append(g["attrs"][nme][i])
        return {"P": keep, "attrs": attrs}

    def k_geometry_delete(self, b, inv):
        return self.k_geometry_separate(b, not inv)  # delete keeps the NOT-selected side

    def k_attribute_store(self, b, inv):
        return self.geo(b["geometry"])

    def k_material_set(self, b, inv):
        return self.geo(b["geometry"])

    def k_instances_realize(self, b, inv):
        raise ImportError2("realized instances have no numeric form (emitted as PCG)")

    def k_geometry_input(self, b, inv):
        raise ImportError2("geometry.input has no numeric form (UE-side surface)")


# ------------------------------------------------------------- UE conversion

def to_ue_pos(p):
    return unreal.Vector(p[0] * M2CM, -p[1] * M2CM, p[2] * M2CM)


def expr_has_random(e):
    """True if a lowered expression tree contains any random leaf."""
    if isinstance(e, dict):
        if "random" in e:
            return True
        return any(expr_has_random(v) for v in e.values())
    if isinstance(e, (list, tuple)):
        return any(expr_has_random(v) for v in e)
    return False


def mat3_mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def euler_xyz_matrix(rx, ry, rz):
    """Blender 'XYZ' euler order: X applied first (R = Rz @ Ry @ Rx)."""
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    Rx = [[1, 0, 0], [0, cx, -sx], [0, sx, cx]]
    Ry = [[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]]
    Rz = [[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]]
    return mat3_mul(Rz, mat3_mul(Ry, Rx))


def mat3_to_ue_rotator(m):
    """Blender-space rotation matrix -> UE rotator, via the same Y-mirror the
    positions get (R_ue = D R D with D = diag(1,-1,1)); columns become axes."""
    x = (m[0][0], -m[1][0], m[2][0])
    y = (-m[0][1], m[1][1], -m[2][1])
    z = (m[0][2], -m[1][2], m[2][2])
    try:
        return unreal.MathLibrary.make_rotation_from_axes(
            unreal.Vector(*x), unreal.Vector(*y), unreal.Vector(*z))
    except Exception as e:
        warn("make_rotation_from_axes: %s" % e)
        return unreal.Rotator(0, 0, 0)


def frame_rotator(tangent, tilt=0.0):
    """Rotator whose local +Z follows the tangent (Blender curve convention),
    X = side (cross with world up), optionally rolled by `tilt` around Z."""
    z = vnorm([tangent[0], -tangent[1], tangent[2]])
    side = vcross(z, [0.0, 0.0, 1.0])
    if vlen(side) < 1e-6:
        side = [1.0, 0.0, 0.0]
    x = vnorm(side)
    y = vcross(z, x)
    if abs(tilt) > 1e-9:
        c, s = math.cos(tilt), math.sin(tilt)
        x, y = [x[i] * c + y[i] * s for i in range(3)], [y[i] * c - x[i] * s for i in range(3)]
    try:
        return unreal.MathLibrary.make_rotation_from_axes(
            unreal.Vector(*x), unreal.Vector(*y), unreal.Vector(*z))
    except Exception as e:
        warn("make_rotation_from_axes: %s" % e)
        return unreal.Rotator(0, 0, 0)


# ------------------------------------------------------------- spawn planning

class Planner:
    """Walk the block graph from the root; produce spawn groups."""

    def __init__(self, desc, kernel):
        self.desc = desc
        self.kernel = kernel
        self.blocks = kernel.blocks
        self.groups = []

    def plan(self):
        self.branch(self.desc["root"])
        return self.groups

    def branch(self, bid):
        if bid is None:
            return
        b = self.blocks[bid.split(":")[0]]
        t = b["type"]
        if t == "geometry.join":
            for sub in b["inputs"]:
                self.branch(sub)
        elif t == "geometry.switch":
            try:
                on = bool(self.kernel.ex(b["switch"]))
            except NonConstant:
                on = True
                warn("switch %s: non-constant condition — defaulting to True branch" % b["id"])
            self.branch(b["true_branch"] if on else b["false_branch"])
        elif t == "geometry.input":
            log("input passthrough (UE-side surface) — nothing to spawn")
        elif t == "material.set":
            self.branch(b["geometry"])
        elif t == "instances.realize":
            self.branch(b["instances"])
        elif t in ("instance.rotate", "instance.translate", "instance.scale",
                   "instance.on_points", "attribute.store"):
            self.instance_chain(bid)
        else:
            warn("root branch %s (%s): un-spawned geometry — skipped" % (bid, t))

    def instance_chain(self, bid):
        mods = []
        b = self.blocks[bid.split(":")[0]]
        while b["type"] in ("instance.rotate", "instance.translate", "instance.scale",
                            "attribute.store"):
            if b["type"] != "attribute.store":
                mods.append(b)
            else:
                warn("attribute.store %r on instances: cosmetic attr skipped" % b.get("name", b["id"]))
            b = self.blocks[(b.get("instances") or b.get("geometry")).split(":")[0]]
        if b["type"] != "instance.on_points":
            warn("instance chain base is %s — skipped" % b["type"])
            return
        mods.reverse()  # apply in graph order
        src_block = self.blocks[b["points"].split(":")[0]]
        while src_block["type"] == "attribute.store":  # stores are pass-through
            src_block = self.blocks[src_block["geometry"].split(":")[0]]
        group = {"on_points": b, "mods": mods}
        if src_block["type"] == "scatter.on_surface":
            group["scatter"] = src_block
            group["stores"] = self.stores_between(b["points"])
            if src_block.get("surface_kind") == "instances":
                group["kind"] = "greeble"
                group["target_on_points"] = self.realize_base(src_block["surface"])
            else:
                group["kind"] = "scatter"
        else:
            group["kind"] = "explicit"
            group["points_id"] = b["points"]
        self.groups.append(group)

    def realize_base(self, bid):
        """instances.realize block id -> the on_points block id of its chain."""
        b = self.blocks[bid.split(":")[0]]
        if b["type"] == "material.set":
            b = self.blocks[b["geometry"].split(":")[0]]
        if b["type"] == "instances.realize":
            b = self.blocks[b["instances"].split(":")[0]]
        while b["type"] in ("instance.rotate", "instance.translate", "instance.scale",
                            "attribute.store"):
            b = self.blocks[(b.get("instances") or b.get("geometry")).split(":")[0]]
        return b["id"] if b["type"] == "instance.on_points" else None

    def stores_between(self, bid):
        out = {}
        b = self.blocks[bid.split(":")[0]]
        while b["type"] in ("attribute.store",):
            out[b["name"]] = b["value"]
            b = self.blocks[b["geometry"].split(":")[0]]
        return out


# ------------------------------------------------------------- PCG emission

def _find_leaf(e, key):
    """First {key: {...}} leaf dict anywhere inside an expression tree."""
    if isinstance(e, dict):
        if key in e and isinstance(e[key], dict):
            return e[key]
        for v in e.values():
            r = _find_leaf(v, key)
            if r is not None:
                return r
    elif isinstance(e, list):
        for v in e:
            r = _find_leaf(v, key)
            if r is not None:
                return r
    return None


def find_class(*names):
    for n in names:
        c = getattr(unreal, n, None)
        if c is not None:
            return c
    return None


def sel_dsl(selector, dsl):
    """Set a PCGAttributePropertySelector from DSL text ('$Scale.Z', 'MyAttr')."""
    try:
        ok = selector.import_text("PCGBegin(%s)PCGEnd" % dsl)
        if ok is not False:
            return True
        raise ValueError("import_text rejected %r" % dsl)
    except Exception:
        try:
            if dsl.startswith("$"):
                prop = getattr(unreal.PCGPointProperties,
                               dsl[1:].split(".")[0].upper(), None)
                if prop is not None:
                    selector.set_point_property(prop)
                    return True
            else:
                selector.set_attribute_name(dsl)
                return True
        except Exception as e:
            warn("selector %r: %s" % (dsl, e))
    return False


def enum_val(enum_name, *members):
    # UE python strips the C++ "E" prefix from some enums (e.g.
    # EPCGMetadataMathsOperation binds as PCGMetadataMathsOperation) —
    # try both spellings so call sites don't have to care.
    names = [enum_name]
    names.append(enum_name[1:] if enum_name.startswith("E") else "E" + enum_name)
    for n in names:
        en = getattr(unreal, n, None)
        if en is None:
            continue
        for m in members:
            v = getattr(en, m, None)
            if v is not None:
                return v
    warn("enum %s.%s not found" % (enum_name, "/".join(members)))
    return None


DYNAMICS_ROOT = "/Game/GNueImport/_Dynamics"


def _mat_enum(enum_name, member):
    en = getattr(unreal, enum_name, None)
    return getattr(en, member, None) if en is not None else None


def ensure_controller_collection(tag):
    """Material Parameter Collection MPC_GNueCtrl_<tag> with a 'Position'
    vector; the GNuePCG world subsystem keeps it synced to the tagged actor
    every frame (editor + runtime). Returns the asset or None."""
    safe = "".join(c if c.isalnum() else "_" for c in str(tag))
    name = "MPC_GNueCtrl_" + safe
    full = DYNAMICS_ROOT + "/" + name
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(full):
            return unreal.EditorAssetLibrary.load_asset(full)
        tools = unreal.AssetToolsHelpers.get_asset_tools()
        mpc = tools.create_asset(name, DYNAMICS_ROOT, unreal.MaterialParameterCollection,
                                 unreal.MaterialParameterCollectionFactoryNew())
        p = unreal.CollectionVectorParameter()
        p.set_editor_property("parameter_name", "Position")
        # same "infinitely far" sentinel as the PCG path: no controller = full size
        p.set_editor_property("default_value", unreal.LinearColor(0.0, 0.0, 1.0e7, 1.0))
        mpc.set_editor_property("vector_parameters", [p])
        unreal.EditorAssetLibrary.save_asset(full)
        log("dynamics: controller collection %s (tag %r)" % (name, tag))
        return mpc
    except Exception as e:
        warn("dynamics: controller collection for %r failed: %s" % (tag, e))
        return None


def build_dynamic_material(root, name, mpc, fmin_cm, fmax_cm, tmin, tmax,
                           spin_rate=0.4, shake_amp=5.0, shake_freq=7.0):
    """M_GNueDyn_*: per-frame World Position Offset that gives every instance a
    proximity-driven scale + spin + shake, all from one agitation value
        agit = saturate((dist - Fmin) / (Fmax - Fmin))   # 0 near, 1 far
    so an instance is calm/small/still next to the controller and
    big/spinning/shaking far from it:
        scale = lerp(Tmin, Tmax, agit)                    # about the pivot
        spin  = SpinRate * Time * agit  turns about instance Z (+per-instance phase)
        shake = ShakeAmp * agit * (sin,cos)(ShakeFreq*Time)  world XY jitter
    Rigid scale+spin are built in INSTANCE space (the engine's "Local" is the
    component, not the instance) and moved to world as a *vector* — absolute
    world positions are Large-World-Coordinate doubles that Distance/Transform
    reject, vectors stay float. Time + Per Instance Random make each instance
    animate independently. Evaluated on the GPU every frame, so the effect
    reacts continuously to the controller without regenerating."""
    full = root + "/" + name
    mel = unreal.MaterialEditingLibrary
    try:
        if unreal.EditorAssetLibrary.does_asset_exist(full):
            mat = unreal.EditorAssetLibrary.load_asset(full)
            mel.delete_all_material_expressions(mat)
        else:
            tools = unreal.AssetToolsHelpers.get_asset_tools()
            mat = tools.create_asset(name, root, unreal.Material, unreal.MaterialFactoryNew())
        safe_set(mat, "used_with_instanced_static_meshes", True, "Material")
        # no Nanite usage flag: our baked meshes aren't Nanite and every usage
        # flag multiplies the shader permutations compiled (RAM + time)

        def ex(cls, x, y):
            return mel.create_material_expression(mat, cls, x, y)

        def link(a, b, b_in, a_out=""):
            if not mel.connect_material_expressions(a, a_out, b, b_in):
                raise RuntimeError("link %s -> %s.%s failed"
                                   % (type(a).__name__, type(b).__name__, b_in))

        def scalar(pname, value, x, y):
            n = ex(unreal.MaterialExpressionScalarParameter, x, y)
            n.set_editor_property("parameter_name", pname)
            n.set_editor_property("default_value", float(value))
            return n

        def pos_enum(member):
            return _mat_enum("MaterialPositionTransformSource", member)

        def vec_src(member):
            return _mat_enum("MaterialVectorCoordTransformSource", member)

        def vec_dst(member):
            return _mat_enum("MaterialVectorCoordTransform", member)

        col = ex(unreal.MaterialExpressionConstant3Vector, -400, -500)
        col.set_editor_property("constant", unreal.LinearColor(0.62, 0.60, 0.56, 1.0))
        mel.connect_material_property(col, "", unreal.MaterialProperty.MP_BASE_COLOR)

        # controller position (float3) -> instance-local space
        ctrl = ex(unreal.MaterialExpressionCollectionParameter, -1800, 200)
        ctrl.set_editor_property("collection", mpc)
        ctrl.set_editor_property("parameter_name", "Position")
        ctrl3 = ex(unreal.MaterialExpressionComponentMask, -1600, 200)
        for c, v in (("r", True), ("g", True), ("b", True), ("a", False)):
            safe_set(ctrl3, c, v, "ComponentMask")
        link(ctrl, ctrl3, "")
        to_local = ex(unreal.MaterialExpressionTransformPosition, -1400, 200)
        to_local.set_editor_property("transform_source_type", pos_enum("TRANSFORMPOSSOURCE_WORLD"))
        # INSTANCE space (per ISM instance) — "Local" would be the component
        to_local.set_editor_property("transform_type", pos_enum("TRANSFORMPOSSOURCE_INSTANCE"))
        link(ctrl3, to_local, "")
        # local offset pivot->controller, back to a WORLD-space *vector* so the
        # distance is in centimetres regardless of the instance's scale
        dvec = ex(unreal.MaterialExpressionTransform, -1200, 200)
        dvec.set_editor_property("transform_source_type", vec_src("TRANSFORMSOURCE_INSTANCE"))
        dvec.set_editor_property("transform_type", vec_dst("TRANSFORM_WORLD"))
        link(to_local, dvec, "")
        zero = ex(unreal.MaterialExpressionConstant3Vector, -1200, 400)
        zero.set_editor_property("constant", unreal.LinearColor(0, 0, 0, 0))
        dist = ex(unreal.MaterialExpressionDistance, -1000, 250)
        link(dvec, dist, "A")
        link(zero, dist, "B")

        p_fmin = scalar("GNue_FalloffMin", fmin_cm, -1000, 450)
        p_fmax = scalar("GNue_FalloffMax", fmax_cm, -1000, 550)
        p_tmin = scalar("GNue_ScaleMin", tmin, -600, 550)
        p_tmax = scalar("GNue_ScaleMax", tmax, -600, 650)
        d_sub = ex(unreal.MaterialExpressionSubtract, -800, 250)
        link(dist, d_sub, "A")
        link(p_fmin, d_sub, "B")
        span = ex(unreal.MaterialExpressionSubtract, -800, 450)
        link(p_fmax, span, "A")
        link(p_fmin, span, "B")
        ratio = ex(unreal.MaterialExpressionDivide, -600, 300)
        link(d_sub, ratio, "A")
        link(span, ratio, "B")
        sat = ex(unreal.MaterialExpressionSaturate, -450, 300)
        link(ratio, sat, "")
        factor = ex(unreal.MaterialExpressionLinearInterpolate, -300, 400)
        link(p_tmin, factor, "A")
        link(p_tmax, factor, "B")
        link(sat, factor, "Alpha")
        # ---- animation inputs -------------------------------------------
        p_spin = scalar("GNue_SpinRate", spin_rate, -300, 700)    # turns/sec, far
        p_shamp = scalar("GNue_ShakeAmp", shake_amp, -300, 800)   # cm, far
        p_shfrq = scalar("GNue_ShakeFreq", shake_freq, -300, 900)
        time = ex(unreal.MaterialExpressionTime, -600, 760)
        pir = ex(unreal.MaterialExpressionPerInstanceRandom, -600, 860)

        # instance-space vertex relative to the instance pivot (float)
        lp_cls = getattr(unreal, "MaterialExpressionLocalPosition", None)
        if lp_cls is not None:
            local_pos = ex(lp_cls, -600, 0)
            origin = _mat_enum("LocalPositionOrigin", "INSTANCE")
            if origin is not None:
                safe_set(local_pos, "local_origin", origin, "LocalPosition")
        else:
            wp = ex(unreal.MaterialExpressionWorldPosition, -800, 0)
            local_pos = ex(unreal.MaterialExpressionTransformPosition, -600, 0)
            local_pos.set_editor_property("transform_source_type", pos_enum("TRANSFORMPOSSOURCE_WORLD"))
            local_pos.set_editor_property("transform_type", pos_enum("TRANSFORMPOSSOURCE_INSTANCE"))
            link(wp, local_pos, "")

        # ---- SPIN: rotate local_pos about instance Z; speed scales with agit
        #      angle(turns) = SpinRate*Time*agit + perInstanceRandom (desync)
        spin_speed = ex(unreal.MaterialExpressionMultiply, -150, 720)
        link(p_spin, spin_speed, "A")
        link(sat, spin_speed, "B")
        spin_t = ex(unreal.MaterialExpressionMultiply, 0, 730)
        link(spin_speed, spin_t, "A")
        link(time, spin_t, "B")
        spin_ang = ex(unreal.MaterialExpressionAdd, 140, 740)
        link(spin_t, spin_ang, "A")
        link(pir, spin_ang, "B")
        axis = ex(unreal.MaterialExpressionConstant3Vector, 140, 900)
        axis.set_editor_property("constant", unreal.LinearColor(0, 0, 1, 0))
        pivot0 = ex(unreal.MaterialExpressionConstant3Vector, 140, 980)
        pivot0.set_editor_property("constant", unreal.LinearColor(0, 0, 0, 0))
        rot = ex(unreal.MaterialExpressionRotateAboutAxis, 320, 780)
        link(axis, rot, "NormalizedRotationAxis")
        link(spin_ang, rot, "RotationAngle")
        link(pivot0, rot, "PivotPoint")
        link(local_pos, rot, "Position")
        # RotateAboutAxis outputs the rotation OFFSET, so rotated = local + offset
        rotated = ex(unreal.MaterialExpressionAdd, 480, 380)
        link(local_pos, rotated, "A")
        link(rot, rotated, "B")

        # ---- SCALE about the pivot, then the rigid delta vs the original vertex
        scaled = ex(unreal.MaterialExpressionMultiply, 620, 380)
        link(rotated, scaled, "A")
        link(factor, scaled, "B")
        rigid_local = ex(unreal.MaterialExpressionSubtract, 760, 380)
        link(scaled, rigid_local, "A")
        link(local_pos, rigid_local, "B")
        rigid_world = ex(unreal.MaterialExpressionTransform, 900, 380)
        rigid_world.set_editor_property("transform_source_type", vec_src("TRANSFORMSOURCE_INSTANCE"))
        rigid_world.set_editor_property("transform_type", vec_dst("TRANSFORM_WORLD"))
        link(rigid_local, rigid_world, "")

        # ---- SHAKE: world-space XY jitter; amplitude scales with agit
        #      phase(turns) = ShakeFreq*Time + perInstanceRandom
        shk_t = ex(unreal.MaterialExpressionMultiply, 320, 1000)
        link(p_shfrq, shk_t, "A")
        link(time, shk_t, "B")
        shk_ph = ex(unreal.MaterialExpressionAdd, 460, 1000)
        link(shk_t, shk_ph, "A")
        link(pir, shk_ph, "B")
        sx = ex(unreal.MaterialExpressionSine, 600, 960)
        link(shk_ph, sx, "")
        sy = ex(unreal.MaterialExpressionCosine, 600, 1050)
        link(shk_ph, sy, "")
        app1 = ex(unreal.MaterialExpressionAppendVector, 740, 1000)
        link(sx, app1, "A")
        link(sy, app1, "B")
        zc = ex(unreal.MaterialExpressionConstant, 740, 1090)
        zc.set_editor_property("r", 0.0)
        app2 = ex(unreal.MaterialExpressionAppendVector, 860, 1000)
        link(app1, app2, "A")
        link(zc, app2, "B")
        shk_amp2 = ex(unreal.MaterialExpressionMultiply, 1000, 1000)   # amp * agit
        link(p_shamp, shk_amp2, "A")
        link(sat, shk_amp2, "B")
        shake_world = ex(unreal.MaterialExpressionMultiply, 1140, 1000)
        link(app2, shake_world, "A")
        link(shk_amp2, shake_world, "B")

        # ---- WPO = rigid (scale+spin) world delta + shake
        wpo = ex(unreal.MaterialExpressionAdd, 1300, 600)
        link(rigid_world, wpo, "A")
        link(shake_world, wpo, "B")
        mel.connect_material_property(wpo, "", unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)

        mel.recompile_material(mat)
        unreal.EditorAssetLibrary.save_asset(full)
        log("dynamics: material %s (falloff %.0f..%.0fcm -> scale %.2f..%.2f + "
            "spin %.2f turns/s + shake %.0fcm, per-frame WPO)"
            % (name, fmin_cm, fmax_cm, tmin, tmax, spin_rate, shake_amp))
        return mat
    except Exception as e:
        warn("dynamics: material %s failed (%s) — falling back to PCG-side falloff" % (name, e))
        return None


class Emitter:
    def __init__(self, graph, kernel, desc, meshes):
        self.g = graph
        self.k = kernel
        self.desc = desc
        self.meshes = meshes
        self.x = 0
        self.chain_final = {}   # on_points block id -> final chain node(s) (list)
        self.actor_nodes = {}   # actor object name -> Get Actor Data node
        self.pending_falloff = None  # set by emit_actor_falloff, split in emit_group
        self.surface_mesh = None     # /Game path of SM_GNue_Surface, if shipped
        self._self_anchor = None     # cached single point at the volume origin
        self._scatter_extra_sources = []  # tagged-surface chains to co-spawn
        self.asset_root = None       # /Game/GNueImport/<Effect>, set by main()
        self.dynamics_enabled = True # shader-side proximity (GNue Dynamics)
        self.dyn_materials = {}      # group id -> dynamics material
        self._current_group = None
        self.typical_scale = {}  # on_points block id -> rest scale of an instance

    def pos(self):
        self.x += 300
        return (self.x, 0)

    def eval_maybe(self, expr, env=None, default=None):
        try:
            return self.k.ex(expr, env)
        except NonConstant:
            return default

    def asset_scale(self, spec, env=None):
        v = self.eval_maybe(spec.get("size", {"const": [1, 1, 1]}), env, [1, 1, 1])
        if not isinstance(v, list):
            v = [v, v, v]
        return v

    def emit_group(self, i, group):
        name = "grp%d" % i
        b = group["on_points"]
        spec = b["instance"]
        mesh = self.meshes[spec["asset"]]
        scale = self.asset_scale(spec)

        if group["kind"] == "explicit":
            geo = self.k.geo(group["points_id"])
            # fold the LEADING run of deterministic rotations into the point
            # frames (order matters, so folding stops at the first live mod)
            det_eulers, live_mods = [], []
            folding = True
            for m in group["mods"]:
                args = self._det_euler_args(m) if folding else None
                if args is not None:
                    det_eulers.append((args, bool(m.get("local", True))))
                else:
                    folding = False
                    live_mods.append(m)
            group = dict(group, mods=live_mods)
            node = self.emit_create_points(name, geo, b, scale, det_eulers)
            count = len(geo["P"])
        elif group["kind"] == "greeble":
            node = self.emit_greebles(name, group, scale)
            count = -2
        else:
            node = self.emit_scatter(name, group)
            count = -1
        if node is None:
            return 0
        if group["kind"] != "greeble":
            self.typical_scale[b["id"]] = self._typical_scale(group, scale)
        # greeble clouds already carry their base scale in the source points
        self._current_group = b["id"]
        node = self.emit_mods(name, node, group, scale, group["kind"] == "scatter")
        ends = self.emit_falloff_bands(name, node)
        spawner, sp_settings = add_node(self.g, unreal.PCGStaticMeshSpawnerSettings,
                                        name + "_Spawner", self.pos())
        # greebles ride their target's dynamics material so they vanish with it
        dyn_mat = (self.dyn_materials.get(b["id"])
                   or self.dyn_materials.get(group.get("target_on_points")))
        set_spawner_mesh(sp_settings, mesh, material=dyn_mat)
        for end in ends:
            connect(self.g, end, spawner)
        self.chain_final[b["id"]] = ends
        return count

    def emit_falloff_bands(self, name, node):
        """Split the chain into discrete proximity-collapse bands if an actor
        falloff is pending (see emit_actor_falloff). Returns the list of chain
        ends to feed the spawner; [node] when there is no falloff."""
        pend, self.pending_falloff = self.pending_falloff, None
        if pend is None:
            return [node]
        fcls = find_class("PCGAttributeFilteringRangeSettings")
        if fcls is None:
            warn("range-filter class missing — proximity collapse skipped "
                 "(towers stay full size near the controller)")
            return [node]
        attr, tmin, tmax = pend["attr"], pend["tmin"], pend["tmax"]
        span = tmax - tmin
        # (band lower frac, band upper frac, scale multiplier or None=passthrough);
        # points below the first band are culled = fully collapsed
        bands = [(0.15, 0.5, 0.22), (0.5, 0.85, 0.6), (0.85, None, None)]
        ends = []
        for bi, (f0, f1, factor) in enumerate(bands):
            filt, fs = add_node(self.g, fcls, "%s_Band%d" % (name, bi), self.pos())
            try:
                sel = fs.get_editor_property("target_attribute")
                sel_dsl(sel, attr)
                fs.set_editor_property("target_attribute", sel)
                lo = tmin + f0 * span
                hi = (tmax + abs(span) * 0.01 + 1e-4) if f1 is None else tmin + f1 * span
                for prop, val, incl in (("min_threshold", lo, True),
                                        ("max_threshold", hi, f1 is None)):
                    th = fs.get_editor_property(prop)
                    safe_set(th, "use_constant_threshold", True, "Band")
                    safe_set(th, "inclusive", incl, "Band")
                    const = th.get_editor_property("attribute_types")
                    ty = enum_val("EPCGMetadataTypes", "DOUBLE")
                    if ty is not None:
                        safe_set(const, "type", ty, "Band")
                    safe_set(const, "double_value", float(val), "Band")
                    safe_set(th, "attribute_types", const, "Band")
                    fs.set_editor_property(prop, th)
            except Exception as e:
                warn("collapse band %d config: %s — proximity collapse skipped"
                     % (bi, e))
                return [node]
            connect(self.g, node, filt, preferred_in="In")
            end = filt
            if factor is not None:
                tp, ts = add_node(self.g, unreal.PCGTransformPointsSettings,
                                  "%s_Band%dScale" % (name, bi), self.pos())
                v = unreal.Vector(factor, factor, factor)
                safe_set(ts, "scale_min", v, "TransformPoints")
                safe_set(ts, "scale_max", v, "TransformPoints")
                safe_set(ts, "absolute_scale", False, "TransformPoints")
                connect(self.g, filt, tp, preferred_out="InsideFilter")
                end = tp
            ends.append(end)
        return ends

    def _det_euler_args(self, m):
        """instance.rotate with a fully deterministic rotation -> [x, y, z]
        component exprs (radians, Blender XYZ euler). Handles
        euler_to_rotation(vec3(...)), euler_to_rotation({const}), and a plain
        {const: [x, y, z]} rotation socket value."""
        if m["type"] != "instance.rotate":
            return None
        e = m["rotation"]
        if expr_has_random(e):
            return None
        if "const" in e and isinstance(e["const"], list):
            return [{"const": float(c)} for c in e["const"][:3]]
        if e.get("op") != "euler_to_rotation":
            return None
        v = e["args"][0]
        if "const" in v and isinstance(v["const"], list):
            return [{"const": float(c)} for c in v["const"][:3]]
        if v.get("op") == "vec3":
            return v["args"]
        return None

    def emit_create_points(self, name, geo, on_points, scale, det_eulers=()):
        node, settings = add_node(self.g, unreal.PCGCreatePointsSettings,
                                  name + "_Points", self.pos())
        # Points carry Blender-absolute coordinates. Left in the default World
        # space they always generate at the world origin, ignoring where the
        # PCG volume was placed; Local makes the effect sit on (and follow)
        # its volume. NOTE: the volume's SCALE then scales the effect too, so
        # keep the volume at scale 1 for Blender's exact size.
        cs = enum_val("EPCGCoordinateSpace", "LOCAL_COMPONENT", "ORIGINAL_COMPONENT")
        if cs is not None:
            safe_set(settings, "coordinate_space", cs, "CreatePoints")
        safe_set(settings, "cull_points_outside_volume", False, "CreatePoints")
        pts = []
        rot_expr = on_points.get("rotation")
        for i in range(len(geo["P"])):
            p = unreal.PCGPoint()
            env = self.k.env_for(geo, i)
            rot = unreal.Rotator(0, 0, 0)
            if rot_expr and rot_expr.get("attr") == "rotation" and "T" in geo:
                # curve-frame path (bridge planks): fold z-components as roll
                tilt = 0.0
                for args, _local in det_eulers:
                    v = self.eval_maybe(args[2], env, 0.0)
                    tilt += float(v or 0.0)
                rot = frame_rotator(geo["T"][i], tilt)
            elif det_eulers:
                # general path (point.create sources): compose actual rotation
                # matrices per point, then convert once to UE handedness
                m3 = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
                for args, local in det_eulers:
                    comps = [float(self.eval_maybe(a, env, 0.0) or 0.0) for a in args]
                    step = euler_xyz_matrix(*comps)
                    m3 = mat3_mul(m3, step) if local else mat3_mul(step, m3)
                rot = mat3_to_ue_rotator(m3)
            sc = scale
            xf = unreal.Transform()
            xf.translation = to_ue_pos(geo["P"][i])
            xf.rotation = rot.quaternion()
            xf.scale3d = unreal.Vector(sc[0], sc[1], sc[2])
            p.set_editor_property("transform", xf)
            safe_set(p, "seed", i * 7919 + 42, "PCGPoint")
            pts.append(p)
        settings.set_editor_property("points_to_create", pts)
        return node

    # ------------------------------------------------ V1.x: actor binding
    def emit_actor_node(self, obj_name):
        """Get Actor Data (single point, by tag = Blender object name). PCG
        tracks selected actors, so moving the tagged actor regenerates."""
        if obj_name in self.actor_nodes:
            return self.actor_nodes[obj_name]
        cls = find_class("PCGDataFromActorSettings", "PCGGetActorDataSettings")
        if cls is None:
            warn("no Get Actor Data settings class — actor binding unavailable")
            return None
        node, s = add_node(self.g, cls, "Actor %s" % obj_name, (self.x, -300))
        mode = enum_val("EPCGGetDataFromActorMode", "GET_SINGLE_POINT")
        if mode is not None:
            safe_set(s, "mode", mode, "DataFromActor")
        # without this, PCG caches the actor snapshot and manual regenerations
        # keep seeing the actor's old transform
        safe_set(s, "always_requery_actors", True, "DataFromActor")
        # ...and without this, moving the actor OUTSIDE the volume's brush
        # bounds (a 2m box at scale 1) stops triggering auto-regeneration —
        # the live proximity effect appears frozen until a manual regen
        safe_set(s, "track_actors_only_within_bounds", False, "DataFromActor")
        try:
            sel = s.get_editor_property("actor_selector")
            f = enum_val("EPCGActorFilter", "ALL_WORLD_ACTORS")
            if f is not None:
                safe_set(sel, "actor_filter", f, "ActorSelector")
            by_tag = enum_val("EPCGActorSelection", "BY_TAG")
            if by_tag is not None:
                safe_set(sel, "actor_selection", by_tag, "ActorSelector")
            safe_set(sel, "actor_selection_tag", obj_name, "ActorSelector")
            safe_set(sel, "must_overlap_self", False, "ActorSelector")
            s.set_editor_property("actor_selector", sel)
        except Exception as e:
            warn("actor selector for %r: %s" % (obj_name, e))
        log("actor binding: tag %r (tag any UE actor with this to drive the effect)"
            % obj_name)
        self.actor_nodes[obj_name] = node
        return node

    def emit_scale_by_attr(self, nm, node, attr, comps, op="Multiply",
                           vmin=0.0, vmax=1000000.0):
        """Custom PCG node from the plugin's GNuePCG module: point scale
        *= attribute, per component. UE 5.8's stock Attribute Maths Op (and
        every other PCGMetadata* op) silently emits no data, so this is the
        only way to do exact per-point scale math. Returns None when the
        module isn't compiled in — callers fall back to approximations."""
        cls = find_class("GNueScaleByAttributeSettings")
        if cls is None:
            return None
        sn, ss = add_node(self.g, cls, nm, self.pos())
        try:
            sel = ss.get_editor_property("scale_source")
            sel_dsl(sel, attr)
            ss.set_editor_property("scale_source", sel)
        except Exception as e:
            warn("scale-by-attr source %r: %s" % (attr, e))
            return None
        o = enum_val("EGNueScaleOp", op.upper())
        if o is not None:
            safe_set(ss, "operation", o, "GNueScale")
        for c in "XYZ":
            safe_set(ss, "scale_%s" % c.lower(), c in comps, "GNueScale")
        safe_set(ss, "value_min", float(vmin), "GNueScale")
        safe_set(ss, "value_max", float(vmax), "GNueScale")
        connect(self.g, node, sn)
        return sn

    def _dynamic_falloff(self, name, dyn):
        """Proximity collapse as a per-frame WPO material instead of PCG nodes.
        Returns the material, or None to use the PCG path."""
        if not self.dynamics_enabled or not self.asset_root:
            return None
        mpc = ensure_controller_collection(dyn["object"])
        if mpc is None:
            return None
        safe = "".join(c if c.isalnum() else "_" for c in name)
        mat_name = "M_GNueDyn_" + safe
        # A scale that drives X/Y/Z from the same controller decomposes into one
        # actor factor per component; build the material ONCE per name, else the
        # rebuilds stack tangled duplicate node chains onto the same asset and
        # the World Position Offset stops computing correctly.
        if not hasattr(self, "_dyn_mat_cache"):
            self._dyn_mat_cache = {}
        if mat_name in self._dyn_mat_cache:
            return self._dyn_mat_cache[mat_name]
        mat = build_dynamic_material(
            self.asset_root, mat_name, mpc,
            float(dyn["fmin"]) * M2CM, float(dyn["fmax"]) * M2CM,
            float(dyn["tmin"]), float(dyn["tmax"]))
        self._dyn_mat_cache[mat_name] = mat
        return mat

    def emit_actor_falloff(self, name, node, dyn):
        """points -> Distance(to actor point) -> Remap -> multiply into $Scale.
        Preferred: no PCG nodes at all — the collapse runs in the dynamics
        material every frame (see _dynamic_falloff); the PCG chain below is
        the fallback when that can't be built."""
        mat = self._dynamic_falloff(name, dyn)
        if mat is not None:
            self.dyn_materials[self._current_group] = mat
            log("%s: proximity collapse is shader-driven (tag %r) — no "
                "regeneration needed when the controller moves"
                % (name, dyn["object"]))
            return node
        actor = self.emit_actor_node(dyn["object"])
        if actor is None:
            return node
        dcls = find_class("PCGDistanceSettings")
        rcls = find_class("PCGAttributeRemapSettings")
        if not (dcls and rcls):
            warn("distance/remap classes missing — actor falloff skipped")
            return node
        attr = "gnue_fall"
        dist, ds = add_node(self.g, dcls, name + "_Dist", self.pos())
        safe_set(ds, "output_to_attribute", True, "Distance")
        try:
            sel = ds.get_editor_property("output_attribute")
            sel_dsl(sel, attr)
            ds.set_editor_property("output_attribute", sel)
        except Exception as e:
            warn("distance attr: %s" % e)
        shape = enum_val("PCGDistanceShape", "CENTER") or enum_val("EPCGDistanceShape", "CENTER")
        for prop in ("source_shape", "target_shape"):
            if shape is not None:
                safe_set(ds, prop, shape, "Distance")
        safe_set(ds, "maximum_distance",
                 max(100.0, dyn["fmax"] * M2CM * 4.0), "Distance")
        connect(self.g, node, dist, preferred_in="Source")
        # Distance with an EMPTY Target outputs nothing and silently kills the
        # whole chain — which is exactly what happens when the user hasn't
        # tagged a controller actor yet. Merge the controller with a sentinel
        # point 100km up: no controller -> huge distance -> falloff clamps to
        # 1.0 and the effect renders at full size instead of vanishing.
        target = actor
        mcls = find_class("PCGMergeSettings", "PCGMergePointsSettings")
        if mcls is not None:
            sent, ss = add_node(self.g, unreal.PCGCreatePointsSettings,
                                name + "_NoCtrlSentinel", self.pos())
            pt = unreal.PCGPoint()
            xf = unreal.Transform()
            xf.translation = unreal.Vector(0, 0, 1e7)
            pt.set_editor_property("transform", xf)
            ss.set_editor_property("points_to_create", [pt])
            merge, _ms = add_node(self.g, mcls, name + "_CtrlOrFar", self.pos())
            connect(self.g, actor, merge)
            connect(self.g, sent, merge)
            target = merge
        else:
            warn("PCG Merge node missing — effect disappears entirely if no "
                 "actor is tagged %r" % dyn["object"])
        connect(self.g, target, dist, preferred_in="Target")

        remap, rs = add_node(self.g, rcls, name + "_Falloff", self.pos())
        try:
            sel = rs.get_editor_property("input_source")
            sel_dsl(sel, attr)
            rs.set_editor_property("input_source", sel)
        except Exception as e:
            warn("remap source: %s" % e)
        safe_set(rs, "range_min", dyn["fmin"] * M2CM, "Remap")
        safe_set(rs, "range_max", dyn["fmax"] * M2CM, "Remap")
        safe_set(rs, "out_range_min", dyn["tmin"], "Remap")
        safe_set(rs, "out_range_max", dyn["tmax"], "Remap")
        safe_set(rs, "clamp_to_unit_range", True, "Remap")
        connect(self.g, dist, remap)
        # UE 5.8's Attribute Maths Op runs as a silent no-op (no output data,
        # no log), so the smooth scale multiply is approximated with discrete
        # collapse bands, split off at the end of the chain (emit_group).
        comps = dyn.get("comps") or ["X", "Y", "Z"]
        exact = self.emit_scale_by_attr(name + "_Apply", remap, attr, comps,
                                        vmin=min(dyn["tmin"], dyn["tmax"]),
                                        vmax=max(dyn["tmin"], dyn["tmax"]))
        if exact is not None:
            log("%s: proximity falloff multiplies $Scale.%s per point (smooth, "
                "exact)" % (name, "".join(comps)))
            return exact
        # no GNuePCG module: approximate the smooth falloff with scale bands
        self.pending_falloff = {"attr": attr, "tmin": float(dyn["tmin"]),
                                "tmax": float(dyn["tmax"]), "name": name}
        warn("%s: GNuePCG module not available — proximity falloff approximated "
             "with discrete collapse bands (rebuild the plugin's C++ for smooth "
             "scaling)" % name)
        return remap

    # ------------------------------------------------ V1.x: spatial noise
    def _noise3d(self, nm, node, dyn, mode, out_min=0.0, out_max=1.0,
                 comps=("Z",)):
        """GNue Noise 3D (C++ module) — true 3D Perlin like Blender's Noise
        Texture. The stock Spatial Noise node is 2D-only, so on vertical
        surfaces whole columns share one value (straight stripes instead of
        organic patches). Returns None when the module isn't built."""
        cls = find_class("GNueNoise3DSettings")
        if cls is None:
            return None
        n, st = add_node(self.g, cls, nm, self.pos())
        out = enum_val("EGNueNoiseOutput",
                       "DENSITY" if mode == "Density" else "SCALE_MULTIPLY")
        if out is not None:
            safe_set(st, "output", out, "Noise3D")
        bscale = float(self.eval_maybe(dyn.get("noise_scale"), default=1.0) or 1.0)
        safe_set(st, "noise_scale", max(1e-3, bscale), "Noise3D")
        detail = self.eval_maybe(dyn.get("noise_detail"), default=3.0)
        safe_set(st, "detail", max(1, int(round(float(detail or 3.0)))), "Noise3D")
        try:
            seed = int(getattr(self.k, "params", {}).get("Seed", 0))
        except Exception:
            seed = 0
        safe_set(st, "noise_seed", seed, "Noise3D")
        safe_set(st, "out_min", float(out_min), "Noise3D")
        safe_set(st, "out_max", float(out_max), "Noise3D")
        if mode != "Density":
            safe_set(st, "scale_x", "X" in comps, "Noise3D")
            safe_set(st, "scale_y", "Y" in comps, "Noise3D")
            safe_set(st, "scale_z", "Z" in comps, "Noise3D")
        connect(self.g, node, n)
        log("%s: 3D noise (feature ~%.1fm, %d octaves) -> %s"
            % (nm, 1.0 / max(1e-3, bscale),
               max(1, int(round(float(detail or 3.0)))), mode))
        return n

    def _noise_node(self, nm, node, dyn, attr):
        """Spatial Noise writing `attr`, with Blender's noise frequency.

        PCG samples world-space cm scaled by MAGIC_SCALE_FACTOR (1e-4), so one
        noise cell spans 100 m by default — near-constant over a normal effect,
        which is why unscaled noise made every instance the same size. Blender's
        Noise Texture multiplies position-in-metres by Scale, so matching
        feature size needs transform scale = 100 * blender_scale."""
        ncls = find_class("PCGSpatialNoiseSettings")
        if ncls is None:
            return None
        noise, ns = add_node(self.g, ncls, nm, self.pos())
        try:
            sel = ns.get_editor_property("value_target")
            sel_dsl(sel, attr)
            ns.set_editor_property("value_target", sel)
        except Exception as e:
            warn("noise target: %s" % e)
        bscale = float(self.eval_maybe(dyn.get("noise_scale"), default=1.0) or 1.0)
        freq = max(1e-3, bscale) * 100.0
        try:
            xf = ns.get_editor_property("transform")
            xf.scale3d = unreal.Vector(freq, freq, freq)
            ns.set_editor_property("transform", xf)
        except Exception as e:
            warn("noise frequency: %s" % e)
        detail = self.eval_maybe(dyn.get("noise_detail"), default=None)
        if detail is not None:
            safe_set(ns, "iterations", max(1, int(round(float(detail)))), "Noise")
        # engine noise is centred on 0 and clamps to [0,1]; Blender's fac is
        # centred on 0.5, so lift it to keep the usable spread
        safe_set(ns, "brightness", 0.5, "Noise")
        connect(self.g, node, noise)
        log("%s: spatial noise feature size ~%.1fm (Blender scale %.3f)"
            % (nm, 1.0 / max(1e-3, bscale), bscale))
        return noise

    def emit_noise_scale_z(self, name, node, dyn):
        """Noise -> Remap to the Blender factor range -> multiply into the
        affected scale components (statistical stand-in for Blender's Noise
        Texture: pattern differs, distribution matches)."""
        comps3 = dyn.get("comps", ["Z"])
        n3 = self._noise3d(name + "_NScale", node, dyn, "ScaleMultiply",
                           out_min=dyn["tmin"], out_max=dyn["tmax"],
                           comps=comps3)
        if n3 is not None:
            log("%s: 3D noise multiplies $Scale.%s in [%.2f, %.2f]"
                % (name, "".join(comps3), dyn["tmin"], dyn["tmax"]))
            return n3
        warn("GNuePCG Noise3D unavailable — 2D noise fallback (vertical "
             "surfaces will stripe)")
        rcls = find_class("PCGAttributeRemapSettings")
        attr = "gnue_noise"
        noise = self._noise_node(name + "_Noise", node, dyn, attr)
        if noise is None or rcls is None:
            warn("spatial-noise/remap classes missing — noise factor skipped")
            return node

        comps = dyn.get("comps", ["Z"])
        remap, rs = add_node(self.g, rcls, name + "_NRemap", self.pos())
        try:
            sel = rs.get_editor_property("input_source")
            sel_dsl(sel, attr)
            rs.set_editor_property("input_source", sel)
        except Exception as e:
            warn("noise remap source: %s" % e)
        safe_set(rs, "range_min", 0.0, "Remap")
        safe_set(rs, "range_max", 1.0, "Remap")
        safe_set(rs, "out_range_min", dyn["tmin"], "Remap")
        safe_set(rs, "out_range_max", dyn["tmax"], "Remap")
        connect(self.g, noise, remap)

        exact = self.emit_scale_by_attr(name + "_NApply", remap, attr, comps,
                                        vmin=min(dyn["tmin"], dyn["tmax"]),
                                        vmax=max(dyn["tmin"], dyn["tmax"]))
        if exact is not None:
            log("%s: noise multiplies $Scale.%s in [%.2f, %.2f] (keeps the "
                "per-instance random base scale)"
                % (name, "".join(comps), dyn["tmin"], dyn["tmax"]))
            return exact

        # fallback: Remap writes the component directly (loses the random base)
        cur = remap
        for comp in comps:
            try:
                sel = rs.get_editor_property("output_target")
                sel_dsl(sel, "$Scale.%s" % comp)
                rs.set_editor_property("output_target", sel)
            except Exception as e:
                warn("noise remap target: %s" % e)
            break
        if len(comps) > 1:
            warn("%s: without the GNuePCG module only $Scale.%s gets the noise "
                 "factor" % (name, comps[0]))
        warn("%s: GNuePCG module not available — noise SETS the scale component "
             "instead of multiplying (per-instance size variety is lost)" % name)
        return cur

    # ------------------------------------------------ V1.x: greebles
    def emit_greebles(self, name, group, gsize):
        target_id = group.get("target_on_points")
        target_node = self.chain_final.get(target_id)
        if target_node is None:
            warn("greeble group %s: target instance chain not emitted — skipped" % name)
            return None
        tgt_block = self.k.blocks.get(target_id, {})
        tgt_spec = tgt_block.get("instance", {})
        # Copy Points inherits the target's scale (so greebles collapse with
        # their tower, as they vanish in Blender when its surface shrinks).
        # Blender sizes them absolutely though, so divide the target's rest
        # scale back out to land on the authored size.
        tgt_scale = self.typical_scale.get(target_id)
        if tgt_scale:
            gsize = [gsize[i] / max(1e-4, tgt_scale[i]) for i in range(3)]
            log("greebles: size compensated for target scale %s (Copy Points "
                "multiplies it back in)" % [round(v, 3) for v in tgt_scale])
        bottom = "bottom" in str(tgt_spec.get("asset", ""))
        dens = float(self.eval_maybe(group["scatter"]["density"], default=4.0) or 4.0)
        seed = int(self.eval_maybe(group["scatter"]["seed"], default=0) or 0)
        # per-instance sample count ~ density x sampled surface area of the
        # target asset box (5 faces, bottom skipped) at its base size
        tsize = self.eval_maybe(tgt_spec.get("size", {"const": [1, 1, 1]}),
                                default=[1, 1, 1])
        tsize = tsize if isinstance(tsize, list) else [tsize] * 3
        area = (tsize[0] * tsize[1]            # top
                + 2 * tsize[0] * tsize[2]      # x faces
                + 2 * tsize[1] * tsize[2])     # y faces
        k = max(1, min(64, int(round(dens * max(0.25, area)))))
        log("greebles: %d samples per instance (%.1f/m^2 x %.2fm^2 box surface; "
            "per-instance scale not included — statistical)" % (k, dens, area))

        import random as _random
        rng = _random.Random(seed * 7919 + 17)
        node, settings = add_node(self.g, unreal.PCGCreatePointsSettings,
                                  name + "_Cloud", self.pos())
        faces = [((1, 0, 0), "x+"), ((-1, 0, 0), "x-"),
                 ((0, 1, 0), "y+"), ((0, -1, 0), "y-"), ((0, 0, 1), "z+")]
        pts = []
        for i in range(k):
            nrm, _tag = faces[rng.randrange(len(faces))]
            u, v = rng.uniform(-0.45, 0.45), rng.uniform(-0.45, 0.45)
            if nrm[0]:
                pos = [0.5 * nrm[0], u, (v + 0.5) if bottom else v]
            elif nrm[1]:
                pos = [u, 0.5 * nrm[1], (v + 0.5) if bottom else v]
            else:
                pos = [u, v, 1.0 if bottom else 0.5]
            # frame: local +Z along the face normal, random twist around it
            z = list(nrm)
            x0 = [0, 0, 1] if abs(z[2]) < 0.9 else [1, 0, 0]
            x = vnorm(vcross(x0, z))
            y = vcross(z, x)
            tw = rng.uniform(0, 2 * math.pi)
            c, s = math.cos(tw), math.sin(tw)
            xr = [x[j] * c + y[j] * s for j in range(3)]
            yr = [y[j] * c - x[j] * s for j in range(3)]
            m3 = [[xr[0], yr[0], z[0]], [xr[1], yr[1], z[1]], [xr[2], yr[2], z[2]]]
            p = unreal.PCGPoint()
            xf = unreal.Transform()
            xf.translation = unreal.Vector(pos[0] * M2CM, -pos[1] * M2CM, pos[2] * M2CM)
            xf.rotation = mat3_to_ue_rotator(m3).quaternion()
            xf.scale3d = unreal.Vector(gsize[0], gsize[1], gsize[2])
            p.set_editor_property("transform", xf)
            safe_set(p, "seed", i * 6151 + seed, "PCGPoint")
            pts.append(p)
        settings.set_editor_property("points_to_create", pts)

        ccls = find_class("PCGCopyPointsSettings")
        if ccls is None:
            warn("Copy Points class missing — greebles skipped")
            return None
        cp, cs = add_node(self.g, ccls, name + "_OnSurfaces", self.pos())
        rel = enum_val("EPCGCopyPointsInheritanceMode", "RELATIVE")
        if rel is not None:
            safe_set(cs, "rotation_inheritance", rel, "CopyPoints")
            safe_set(cs, "scale_inheritance", rel, "CopyPoints")
        safe_set(cs, "apply_target_rotation_to_positions", True, "CopyPoints")
        safe_set(cs, "apply_target_scale_to_positions", True, "CopyPoints")
        connect(self.g, node, cp, preferred_in="Source")
        targets = target_node if isinstance(target_node, list) else [target_node]
        for t in targets:
            connect(self.g, t, cp, preferred_in="Target")
        return cp

    def ground_surface(self):
        """Scatter surface sources (list): World Ray Hit (any collidable ground
        under the PCG bounds) plus data from any actor tagged `GNueSurface` —
        tag a mesh actor with that to scatter across its surfaces (experimental;
        vertical faces depend on PCG's sampling of that data type). Both feed
        the sampler's Surface pin directly — routing them through a Union node
        yields "No surfaces found" on 5.8, the sampler only accepts surface-ish
        data per-edge (UE inserts a type filter for the actor data)."""
        if getattr(self, "_ground", None) is not None:
            return self._ground
        ray = None
        for cls_name in ("PCGWorldRayHitSettings", "PCGWorldRayHitQuerySettings"):
            cls = getattr(unreal, cls_name, None)
            if cls is not None:
                ray, _ = add_node(self.g, cls, "Ground Surface", (0, -400))
                break
        tagged = None
        acls = find_class("PCGDataFromActorSettings", "PCGGetActorDataSettings")
        if acls is not None:
            tagged, ts = add_node(self.g, acls, "Tagged Surface", (0, -560))
            try:
                sel = ts.get_editor_property("actor_selector")
                f = enum_val("EPCGActorFilter", "ALL_WORLD_ACTORS")
                if f is not None:
                    safe_set(sel, "actor_filter", f, "ActorSelector")
                by_tag = enum_val("EPCGActorSelection", "BY_TAG")
                if by_tag is not None:
                    safe_set(sel, "actor_selection", by_tag, "ActorSelector")
                safe_set(sel, "actor_selection_tag", "GNueSurface", "ActorSelector")
                safe_set(sel, "must_overlap_self", False, "ActorSelector")
                ts.set_editor_property("actor_selector", sel)
            except Exception as e:
                warn("tagged surface selector: %s" % e)
            log("scatter surface: ray-hit ground + any actor tagged 'GNueSurface'")
        sources = [n for n in (ray, tagged) if n is not None]
        if not sources:
            warn("no World Ray Hit settings class found — falling back to graph input "
                 "(scatter only works with landscapes in that mode)")
            fallback = self.g.get_input_node() if hasattr(self.g, "get_input_node") else None
            sources = [fallback] if fallback is not None else []
        self._ground = sources
        return sources

    def _noise_selection(self, sel):
        """selection == noise > threshold (possibly AND-ed with geometric terms
        that stay approximated) -> (threshold, noise leaf), else (None, None)."""
        terms = [sel]
        conj = []
        while terms:
            t = terms.pop()
            if t.get("op") == "bool.and":
                terms.extend(t["args"])
            else:
                conj.append(t)
        thresh, leaf = None, None
        for t in conj:
            if t.get("op") in ("cmp.greater_than", "math.greater_than") \
                    and '"noise"' in json.dumps(t["args"][0]):
                v = self.eval_maybe(t["args"][1], default=None)
                if v is not None:
                    thresh = float(v)
                    leaf = _find_leaf(t["args"][0], "noise")
            else:
                warn("scatter selection term approximated by the sampler surface: %s"
                     % json.dumps(t)[:120])
        return thresh, leaf

    def self_anchor(self):
        """Single point at the PCG volume's own origin (Get Actor Data, default
        self selector) — Copy Points target that places local-space mesh
        samples at (and moving with) the volume."""
        if self._self_anchor is not None:
            return self._self_anchor
        cls = find_class("PCGDataFromActorSettings", "PCGGetActorDataSettings")
        if cls is None:
            return None
        node, st = add_node(self.g, cls, "Self Anchor", (0, -700))
        mode = enum_val("EPCGGetDataFromActorMode", "GET_SINGLE_POINT")
        if mode is not None:
            safe_set(st, "mode", mode, "DataFromActor")
        # without requery, PCG caches the volume's transform and every later
        # move/rescale of the volume warps the placed samples
        safe_set(st, "always_requery_actors", True, "DataFromActor")
        self._self_anchor = node
        return node

    def _poisson_radius(self, density):
        """Blender density (pts/m^2) -> Poisson disk radius (cm). Poisson dart
        throwing fills ~0.68 of the area at min spacing d: N = 0.68*A/d^2, so
        d_cm = sqrt(0.68e4 / density)."""
        return max(1.0, 41.2 / math.sqrt(max(1e-3, float(density))))

    def _mesh_sampler(self, name, density, seed):
        cls = find_class("PCGMeshSamplerSettings")
        if cls is None:
            return None, None
        node, st = add_node(self.g, cls, name, self.pos())
        method = enum_val("EPCGMeshSamplingMethod", "POISSON_SAMPLING")
        if method is not None:
            safe_set(st, "sampling_method", method, "MeshSampler")
        try:
            opts = st.get_editor_property("sampling_options")
            opts.set_editor_property("sampling_radius", self._poisson_radius(density))
            opts.set_editor_property("random_seed", int(seed))
            st.set_editor_property("sampling_options", opts)
        except Exception as e:
            warn("mesh sampler poisson options: %s" % e)
        return node, st

    def _copy_to_anchor(self, name, samples, anchor):
        """Copy local-space mesh samples onto an anchor point — reconstructs
        their world placement (Mesh Sampler discards the component/asset
        transform, its samples are local-space)."""
        ccls = find_class("PCGCopyPointsSettings")
        if ccls is None:
            return None
        cp, cs = add_node(self.g, ccls, name, self.pos())
        rel = enum_val("EPCGCopyPointsInheritanceMode", "RELATIVE")
        if rel is not None:
            safe_set(cs, "rotation_inheritance", rel, "CopyPoints")
            safe_set(cs, "scale_inheritance", rel, "CopyPoints")
        safe_set(cs, "apply_target_rotation_to_positions", True, "CopyPoints")
        safe_set(cs, "apply_target_scale_to_positions", True, "CopyPoints")
        connect(self.g, samples, cp, preferred_in="Source")
        connect(self.g, anchor, cp, preferred_in="Target")
        return cp

    def _tagged_surface_actor(self):
        """Get Actor Data for tag GNueSurface (single point, requeried)."""
        if getattr(self, "_tagged_anchor", None) is not None:
            return self._tagged_anchor
        cls = find_class("PCGDataFromActorSettings", "PCGGetActorDataSettings")
        if cls is None:
            return None
        node, st = add_node(self.g, cls, "Tagged Surface Actor", (0, -840))
        mode = enum_val("EPCGGetDataFromActorMode", "GET_SINGLE_POINT")
        if mode is not None:
            safe_set(st, "mode", mode, "DataFromActor")
        safe_set(st, "always_requery_actors", True, "DataFromActor")
        safe_set(st, "track_actors_only_within_bounds", False, "DataFromActor")
        try:
            sel = st.get_editor_property("actor_selector")
            f = enum_val("EPCGActorFilter", "ALL_WORLD_ACTORS")
            if f is not None:
                safe_set(sel, "actor_filter", f, "ActorSelector")
            by_tag = enum_val("EPCGActorSelection", "BY_TAG")
            if by_tag is not None:
                safe_set(sel, "actor_selection", by_tag, "ActorSelector")
            safe_set(sel, "actor_selection_tag", "GNueSurface", "ActorSelector")
            safe_set(sel, "must_overlap_self", False, "ActorSelector")
            st.set_editor_property("actor_selector", sel)
        except Exception as e:
            warn("tagged surface selector: %s" % e)
        self._tagged_anchor = node
        return node

    def emit_mesh_scatter(self, name, sc):
        """Scatter on the effect's own surface mesh (SM_GNue_Surface shipped in
        the drop): Mesh Sampler (Poisson; +Z follows the face normal, Blender's
        alignment) -> Copy Points onto the volume origin. Also spawns the
        surface itself so the effect arrives visually complete, and samples any
        actor tagged GNueSurface the same way. Returns the point source, or
        None to fall back to ground sampling."""
        if find_class("PCGMeshSamplerSettings") is None:
            warn("Mesh Sampler unavailable (PCGGeometryScriptInterop not loaded)"
                 " — surface mesh shipped but scatter falls back to the UE ground")
            return None
        anchor = self.self_anchor()
        if anchor is None:
            return None
        density = self.eval_maybe(sc["density"], default=1.0)
        seed = self.eval_maybe(sc["seed"], default=0)

        sampler, st = self._mesh_sampler(name + "_MeshSampler", density, seed)
        # surface_mesh is the loaded StaticMesh object (import_fbx returns
        # objects); a /Game path string also works via SoftObjectPath
        assigned = False
        for value in (self.surface_mesh,
                      None if not isinstance(self.surface_mesh, str)
                      else unreal.SoftObjectPath(self.surface_mesh)):
            if value is None:
                continue
            try:
                st.set_editor_property("mesh", value)
                assigned = True
                break
            except Exception:
                continue
        if not assigned:
            warn("mesh sampler: could not assign surface mesh %r" % self.surface_mesh)
            try:
                self.g.remove_node(sampler)
            except Exception:
                pass
            return None
        placed = self._copy_to_anchor(name + "_OnVolume", sampler, anchor)
        if placed is None:
            return None

        # the surface itself, spawned at the volume origin
        vis, vs = add_node(self.g, unreal.PCGCreatePointsSettings,
                           name + "_SurfacePoint", self.pos())
        pt = unreal.PCGPoint()
        pt.set_editor_property("transform", unreal.Transform())
        vs.set_editor_property("points_to_create", [pt])
        cspace = enum_val("EPCGCoordinateSpace", "LOCAL_COMPONENT", "ORIGINAL_COMPONENT")
        if cspace is not None:
            safe_set(vs, "coordinate_space", cspace, "CreatePoints")
        spawner, sps = add_node(self.g, unreal.PCGStaticMeshSpawnerSettings,
                                name + "_SurfaceSpawner", self.pos())
        set_spawner_mesh(sps, self.surface_mesh)
        connect(self.g, vis, spawner)

        # any actor the user tags GNueSurface joins in, sampled the same way
        extras = []
        tagged = self._tagged_surface_actor()
        if tagged is not None:
            tsampler, tst = self._mesh_sampler(name + "_TaggedSampler", density, seed)
            if tsampler is not None:
                safe_set(tst, "extract_mesh_from_input", True, "MeshSampler")
                try:
                    sel = tst.get_editor_property("input_source")
                    sel_dsl(sel, "ActorReference")
                    tst.set_editor_property("input_source", sel)
                except Exception as e:
                    warn("tagged sampler source: %s" % e)
                connect(self.g, tagged, tsampler, preferred_in="In")
                tplaced = self._copy_to_anchor(name + "_OnTagged", tsampler, tagged)
                if tplaced is not None:
                    extras.append(tplaced)
        log("%s: scatter on shipped surface mesh (poisson r=%.1fcm from density"
            " %.2f/m^2; +Z follows the face normal)"
            % (name, self._poisson_radius(density), density))
        self._scatter_extra_sources = extras
        return placed

    def emit_scatter(self, name, group):
        sc = group["scatter"]
        self._scatter_extra_sources = []
        node = None
        if self.surface_mesh and sc.get("surface_kind") == "input":
            node = self.emit_mesh_scatter(name, sc)
        if node is None:
            sampler, s = add_node(self.g, unreal.PCGSurfaceSamplerSettings,
                                  name + "_Sampler", self.pos())
            density = self.eval_maybe(sc["density"], default=1.0)
            safe_set(s, "points_per_squared_meter", float(density), "SurfaceSampler")
            # default 50cm extents cap density far below Blender's — shrink
            safe_set(s, "point_extents", unreal.Vector(4, 4, 4), "SurfaceSampler")
            seed = self.eval_maybe(sc["seed"], default=0)
            safe_set(s, "seed", int(seed), "SurfaceSampler")
            safe_set(s, "unbounded", False, "SurfaceSampler")
            ground = self.ground_surface()
            if ground:
                for src in ground:
                    connect(self.g, src, sampler, preferred_in="Surface")
            else:
                warn("sampler surface unconnected")
            node = sampler
        if self._scatter_extra_sources:
            # identity Transform Points = merge point (multi-edge In), so the
            # tagged-surface samples flow through the same mask/mods/falloff
            merge, _ms = add_node(self.g, unreal.PCGTransformPointsSettings,
                                  name + "_Merge", self.pos())
            connect(self.g, node, merge)
            for extra in self._scatter_extra_sources:
                connect(self.g, extra, merge)
            node = merge
        if sc.get("selection") is not None:
            thresh, leaf = self._noise_selection(sc["selection"])
            ncls = find_class("PCGSpatialNoiseSettings")
            if thresh is not None and ncls is not None:
                # noise -> $Density, then a plain density filter = noise mask
                ndyn = {"noise_scale": (leaf or {}).get("scale"),
                        "noise_detail": (leaf or {}).get("detail")}
                noise = self._noise3d(name + "_Coverage", node, ndyn, "Density")
                if noise is None:
                    warn("GNuePCG Noise3D unavailable — falling back to 2D "
                         "Spatial Noise (vertical surfaces will stripe)")
                    noise = self._noise_node(name + "_Coverage", node, ndyn,
                                             "$Density")
                if noise is None:
                    return node
                filt, fs = add_node(self.g, unreal.PCGDensityFilterSettings,
                                    name + "_CoverageFilter", self.pos())
                safe_set(fs, "lower_bound", max(0.0, min(1.0, thresh)), "DensityFilter")
                safe_set(fs, "upper_bound", 1.0, "DensityFilter")
                connect(self.g, noise, filt)
                node = filt
                log("%s: noise coverage mask lowered (threshold %.2f, statistical)"
                    % (name, thresh))
        return node

    def emit_mods(self, name, node, group, base_scale, is_scatter):
        idx = 0
        if is_scatter:
            # base absolute scale for scatter chains (explicit points carry it already)
            tp, s = add_node(self.g, unreal.PCGTransformPointsSettings,
                             name + "_BaseScale", self.pos())
            safe_set(s, "absolute_scale", True, "TP")
            safe_set(s, "uniform_scale", False, "TP")
            v = unreal.Vector(base_scale[0], base_scale[1], base_scale[2])
            safe_set(s, "scale_min", v, "TP")
            safe_set(s, "scale_max", v, "TP")
            connect(self.g, node, tp)
            node = tp
        for m in group["mods"]:
            idx += 1
            nm = "%s_M%d" % (name, idx)
            if m["type"] == "instance.rotate":
                node = self.mod_rotate(nm, node, m)
            elif m["type"] == "instance.translate":
                node = self.mod_translate(nm, node, m)
            elif m["type"] == "instance.scale":
                node = self.mod_scale(nm, node, m, group)
        return node

    def _random_euler_bounds(self, expr):
        """euler_to_rotation(vec3(...)) with random leaves -> (min,max) radians."""
        if expr.get("op") != "euler_to_rotation":
            return None
        v = expr["args"][0]
        if v.get("op") == "vec3":
            lo, hi = [0.0] * 3, [0.0] * 3
            found = False
            for i, comp in enumerate(v["args"]):
                if "random" in comp:
                    r = comp["random"]
                    lo[i] = float(self.eval_maybe(r.get("min", {"const": 0}), default=0) or 0)
                    hi[i] = float(self.eval_maybe(r.get("max", {"const": 0}), default=0) or 0)
                    found = True
                else:
                    c = self.eval_maybe(comp, default=0.0)
                    lo[i] = hi[i] = float(c or 0.0)
            return (lo, hi) if found else None
        if "random" in v:
            r = v["random"]
            lo = self.eval_maybe(r.get("min"), default=[0, 0, 0])
            hi = self.eval_maybe(r.get("max"), default=[0, 0, 0])
            lo = lo if isinstance(lo, list) else [lo] * 3
            hi = hi if isinstance(hi, list) else [hi] * 3
            return (lo, hi)
        return None

    def mod_rotate(self, nm, node, m):
        bounds = self._random_euler_bounds(m["rotation"])
        if bounds is None:
            args = self._det_euler_args(m)
            if args is not None:
                vals = [self.eval_maybe(a, None, None) for a in args]
                if all(v is not None for v in vals):
                    # constant rotation -> exact TransformPoints (min == max)
                    bounds = ([float(v) for v in vals], [float(v) for v in vals])
                else:
                    warn("%s: per-point deterministic rotation cannot be applied "
                         "after a random modifier / on sampled points — SKIPPED "
                         "(reorder the Blender graph so deterministic rotations "
                         "come first)" % nm)
                    return node
            else:
                warn("%s: unsupported rotation expression — SKIPPED" % nm)
                return node
        lo, hi = bounds
        tp, s = add_node(self.g, unreal.PCGTransformPointsSettings, nm, self.pos())
        safe_set(s, "absolute_rotation", False, "TP")
        safe_set(s, "rotation_min",
                 unreal.Rotator(roll=lo[0] * R2D, pitch=lo[1] * R2D, yaw=lo[2] * R2D), "TP")
        safe_set(s, "rotation_max",
                 unreal.Rotator(roll=hi[0] * R2D, pitch=hi[1] * R2D, yaw=hi[2] * R2D), "TP")
        connect(self.g, node, tp)
        return tp

    def mod_translate(self, nm, node, m):
        e = m["translation"]
        if "random" in e:
            r = e["random"]
            lo = self.eval_maybe(r.get("min"), default=[0, 0, 0])
            hi = self.eval_maybe(r.get("max"), default=[0, 0, 0])
        else:
            c = self.eval_maybe(e, default=[0, 0, 0])
            lo = hi = c if isinstance(c, list) else [0, 0, 0]
        tp, s = add_node(self.g, unreal.PCGTransformPointsSettings, nm, self.pos())
        safe_set(s, "absolute_offset", False, "TP")
        safe_set(s, "offset_min", unreal.Vector(lo[0] * M2CM, -hi[1] * M2CM, lo[2] * M2CM), "TP")
        safe_set(s, "offset_max", unreal.Vector(hi[0] * M2CM, -lo[1] * M2CM, hi[2] * M2CM), "TP")
        connect(self.g, node, tp)
        return tp

    def _typical_scale(self, group, base):
        """Scale of a mid-range instance of this chain, with the asset scale and
        every scale modifier folded in. Proximity falloff counts as 1 (rest
        state, away from the controller); random and noise factors count as
        their mid value. Used to size greebles, which Copy Points multiplies by
        their target's scale."""
        sc = [float(x) for x in base]
        for m in group.get("mods", []):
            if m["type"] != "instance.scale":
                continue
            e = m["scale"]
            comps = e["args"] if e.get("op") == "vec3" else [e, e, e]
            for i, c in enumerate(comps[:3]):
                c = self._deref_named(c, group)
                dyns, residual = [], []
                if self._factor_split(c, dyns, residual):
                    b = self._residual_bounds(residual)
                    if b is not None:
                        sc[i] *= math.sqrt(max(1e-6, b[0]) * max(1e-6, b[1]))
                    for d in dyns:
                        if d["kind"] == "noise":       # actor falloff == 1 at rest
                            sc[i] *= (float(d["tmin"]) + float(d["tmax"])) / 2.0
                else:
                    b = self._comp_bounds(c)
                    if b is not None:
                        sc[i] *= (b[0] + b[1]) / 2.0
        return sc

    def _deref_named(self, e, group):
        """{"attr": "named:X"} -> the stored expression for X, when known."""
        if isinstance(e, dict) and str(e.get("attr", "")).startswith("named:"):
            stored = (group or {}).get("stores", {}).get(e["attr"][6:])
            if stored is not None:
                return stored
        return e

    def _comp_bounds(self, e):
        """(lo, hi) for a scalar expr, random leaves taken at their min/max."""
        a = self.eval_maybe(self._sub_random(e, False), default=None)
        b = self.eval_maybe(self._sub_random(e, True), default=None)
        if a is None or b is None:
            return None
        try:
            a, b = float(a), float(b)
        except (TypeError, ValueError):
            return None
        return (min(a, b), max(a, b))

    def _uniform_random_range(self, e, group):
        """vec3(r,r,r) where r is random / map_range(random) / named random store."""
        if e.get("op") != "vec3":
            return None
        comps = [json.dumps(c, sort_keys=True) for c in e["args"]]
        if len(set(comps)) != 1:
            return None
        r = e["args"][0]
        if r.get("attr", "").startswith("named:"):
            name = r["attr"][6:]
            stored = group.get("stores", {}).get(name)
            if stored is not None:
                r = stored
        if "random" in r:
            lo = float(self.eval_maybe(r["random"].get("min"), default=1.0) or 1.0)
            hi = float(self.eval_maybe(r["random"].get("max"), default=1.0) or 1.0)
            return lo, hi
        if r.get("op") == "map_range" and "random" in r["args"][0]:
            lo = float(self.eval_maybe(r["args"][3], default=1.0) or 1.0)
            hi = float(self.eval_maybe(r["args"][4], default=1.0) or 1.0)
            return lo, hi
        return None

    # ---------------------------------------- V1.x: dynamic scale factors
    def _dyn_factor(self, e):
        """map_range over an actor-distance or noise value -> emission spec."""
        if e.get("op") != "map_range":
            return None
        val_json = json.dumps(e["args"][0])
        spec = {"fmin": float(self.eval_maybe(e["args"][1], default=0.0) or 0.0),
                "fmax": float(self.eval_maybe(e["args"][2], default=1.0) or 1.0),
                "tmin": float(self.eval_maybe(e["args"][3], default=0.0) or 0.0),
                "tmax": float(self.eval_maybe(e["args"][4], default=1.0) or 1.0)}
        if '"actor"' in val_json:
            def find_actor(x):
                if isinstance(x, dict):
                    if "actor" in x:
                        return x["actor"].get("object")
                    for v in x.values():
                        r = find_actor(v)
                        if r:
                            return r
                if isinstance(x, list):
                    for v in x:
                        r = find_actor(v)
                        if r:
                            return r
                return None
            spec.update(kind="actor", object=find_actor(e["args"][0]))
            return spec  # comps filled in by mod_scale
        if '"noise"' in val_json:
            leaf = _find_leaf(e["args"][0], "noise") or {}
            spec.update(kind="noise", noise_scale=leaf.get("scale"),
                        noise_detail=leaf.get("detail"))
            return spec
        return None

    def _factor_split(self, e, dyns, residual):
        """Split a multiplicative scalar expr into dyn factors + a residual
        (random/static) product. False when un-decomposable."""
        if e.get("op") == "math.multiply":
            return all(self._factor_split(a, dyns, residual) for a in e["args"])
        d = self._dyn_factor(e)
        if d is not None:
            dyns.append(d)
            return True
        j = json.dumps(e)
        if '"actor"' in j or '"noise"' in j:
            return False   # dynamic value outside the recognized map_range shape
        residual.append(e)
        return True

    def _sub_random(self, e, use_max):
        if isinstance(e, dict):
            if "random" in e:
                key = "max" if use_max else "min"
                v = self.eval_maybe(e["random"].get(key, {"const": 0}), default=0)
                return {"const": v}
            return {k: self._sub_random(v, use_max) for k, v in e.items()}
        if isinstance(e, list):
            return [self._sub_random(v, use_max) for v in e]
        return e

    def _residual_bounds(self, residual):
        lo = hi = 1.0
        for r in residual:
            a = self.eval_maybe(self._sub_random(r, False), default=None)
            b = self.eval_maybe(self._sub_random(r, True), default=None)
            if a is None or b is None:
                return None
            a, b = float(a), float(b)
            lo *= min(a, b)
            hi *= max(a, b)
        return lo, hi

    def mod_scale(self, nm, node, m, group):
        rng = self._uniform_random_range(m["scale"], group)
        scale_json = json.dumps(m["scale"])
        if rng is None and ('"actor"' in scale_json or '"noise"' in scale_json):
            # dynamic factors present (actor / noise) — decompose per component
            e = m["scale"]
            comps = e["args"] if e.get("op") == "vec3" else [e, e, e]
            split, ok = [], True
            for c in comps:
                dyns, residual = [], []
                if not self._factor_split(c, dyns, residual):
                    ok = False
                    break
                bounds = self._residual_bounds(residual)
                if bounds is None:
                    ok = False
                    break
                split.append((dyns, bounds))
            if ok:
                lo = [split[i][1][0] for i in range(3)]
                hi = [split[i][1][1] for i in range(3)]
                tp, s = add_node(self.g, unreal.PCGTransformPointsSettings, nm, self.pos())
                safe_set(s, "absolute_scale", False, "TP")
                safe_set(s, "uniform_scale", False, "TP")
                safe_set(s, "scale_min", unreal.Vector(*lo), "TP")
                safe_set(s, "scale_max", unreal.Vector(*hi), "TP")
                connect(self.g, node, tp)
                node = tp
                seen = {}
                for ci, (dyns, _b) in enumerate(split):
                    for d in dyns:
                        key = json.dumps(d, sort_keys=True)
                        seen.setdefault(key, {"d": d, "comps": set()})["comps"].add("XYZ"[ci])
                for ent in seen.values():
                    d, cps = ent["d"], sorted(ent["comps"])
                    if d["kind"] == "actor":
                        node = self.emit_actor_falloff(nm, node, dict(d, comps=cps))
                    else:
                        node = self.emit_noise_scale_z(nm, node, dict(d, comps=cps))
                return node
            warn("%s: dynamic scale expression not decomposable — using static eval" % nm)
        tp, s = add_node(self.g, unreal.PCGTransformPointsSettings, nm, self.pos())
        safe_set(s, "absolute_scale", False, "TP")
        if rng is not None:
            safe_set(s, "uniform_scale", True, "TP")
            safe_set(s, "scale_min", unreal.Vector(rng[0], rng[0], rng[0]), "TP")
            safe_set(s, "scale_max", unreal.Vector(rng[1], rng[1], rng[1]), "TP")
            connect(self.g, node, tp)
            return tp
        # per-component [min, max] with random leaves substituted — covers
        # products like random(0.4, 1.6) * Greeble Size, which a plain
        # constant evaluation cannot express (it used to silently yield 1)
        e = m["scale"]
        comps = e["args"] if e.get("op") == "vec3" else [e, e, e]
        comps = [self._deref_named(c, group) for c in comps]
        bounds = [self._comp_bounds(c) for c in comps]
        if all(b is not None for b in bounds):
            uniform = len({json.dumps(c, sort_keys=True) for c in comps}) == 1
            lo = [b[0] for b in bounds]
            hi = [b[1] for b in bounds]
            safe_set(s, "uniform_scale", uniform, "TP")
            safe_set(s, "scale_min", unreal.Vector(*lo), "TP")
            safe_set(s, "scale_max", unreal.Vector(*hi), "TP")
            if lo != hi:
                log("%s: scale varies per instance %s..%s%s"
                    % (nm, [round(x, 3) for x in lo], [round(x, 3) for x in hi],
                       " (uniform)" if uniform else ""))
        else:
            v = self.eval_maybe(e, default=[1, 1, 1])
            v = v if isinstance(v, list) else [v] * 3
            warn("%s: scale expression not evaluable — baked to %s"
                 % (nm, [round(float(x), 3) for x in v]))
            safe_set(s, "uniform_scale", False, "TP")
            safe_set(s, "scale_min", unreal.Vector(*v), "TP")
            safe_set(s, "scale_max", unreal.Vector(*v), "TP")
        connect(self.g, node, tp)
        return tp


# ------------------------------------------------------------- main

def main(folder=None, dest=None, param_overrides=None, meshes_dest=None):
    folder = folder or os.environ.get("GNUE2_DIR") or os.path.join(_REPO, "export", "ropebridge_v1")
    with open(os.path.join(folder, "effect.gnue.json"), "r", encoding="utf-8") as f:
        desc = json.load(f)
    if desc.get("version", "").split(".")[0] != "2":
        raise ImportError2("descriptor version %r is not v2" % desc.get("version"))
    supported = {"actor_binding", "noise", "instance_surface_scatter", "materials",
                 "trim", "accumulate"}
    missing = [f for f in desc.get("requires", []) if f not in supported]
    if missing:
        raise ImportError2("descriptor requires features this importer lacks: %s"
                           % ", ".join(missing))

    name = desc["source"]["node_group"].replace(" ", "_")
    root = dest or os.environ.get("GNUE_DEST", "/Game/GNueImport/" + name)
    params = {p["name"]: p["default"] for p in desc["parameters"]}
    if param_overrides:
        params.update(param_overrides)
        log("parameter overrides applied: %s" % param_overrides)
    log("v2 import: %s -> %s (params baked at defaults; %d blocks)"
        % (folder, root, len(desc["blocks"])))

    meshes = {}
    meshes_root = meshes_dest or (root + "/Meshes")
    for a in desc["assets"]:
        fbx = os.path.join(folder, a["file"].replace("/", os.sep))
        aname = os.path.splitext(os.path.basename(fbx))[0]
        # force only when this import owns the mesh folder — per-volume instance
        # copies share the effect's meshes and must not churn them
        meshes[a["id"]] = import_fbx(fbx, meshes_root, aname, force=(meshes_dest is None))

    surface_path = None
    surf = desc.get("surface_asset")
    if surf:
        sfbx = os.path.join(folder, surf["file"].replace("/", os.sep))
        if os.path.isfile(sfbx):
            surface_path = import_fbx(sfbx, meshes_root,
                                      surf.get("name", "SM_GNue_Surface"),
                                      force=(meshes_dest is None))
            log("surface mesh shipped with the effect: %s (%s tris)"
                % (surface_path, surf.get("tris", "?")))
        else:
            warn("descriptor names a surface mesh but %s is missing" % sfbx)

    kernel = Kernel(desc, params)
    planner = Planner(desc, kernel)
    groups = planner.plan()
    groups.sort(key=lambda g: g["kind"] == "greeble")  # greebles need their targets
    log("%d spawn groups planned" % len(groups))

    tools = unreal.AssetToolsHelpers.get_asset_tools()
    gname = "PCG_" + name
    full = root + "/" + gname
    if unreal.EditorAssetLibrary.does_asset_exist(full):
        # rebuild IN PLACE — deleting the asset would sever every level volume's
        # graph reference (they silently stop generating)
        graph = unreal.EditorAssetLibrary.load_asset(full)
        for nd in list(graph.get_editor_property("nodes")):
            try:
                graph.remove_node(nd)
            except Exception as e:
                warn("remove old node %s: %s" % (nd.get_name(), e))
    else:
        graph = tools.create_asset(gname, root, unreal.PCGGraph, unreal.PCGGraphFactory())

    emitter = Emitter(graph, kernel, desc, meshes)
    emitter.surface_mesh = surface_path
    emitter.asset_root = root
    counts = []
    for i, grp in enumerate(groups):
        counts.append(emitter.emit_group(i, grp))

    # declare Blender parameters on the graph (Details-panel sliders) via the
    # optional GNueParams C++ module — 5.8 exposes no scripting API for this
    lib = getattr(unreal, "GNueParamLibrary", None)
    if lib is not None:
        # property-bag names must be identifiers — spaced names silently fail
        spec = [{"name": param_bag_name(p["name"]), "type": str(p["type"]).lower(),
                 "default": p["default"]}
                for p in desc["parameters"]]
        try:
            n = lib.declare_parameters(graph, json.dumps(spec))
            log("declared %s graph parameter(s) via GNueParams" % n)
        except Exception as e:
            warn("parameter declaration failed: %s" % e)
    else:
        log("GNueParams C++ module not loaded — no Details-panel parameters "
            "(values still baked; use the Blender re-export loop)")

    unreal.EditorAssetLibrary.save_loaded_asset(graph)

    nodes = graph.get_editor_property("nodes")
    edges = graph.get_all_edges() if hasattr(graph, "get_all_edges") else []
    result = "PASS" if groups and not any(c == 0 for c in counts) else "CHECK"
    print("GNUE2 IMPORT RESULT: %s%s" % (result, "_WITH_WARNINGS" if WARNINGS else ""))
    print("GNUE2 graph: %s (%d nodes, %d edges, %d groups, counts=%s)"
          % (graph.get_path_name(), len(nodes), len(edges), len(groups), counts))
    for w in WARNINGS:
        print("GNUE2 WARNING: %s" % w)


if __name__ == "__main__":
    main()
