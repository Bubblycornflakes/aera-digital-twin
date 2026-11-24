"""Write a standalone HTML report (no external files) from results/runs.

    python -m aera.report results/report.html
"""
import html
import json
import sys
from pathlib import Path
from .leaderboard import ROOT, build

def scatter(history, reference, width=420, height=140):
    energies = [h["energy"] for h in history] + [reference]
    lo, hi = min(energies), max(energies)
    span = (hi - lo) or 1.0
    def y(v):
        return height - 14 - (v - lo) / span * (height - 28)
    def x(i):
        return 30 + i / max(len(history) - 1, 1) * (width - 44)
    dots = "".join(f'<circle cx="{x(i):.1f}" cy="{y(h["energy"]):.1f}" r="3.5" fill="{"#1b9e77" if h["feasible"] else "#d95f02"}"/>'
                   for i, h in enumerate(history))
    return (f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" '
            f'aria-label="Aeration energy per trial"><line x1="30" x2="{width - 14}" y1="{y(reference):.1f}" y2="{y(reference):.1f}" '
            f'stroke="#888" stroke-dasharray="4 3"/><text x="32" y="{y(reference) - 4:.1f}" font-size="9" fill="#666">BSM1 default {reference:.0f}</text>'
            f'{dots}<text x="2" y="{y(lo) + 3:.1f}" font-size="9" fill="#666">{lo:.0f}</text>'
            f'<text x="2" y="{y(hi) + 3:.1f}" font-size="9" fill="#666">{hi:.0f}</text></svg>')

def render(rows, runs):
    e = html.escape
    out = ['<!doctype html><meta charset="utf-8"><title>AeroBench report</title>',
           '<style>body{font:15px/1.5 system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#1d2b2a}'
           'table{border-collapse:collapse;margin:1rem 0}td,th{border:1px solid #ccd;padding:4px 8px;text-align:left}'
           '.ok{color:#1b7f5f}.bad{color:#b5481f}h2{margin-top:2rem}</style>',
           '<h1>AeroBench report</h1><p>Tuning the BSM1 reactor 5 DO controller from a trial budget, scored on unseen scenarios. '
           'Feasible means no effluent limit is exceeded for longer than under the BSM1 default controller in any held-out scenario '
           'and DO stays above 0.5 g/m3 for at least 99% of the time. Simulation of a benchmark plant, not a facility estimate.</p>',
           '<h2>Leaderboard</h2><table><tr><th>Tuner</th><th>Runs</th><th>Feasible (95% interval)</th>'
           '<th>Saving vs default, feasible runs</th><th>Common failures</th></tr>']
    for r in rows:
        fail = ", ".join(f"{k} ({v})" for k, v in r["common_failures"]) or "none"
        out.append(f'<tr><td>{e(r["tuner"])}</td><td>{r["runs"]}</td><td>{r["feasible_rate"]:.0%} ({r.get("feasible_ci", (0, 0))[0]:.0%} to {r.get("feasible_ci", (0, 0))[1]:.0%})</td>'
                                      f'<td>{str(r["mean_saving_feasible_pct"]) + "%" if r["mean_saving_feasible_pct"] is not None else "n/a"}</td><td>{e(fail)}</td></tr>')
    out.append("</table><h2>Runs</h2>")
    for r in runs:
        status = '<span class="ok">feasible</span>' if r["feasible"] else '<span class="bad">infeasible</span>'
        out.append(f'<h3>{e(r["tuner"])} on {e(r["plant"])}, seed {r["seed"]}: {status}</h3>')
        out.append(f'<p>{r["trials"]} trials. Held-out aeration {r["aeration_energy_kwh_d"]:.0f} kWh/d against '
                   f'{r["reference_energy_kwh_d"]:.0f} for the default ({r["saving_pct"]:+.1f}% saving). Submitted: '
                   f'<code>{e(json.dumps({k: round(v, 4) for k, v in r["answer"].items()}))}</code></p>')
        out.append("<table><tr><th>Scenario</th><th>kWh/d</th><th>Default kWh/d</th><th>Result</th><th>Limits exceeded more than default</th></tr>")
        for name, s in r["scenarios"].items():
            rules = ", ".join(f["rule"] for f in s["failures"]) or "none"
            out.append(f'<tr><td>{e(name)}</td><td>{s["aeration_energy_kwh_d"]:.0f}</td><td>{s["reference_energy_kwh_d"]:.0f}</td>'
                       f'<td class="{"ok" if s["feasible"] else "bad"}">{"pass" if s["feasible"] else "fail"}</td><td>{e(rules)}</td></tr>')
        out.append("</table>")
        if r["history"]:
            out.append(scatter(r["history"], r["reference_energy_kwh_d"]))
    return "\n".join(out)

if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "report.html")
    runs = [json.loads(p.read_text()) for p in sorted((ROOT / "runs").glob("*.json"))]
    target.write_text(render(build(), runs))
    print("wrote", target)
