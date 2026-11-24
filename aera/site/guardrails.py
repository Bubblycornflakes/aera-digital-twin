"""Turn a replay result into a bounded, advisory recommendation. The tool never actuates anything.

Rules, all configurable in [guardrails] and [validation]:
1. The suggested DO setpoint stays inside [so_ref_min, so_ref_max], and the controller gains inside the ranges tested in AeroBench.
2. No modelled consent is made worse: one that is within must stay within, and one that already exceeds must not exceed by more.
3. No more time at low DO than today.
4. A change larger than max_setpoint_step is staged into smaller steps (shown only when the recommendation is ready).
5. Only a validated model can produce a recommendation that is "ready for operator review", and only if every consent it relies on
   was itself checked against a recording. Otherwise it is "research only"."""
import numpy as np
from .. import bsm1_dynamic as dyn

READY, RESEARCH, REJECTED = "ready_for_operator_review", "research_only", "rejected"

def staged_plan(current, target, step):
    """Setpoints to move through, each at most `step` from the previous one."""
    n = int(np.ceil(abs(target - current) / step - 1e-9))
    return [round(current + (target - current) * (i + 1) / n, 2) for i in range(n)] if n else []

def made_worse(base, cand):
    """A consent is worse if it flipped to exceeding, or already exceeded and now exceeds by more."""
    if base["status"] == "within" and cand["status"] == "exceeds":
        return True
    return base["status"] == "exceeds" and cand["status"] == "exceeds" and cand.get("value", 0) > base.get("value", 0) + 1e-9

def review(config, candidate, validation, consent_base, consent_cand, low_do_base, low_do_cand):
    g = config.guardrails
    checks = []
    so_ref = candidate.get("so_ref", config.control.do_setpoint)
    inside = g.so_ref_min <= so_ref <= g.so_ref_max
    checks.append(dict(name="Setpoint inside the allowed range", ok=inside, detail=f"{so_ref:g} against {g.so_ref_min:g} to {g.so_ref_max:g}"))
    gains = [(k, candidate[k], dyn.BOUNDS[k]) for k in ("k_do", "ti_do") if k in candidate]
    bad = [f"{k} {v:g} outside {lo:g} to {hi:g}" for k, v, (lo, hi) in gains if not lo <= v <= hi]
    checks.append(dict(name="Controller settings inside the tested ranges", ok=not bad, detail="; ".join(bad) or "within the ranges tested in the benchmark"))
    worse = [b["name"] for b, c in zip(consent_base, consent_cand) if made_worse(b, c)]
    checks.append(dict(name="No modelled consent made worse", ok=not worse, detail=", ".join(worse) or "none worse (a consent that already exceeds must not exceed by more)"))
    do_ok = low_do_cand <= max(low_do_base, 0.01)
    checks.append(dict(name="No more time at low DO than today", ok=do_ok, detail=f"{100 * low_do_cand:.1f}% against {100 * low_do_base:.1f}% (limit 1% or today's value)"))
    blocking = [c["name"] for c in checks if not c["ok"]]
    indicators = validation["indicators"]
    unchecked = sorted({c["tag"] for c in consent_cand if indicators.get(c["tag"], {}).get("ok") is not True})
    if blocking:
        status = REJECTED
    elif validation["status"] == "validated" and not unchecked:
        status = READY
    else:
        status = RESEARCH
    plan = staged_plan(config.control.do_setpoint, so_ref, g.max_setpoint_step) if status == READY else []
    reason = {READY: "The model reproduces your recorded data and the candidate passes every check. A named engineer should review it before any change.",
              RESEARCH: (f"The model is '{validation['status']}', so this is research only." if validation["status"] != "validated" else
                         f"The model is validated, but these limits were never checked against a recording: {', '.join(unchecked)}.") + " Do not change plant settings on this result.",
              REJECTED: "The candidate fails: " + ", ".join(blocking) + "."}[status]
    return dict(status=status, advisory_only=True, reason=reason, checks=checks, staged_setpoints=plan, consents_without_a_check=unchecked,
                statement="This tool does not read from or write to any plant control system. Any change is made by people, not by this software.")
