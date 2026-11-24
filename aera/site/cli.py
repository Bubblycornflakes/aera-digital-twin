"""Command line for the site tools.  python -m aera.site --help

    init <folder>            create a folder with a template configuration to fill in
    check <site.toml>        read your data and report what is wrong with it (no model is run)
    replay <site.toml>       shadow mode: validate the model on your data and compare a candidate DO setpoint
    watch <site.toml>        run shadow mode automatically whenever a new CSV export appears in an inbox folder (read only)
    approve <report.json>    record a named person's decision on a report (a record only)
    verify <audit.jsonl>     check that the audit record has not been altered
    demo                     try everything on a synthetic works
"""
import argparse
import json
import sys
from pathlib import Path
from . import audit, config as cfg, demo, importer, shadow, watch

def parse_assignments(items):
    """'so_ref=1.8 k_do=40' -> {'so_ref': 1.8, 'k_do': 40.0}"""
    out = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep:
            raise cfg.ConfigError(f"'{item}' should look like so_ref=1.8")
        try:
            out[key.strip()] = float(value)
        except ValueError:
            raise cfg.ConfigError(f"'{item}': {value!r} is not a number") from None
    return out

def cmd_init(a):
    folder = Path(a.folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / "site.toml"
    if target.exists():
        raise cfg.ConfigError(f"{target} already exists; edit it or choose another folder")
    target.write_text(demo.TOML.replace("Demo works (synthetic data)", "My works").replace("# Site configuration for the SYNTHETIC demo works.",
                      "# Site configuration. Replace every value with your own. Put your data file next to this one."))
    print(f"Created {target}. Next: put your historian export next to it, edit the file, then run: python -m aera.site check {target}")

def cmd_check(a):
    config = cfg.load(a.config)
    data = importer.load(config, Path(a.config).parent)
    print(importer.quality_markdown(data.report))
    return 0 if data.windows else 1

def cmd_replay(a):
    out = Path(a.out or Path(a.config).parent / "shadow_report")
    report = shadow.run(a.config, out, parse_assignments(a.candidate), [float(x) for x in a.sweep.split(",")] if a.sweep else None,
                        a.days, "full" if a.accurate else "fast", calibrate=True if a.calibrate else None)
    print(f"\nModel check: {report['validation']['status'].replace('_', ' ')}")
    for line in report["validation"]["reasons"]:
        print("  -", line)
    if report["recommendation"]:
        print(f"Recommendation: {report['recommendation']['status'].replace('_', ' ')}. {report['recommendation']['reason']}")
    print(f"\nOpen {out / 'report.html'} in a browser.")

def cmd_watch(a):
    inbox = Path(a.inbox)
    out = Path(a.out) if a.out else Path(a.config).parent / "watch_reports"
    watcher = watch.Watcher(a.config, inbox, out, parse_assignments(a.candidate), [float(x) for x in a.sweep.split(",")] if a.sweep else None, a.days,
                            True if a.calibrate else None, a.settle)
    try:
        watcher.run(a.interval, a.once)
    except KeyboardInterrupt:
        print("\nStopped.")
    print(f"Index of runs: {out / 'index.html'}")

def cmd_approve(a):
    path = Path(a.report)
    trail = Path(a.audit) if a.audit else path.parent / "audit.jsonl"
    try:
        entry = audit.approve(trail, path, a.name, a.note, a.override_reason)
    except ValueError as error:
        raise cfg.ConfigError(str(error)) from None
    print(f"Recorded approval {entry['n']} by {a.name} in {trail}. This changes no plant setting.")
    print(f"Audit record head: {entry['hash'][:12]} (write it down somewhere else to detect a truncated record later)")

def cmd_verify(a):
    ok, message = audit.verify(a.audit, a.head)
    print(("OK: " if ok else "PROBLEM: ") + message)
    return 0 if ok else 1

def cmd_demo(a):
    folder = demo.generate(a.out, mismatch=a.mismatch)
    print(f"Created a SYNTHETIC works in {folder} (not real data).")
    report = shadow.run(folder / "site.toml", folder / "shadow_report", dict(so_ref=1.7), [1.0, 1.5, 2.0, 2.5, 3.0], calibrate=True if a.calibrate else None)
    print(f"\nModel check: {report['validation']['status'].replace('_', ' ')}\nOpen {folder / 'shadow_report' / 'report.html'} in a browser.")

def main(argv=None):
    p = argparse.ArgumentParser(prog="python -m aera.site", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init"); s.add_argument("folder"); s.set_defaults(fn=cmd_init)
    s = sub.add_parser("check"); s.add_argument("config"); s.set_defaults(fn=cmd_check)
    s = sub.add_parser("replay"); s.add_argument("config")
    s.add_argument("--candidate", nargs="*", help="settings to test, for example so_ref=1.8 k_do=40")
    s.add_argument("--sweep", help="comma separated DO setpoints to compare, for example 1.0,1.5,2.0,2.5")
    s.add_argument("--days", type=float, default=28.0, help="longest period to replay (default 28)")
    s.add_argument("--accurate", action="store_true", help="slower, tighter numerical tolerance")
    s.add_argument("--calibrate", action="store_true", help="fit nitrifier activity and oxygen transfer to your data first, and validate on held-out days (needs at least 3 weeks)")
    s.add_argument("--out", help="folder for the report (default: shadow_report next to the configuration)")
    s.set_defaults(fn=cmd_replay)
    s = sub.add_parser("watch"); s.add_argument("config")
    s.add_argument("--inbox", required=True, help="the folder where exports appear; it is only ever read")
    s.add_argument("--out", help="folder for reports (default: watch_reports next to the configuration); must be outside the inbox")
    s.add_argument("--candidate", nargs="*"); s.add_argument("--sweep"); s.add_argument("--days", type=float, default=28.0); s.add_argument("--calibrate", action="store_true")
    s.add_argument("--interval", type=float, default=30.0, help="seconds between looks at the inbox (default 30)")
    s.add_argument("--settle", type=float, default=10.0, help="a file must be untouched for this many seconds before it is used (default 10)")
    s.add_argument("--once", action="store_true", help="look once, process what is there, and stop (for a scheduled job)")
    s.set_defaults(fn=cmd_watch)
    s = sub.add_parser("approve"); s.add_argument("report"); s.add_argument("--name", required=True); s.add_argument("--note", required=True)
    s.add_argument("--audit"); s.add_argument("--override-reason", help="needed to approve a report that is not 'ready for operator review'; recorded in the audit log")
    s.set_defaults(fn=cmd_approve)
    s = sub.add_parser("verify"); s.add_argument("audit"); s.add_argument("--head", help="the head hash you wrote down earlier (detects removed entries)")
    s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("demo"); s.add_argument("--out", default="demo_site"); s.add_argument("--calibrate", action="store_true"); s.add_argument("--mismatch", type=float, default=0.0,
                  help="make the synthetic works differ from the model by this fraction (0 to 0.5)"); s.set_defaults(fn=cmd_demo)
    a = p.parse_args(argv)
    try:
        return a.fn(a) or 0
    except cfg.ConfigError as error:
        print(f"\nProblem: {error}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
