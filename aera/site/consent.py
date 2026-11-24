"""Check modelled effluent against permit-style limits.

Permits differ. Four common shapes are supported and each is configured from your own permit:
- absolute:     no sample may exceed the limit
- percentile:   the Nth percentile of samples must not exceed the limit (optionally with an upper-tier limit no sample may exceed)
- annual_mean:  the mean must not exceed the limit (a window shorter than a year gives only an indication)
- lut:          a look-up table gives the number of failures allowed for the number of samples taken
A "sample" here is a flow-weighted daily mean, a stand-in for a 24 hour composite. Real sampling is usually sparser, so this
is a model-based indication of risk, not a statement of compliance. Check the wording of your own permit."""
import numpy as np

def lut_allowed(table, n):
    """Failures allowed for n samples: the entry for the largest sample count not above n (none if n is below the table)."""
    entries = sorted(table)
    allowed = 0
    for samples, failures in entries:
        if samples <= n:
            allowed = failures
    return allowed

def _evaluate(spec, values):
    """One set of samples against the consent. Returns (ok, value, exceedances, detail)."""
    over = int((values > spec.limit).sum())
    if spec.kind == "absolute":
        worst = float(values.max())
        return worst <= spec.limit, worst, over, f"highest sample {worst:.2f} against a limit of {spec.limit:g}"
    if spec.kind == "percentile":
        value = float(np.percentile(values, spec.percentile))
        ok, detail = value <= spec.limit, f"{spec.percentile:g}th percentile {value:.2f} against a limit of {spec.limit:g}"
        if spec.upper_tier is not None and values.max() > spec.upper_tier:
            ok, detail = False, detail + f"; highest sample {float(values.max()):.2f} exceeds the upper tier {spec.upper_tier:g}"
        return ok, value, over, detail
    if spec.kind == "annual_mean":
        value = float(values.mean())
        return value <= spec.limit, value, over, f"mean {value:.2f} against a limit of {spec.limit:g} (a short window only indicates the annual mean)"
    allowed = lut_allowed(spec.lut, len(values))
    note = "" if len(values) >= min(n for n, _ in spec.lut) else "; the window has fewer samples than the table's first row, so the allowance is 0 here: indicative only"
    return over <= allowed, float(over), over, f"{over} of {len(values)} samples over {spec.limit:g}; the table allows {allowed}{note}"

def check(spec, daily):
    """spec: ConsentSpec. daily: Series of daily effluent concentrations on local calendar days.
    With sample_every_days = N the result is the WORST of the N possible sampling phases, because which days a regulator samples
    is not known in advance."""
    calendar = daily.asfreq("D")                          # missing days stay as gaps, so spacing is in real days
    n = spec.sample_every_days
    results = []
    for phase in range(n):
        values = calendar.to_numpy()[phase::n]
        values = values[~np.isnan(values)]
        if len(values):
            results.append(_evaluate(spec, values) + (len(values),))
    base = dict(name=spec.name, tag=spec.tag, kind=spec.kind, limit=spec.limit)
    if not results:
        return dict(base, samples=0, status="no_data", detail="No samples in the window.")
    failing = [r for r in results if not r[0]]
    ok, value, over, detail, count = failing[0] if failing else max(results, key=lambda r: r[1])
    if n > 1:
        detail += f" (worst of {n} sampling phases, one sample every {n} days)"
    margin = None if spec.kind == "lut" else round(100 * (spec.limit - value) / spec.limit, 1)
    return dict(base, samples=count, status="within" if ok else "exceeds", value=round(float(value), 3), exceedances=over, margin_pct=margin,
                detail=detail + "; days are the works' local calendar days")
