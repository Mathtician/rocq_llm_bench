"""Fit  log T(q, m) = a_m * d_q + c_m + N(0, sigma^2)  to the output-token counts of
every valid attempt, treating unfinished attempts as right-censored (T >= tokens spent).

    d_q   problem difficulty (number of correct steps needed, in the reference model's log-token units)
    a_m   1 / intelligence: per-step failure rate; a_m < 1 means m needs fewer tokens than the
          reference as problems get harder (log-log slope of m against the reference)
    c_m   verbosity: log tokens per step, relative to the reference

Identification: d is centred (mean 0 over problems) and the reference model has a = 1; c is reported\nrelative to the reference, so it is the log token ratio on a problem of average difficulty.
Censoring: a failed attempt with L tokens contributes  log Phi((mu - log L) / sigma)  (Tobit).

Outputs: per-model parameters with standard errors, problem difficulties, the replicate-noise check,
and the pairwise slope test (predicted a_i / a_j against the OLS slope over problems both finished).

    uv run --group analysis python scripts/fit_tokens.py [--measure cost|tokens|wall|inference] [--ref codex-high] [--per-model-sigma] [--prior-sd 0.5] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import optimize, stats

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from rlb.cost import composite_cost, lower_bound_cost  # noqa: E402
from rlb.runner import load_attempts  # noqa: E402

# every benchmark run; infrastructure checks (proxy, sandbox, tier, red-team) are not samples of anything
EXCLUDE_PREFIXES = ("proxy", "redteam", "codex-tier", "net-", "process", "stall")


def run_dirs(root: Path):
    return sorted(p for p in (root / "results").iterdir() if p.is_dir() and not p.name.startswith(EXCLUDE_PREFIXES))


def output_tokens(a: dict) -> int:
    u = (a.get("harness") or {}).get("usage") or {}
    h = a["config"]["harness"]
    # pi's `output` and agy's `output_tokens` already include reasoning/thinking (they match the
    # proxy's independent count, median ratio 1.00; adding `reasoning`/`thinking_tokens` on top, as
    # this function did until 2026-09-23, overstated them 1.5-1.8x).
    if h == "pi":
        return int(u.get("output") or 0)
    if h == "agy":
        return int(u.get("output_tokens") or 0)
    if h == "cursor":
        # Cursor reports usage once, in the final result event, and after a mid-run reconnect that
        # figure covers only the resumed segment (seen: 126 model calls, 1.4k tokens). Such attempts
        # have no usable token count; wall time is unaffected.
        if cursor_reconnected(a):
            return 0
        return int(u.get("outputTokens") or 0)
    return int(u.get("output_tokens") or (a.get("net") or {}).get("tokens_out") or 0)


def composite_output_tokens(a: dict) -> int:
    """A main attempt's tokens plus those of its subagent attempts (records under sub/<id>/).
    Summing is sound while subagents run the main model; mixed-model composites need a common unit
    (cost: --measure cost)."""
    d = attempt_dir(a)
    subs = [json.loads((d / "sub" / s["id"] / "attempt.json").read_text()) for s in a.get("subattempts") or []
            if (d / "sub" / s["id"] / "attempt.json").exists()]
    if subs:
        assert all(s["config"]["model"] == a["config"]["model"] for s in subs), "mixed-model composite: tokens are not additive"
    return output_tokens(a) + sum(output_tokens(s) for s in subs)


def cursor_reconnected(a: dict) -> bool:
    d = Path(__file__).resolve().parents[1] / "results" / a["run_id"] / a["config"]["name"] / a["problem"] / f"r{a['rep']}"
    out = d / "stdout.txt"
    return out.exists() and '"type":"retry"' in out.read_text(errors="replace")


def attempt_dir(a: dict) -> Path:
    return ROOT / "results" / a["run_id"] / a["config"]["name"] / a["problem"] / f"r{a['rep']}"


def measure(a: dict, kind: str) -> float:
    """What T is: API-equivalent cost (USD, subagents included; rlb.cost), output tokens,
    wall-clock seconds, or seconds the harness spent in inference. 0 = not measurable (dropped)."""
    if kind == "cost":
        c = composite_cost(a, attempt_dir(a))
        if c is None and not a["solved"] and not a.get("subattempts"):
            c = lower_bound_cost(a, attempt_dir(a))  # censored anyway: a lower bound is exact enough
        return c if c is not None else 0
    if kind == "tokens":
        return composite_output_tokens(a)
    if kind == "wall":
        return a["wall_s"]
    if kind == "inference":
        return a.get("inference_s") or 0
    raise ValueError(kind)


def load(root: Path, kind: str = "cost", min_models: int = 2):
    """Valid attempts with a positive measurement, on problems attempted by >= min_models models.
    A problem seen by one model says nothing about that model's a or c: its free d_q absorbs the
    residual exactly (and runs off to +inf if the only attempts are censored).
    Only problems in the current manifest count: a statement since excluded (e.g. found false by the
    minif2f audit) would otherwise enter as an unsolvable, censored problem."""
    current = {p["name"] for p in json.loads((root / "problems" / "manifest.json").read_text())["problems"]}
    rows = []
    for a in load_attempts(run_dirs(root)):
        if a["invalid"] is not None or a["problem"] not in current:
            continue
        t = measure(a, kind)
        if t <= 0:
            continue
        rows.append((a["config"]["name"], a["problem"], math.log(t), bool(a["solved"])))
    models_of = defaultdict(set)
    for m, q, _, _ in rows:
        models_of[q].add(m)
    return [r for r in rows if len(models_of[r[1]]) >= min_models]


class Fit:
    """Parameters: d[Q-1] (the last problem's d makes the mean over problems zero), a[1:M]
    (reference pinned at 1), c[M] (c_m is the log tokens the model needs on a problem of average
    difficulty; reported relative to the reference), log sigma (one, or one per model)."""

    def __init__(self, rows, ref: str, per_model_sigma: bool, prior_sd: float = 0.5):
        self.prior_sd = prior_sd  # Gaussian prior on log a_m: keeps a identified for models with few finished attempts
        self.models = sorted({m for m, _, _, _ in rows}, key=lambda m: (m != ref, m))
        assert self.models[0] == ref, f"reference {ref!r} not in data"
        self.problems = sorted({q for _, q, _, _ in rows})
        mi = {m: i for i, m in enumerate(self.models)}
        qi = {q: i for i, q in enumerate(self.problems)}
        self.m = np.array([mi[m] for m, _, _, _ in rows])
        self.q = np.array([qi[q] for _, q, _, _ in rows])
        self.y = np.array([y for _, _, y, _ in rows])
        self.done = np.array([s for _, _, _, s in rows])
        self.per_model_sigma = per_model_sigma
        self.M, self.Q = len(self.models), len(self.problems)
        self.n_sigma = self.M if per_model_sigma else 1
        self.iQ, self.iA, self.iC = 0, self.Q - 1, self.Q - 1 + self.M - 1
        self.iS = self.iC + self.M
        self.n = self.iS + self.n_sigma

    def unpack(self, theta):
        D = theta[self.iQ : self.iA]
        d = np.concatenate([D, [-D.sum()]])
        a = np.concatenate([[1.0], np.exp(theta[self.iA : self.iC])])  # stored as log a
        c = theta[self.iC : self.iS]
        ls = theta[self.iS :]
        sigma = np.exp(ls if self.per_model_sigma else np.repeat(ls, self.M))
        return d, a, c, sigma

    def nll_grad(self, theta):
        d, a, c, sigma = self.unpack(theta)
        mu = a[self.m] * d[self.q] + c[self.m]
        s = sigma[self.m]
        z = (self.y - mu) / s
        dn = self.done
        ll = np.empty_like(z); g_mu = np.empty_like(z); g_ls = np.empty_like(z)
        ll[dn] = stats.norm.logpdf(z[dn]) - np.log(s[dn]); g_mu[dn] = z[dn] / s[dn]; g_ls[dn] = z[dn] ** 2 - 1
        zc = z[~dn]; lsf = stats.norm.logsf(zc); h = np.exp(stats.norm.logpdf(zc) - lsf)  # hazard pdf/sf
        ll[~dn] = lsf; g_mu[~dn] = h / s[~dn]; g_ls[~dn] = h * zc
        g = np.zeros(self.n)
        gd = np.bincount(self.q, g_mu * a[self.m], minlength=self.Q)
        g[self.iQ : self.iA] = gd[:-1] - gd[-1]
        g[self.iA : self.iC] = np.bincount(self.m, g_mu * d[self.q], minlength=self.M)[1:] * a[1:]  # d/d(log a)
        g[self.iC : self.iS] = np.bincount(self.m, g_mu, minlength=self.M)
        gs = np.bincount(self.m, g_ls, minlength=self.M)
        g[self.iS :] = gs if self.per_model_sigma else gs.sum()
        la = np.log(a[1:])
        pen = (la ** 2).sum() / (2 * self.prior_sd ** 2)
        g[self.iA : self.iC] -= la / self.prior_sd ** 2
        return -ll.sum() + pen, -g

    def nll(self, theta):
        return self.nll_grad(theta)[0]

    def init(self):
        d = np.full(self.Q, self.y.mean())
        for j in range(self.Q):
            sel = (self.q == j) & self.done
            if sel.any():
                d[j] = self.y[sel].mean()
        d -= d.mean()
        c = np.array([self.y[(self.m == i) & self.done].mean() if ((self.m == i) & self.done).any() else self.y.mean() for i in range(self.M)])
        return np.concatenate([d[:-1], np.zeros(self.M - 1), c, np.zeros(self.n_sigma)])

    def run(self):
        bounds = [(None, None)] * self.iS + [(math.log(0.1), math.log(5.0))] * self.n_sigma  # sigma in [0.1, 5]
        res = optimize.minimize(self.nll_grad, self.init(), jac=True, method="L-BFGS-B", bounds=bounds,
                                options={"maxiter": 20000, "maxfun": 200000, "ftol": 1e-12, "gtol": 1e-8})
        assert res.success, res.message
        self.theta = res.x
        self.loglik = -res.fun
        H = numerical_hessian(self.nll, self.theta)
        try:
            cov = np.linalg.inv(H)
            self.se = np.sqrt(np.maximum(np.diag(cov), 0))
            # d_last = -sum(D): its variance is 1' cov_D 1
            cD = cov[self.iQ : self.iA, self.iQ : self.iA]
            self.se_dlast = math.sqrt(max(cD.sum(), 0))
        except np.linalg.LinAlgError:
            self.se = np.full_like(self.theta, np.nan); self.se_dlast = float("nan")
        return self


def numerical_hessian(f, x, eps=1e-4):
    n = len(x)
    H = np.zeros((n, n))
    f0 = f(x)
    for i in range(n):
        for j in range(i, n):
            xpp = x.copy(); xpp[i] += eps; xpp[j] += eps
            xpm = x.copy(); xpm[i] += eps; xpm[j] -= eps
            xmp = x.copy(); xmp[i] -= eps; xmp[j] += eps
            xmm = x.copy(); xmm[i] -= eps; xmm[j] -= eps
            H[i, j] = H[j, i] = (f(xpp) - f(xpm) - f(xmp) + f(xmm)) / (4 * eps * eps)
    return H


def replicate_sigma(rows):
    """Pooled within-(model, problem) SD of log tokens over finished attempts: the noise floor."""
    cells = defaultdict(list)
    for m, q, y, s in rows:
        if s:
            cells[(m, q)].append(y)
    ss, df = 0.0, 0
    for ys in cells.values():
        if len(ys) > 1:
            ss += sum((v - np.mean(ys)) ** 2 for v in ys)
            df += len(ys) - 1
    return (math.sqrt(ss / df) if df else float("nan")), df


def slope_test(rows, fit: Fit, a, min_shared=6):
    """For each model pair: OLS slope of log T_j on log T_i over problems both finished (cell means)
    vs the fitted prediction a_j / a_i."""
    cell = defaultdict(list)
    for m, q, y, s in rows:
        if s:
            cell[(m, q)].append(y)
    mean = {k: np.mean(v) for k, v in cell.items()}
    out = []
    for i, mi in enumerate(fit.models):
        for j, mj in enumerate(fit.models):
            if j <= i:
                continue
            shared = [q for q in fit.problems if (mi, q) in mean and (mj, q) in mean]
            if len(shared) < min_shared:
                continue
            x = np.array([mean[(mi, q)] for q in shared]); yv = np.array([mean[(mj, q)] for q in shared])
            slope, intercept, r, p, se = stats.linregress(x, yv)
            out.append((mi, mj, len(shared), slope, se, a[j] / a[i], r * r))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="codex-high")
    ap.add_argument("--per-model-sigma", action="store_true")
    ap.add_argument("--prior-sd", type=float, default=0.5, help="SD of the Gaussian prior on log a_m (0 = none)")
    ap.add_argument("--measure", choices=["cost", "tokens", "wall", "inference"], default="cost",
                    help="what T measures (cost: API-equivalent USD, the unit that adds up across models)")
    ap.add_argument("--json")
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    rows = load(root, args.measure)
    unit = {"cost": "USD (API-equivalent)", "tokens": "tokens", "wall": "s wall", "inference": "s inference"}[args.measure]
    n_done = sum(1 for r in rows if r[3])
    print(f"{len(rows)} attempts ({n_done} finished, {len(rows) - n_done} censored), "
          f"{len({r[0] for r in rows})} models, {len({r[1] for r in rows})} problems; reference = {args.ref}; T = {unit}\n")

    fit = Fit(rows, args.ref, args.per_model_sigma, args.prior_sd or 1e9).run()
    d, a, c, sigma = fit.unpack(fit.theta)
    se_d = np.concatenate([fit.se[fit.iQ : fit.iA], [fit.se_dlast]])
    se_a = np.concatenate([[0], fit.se[fit.iA : fit.iC] * a[1:]])  # delta method from log a
    se_c = fit.se[fit.iC : fit.iS]
    c_rel = c - c[0]
    k = len(fit.theta)
    print(f"penalised log-likelihood {fit.loglik:.1f}   parameters {k}   AIC {2 * k - 2 * fit.loglik:.1f}   prior on log a: N(0, {args.prior_sd}²)")
    rs, df = replicate_sigma(rows)
    print(f"sigma (fit) = {sigma[0]:.3f}" + ("" if not args.per_model_sigma else " (reference model)")
          + f"   replicate noise floor = {rs:.3f} on {df} df  (log units; x{math.exp(sigma[0]):.2f} vs x{math.exp(rs):.2f})")
    print(f"d is centred: d = 0 is the average problem; the reference needs e^c_ref = {math.exp(c[0]):,.4g} {unit} there.\n")

    counts = defaultdict(lambda: [0, 0])
    for m, q, y, s in rows:
        counts[m][0] += 1; counts[m][1] += s
    print("| model | n (finished) | a = 1/intelligence | c − c_ref (at avg difficulty) | T vs ref | " + ("sigma_m |" if args.per_model_sigma else ""))
    print("|---|---|---|---|---|" + ("---|" if args.per_model_sigma else ""))
    for i in np.argsort(a):
        m = fit.models[i]
        line = f"| {m} | {counts[m][0]} ({counts[m][1]}) | {a[i]:.2f} ± {se_a[i]:.2f} | {c_rel[i]:+.2f} ± {se_c[i]:.2f} | x{math.exp(c_rel[i]):.2f} |"
        if args.per_model_sigma:
            line += f" {sigma[i]:.2f} |"
        print(line)

    print(f"\n| problem | d (centred) | ref {unit} | attempts |")
    print("|---|---|---|---|")
    qcount = defaultdict(int)
    for _, q, _, _ in rows:
        qcount[q] += 1
    for j in np.argsort(d):
        q = fit.problems[j]
        print(f"| {q} | {d[j]:+.2f} ± {se_d[j]:.2f} | {math.exp(d[j] + c[0]):,.4g} | {qcount[q]} |")

    print("\nPairwise slope test (pairs with >= 6 problems both finished): OLS slope of y-model on x-model vs fitted a_y/a_x")
    print("| x | y | shared | OLS slope | fitted | R² |")
    print("|---|---|---|---|---|---|")
    tests = slope_test(rows, fit, a)
    for mi, mj, n, slope, se, pred, r2 in sorted(tests, key=lambda t: -t[2]):
        flag = "" if abs(slope - pred) <= 2 * se else "  <- off by >2 SE"
        print(f"| {mi} | {mj} | {n} | {slope:.2f} ± {se:.2f} | {pred:.2f} | {r2:.2f} |{flag}")

    # residual check per model (finished attempts)
    mu = a[fit.m] * d[fit.q] + c[fit.m]
    res = (fit.y - mu)[fit.done]
    mm = fit.m[fit.done]
    print("\nResidual SD of finished attempts per model (fit sigma is the pooled value):")
    for i, m in enumerate(fit.models):
        r = res[mm == i]
        if len(r) > 2:
            print(f"  {m:32s} n={len(r):3d}  sd={r.std(ddof=1):.2f}  mean={r.mean():+.2f}")

    if args.json:
        json.dump({"ref": args.ref, "loglik": fit.loglik, "sigma": sigma.tolist(),
                   "models": {m: {"a": float(a[i]), "a_se": float(se_a[i]), "c_rel": float(c_rel[i]), "c_se": float(se_c[i])} for i, m in enumerate(fit.models)},
                   "problems": {q: {"d": float(d[j]), "d_se": float(se_d[j])} for j, q in enumerate(fit.problems)},
                   "slope_test": [dict(x=mi, y=mj, n=n, slope=s, se=se, fitted=p, r2=r2) for mi, mj, n, s, se, p, r2 in tests]},
                  open(args.json, "w"), indent=1)


if __name__ == "__main__":
    main()
