"""Watch folder: run shadow mode automatically whenever a new historian export appears in a folder.

This is the safe alternative to a live plant connection. It never talks to SCADA or a historian: a person (or the historian's own
scheduled export) drops a CSV into the inbox folder, and this tool reads it.

Guarantees, each covered by a test:
- The inbox is read only. Files there are opened for reading and are never modified, moved, renamed or deleted, and nothing is written there.
- A file is only used once it has stopped changing (it is not half written).
- Each distinct file content is processed once (identified by its SHA-256). A changed file is processed again.
- A run that fails is recorded and never stops the watcher, and is not retried until the file changes.
- Every step is written to a hash-chained log (watch_audit.jsonl), and each run has the normal shadow mode report and audit record.
- It makes no network connections and needs no credentials."""
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
import html as _html
from . import audit, config as cfg, shadow

IGNORED_PREFIXES = (".", "~$")
IGNORED_SUFFIXES = (".tmp", ".part", ".crdownload", ".swp")

def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:                              # read only
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

class Watcher:
    def __init__(self, config_path, inbox, out, candidate=None, sweep=None, max_days=28.0, calibrate=None, settle=10.0,
                 runner=shadow.run, clock=time.time, sleep=time.sleep, log=print):
        self.config_path, self.inbox, self.out = Path(config_path), Path(inbox).resolve(), Path(out).resolve()
        self.candidate, self.sweep, self.max_days, self.calibrate, self.settle = candidate, sweep, max_days, calibrate, settle
        self.runner, self.clock, self.sleep, self.log = runner, clock, sleep, log
        if not self.inbox.is_dir():
            raise cfg.ConfigError(f"The inbox folder {self.inbox} does not exist.")
        if self.out == self.inbox or self.inbox in self.out.parents:
            raise cfg.ConfigError("The reports folder must be outside the inbox folder, so reports are never mistaken for new data.")
        cfg.load(self.config_path)                             # fail now, with a readable message, if the configuration is wrong
        self.out.mkdir(parents=True, exist_ok=True)
        self.state_path, self.trail = self.out / "watch_state.json", self.out / "watch_audit.jsonl"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else dict(processed={})
        self.started = False

    # ---- looking at the inbox (read only) ----
    def candidates(self):
        """CSV files in the inbox that are complete: not hidden or temporary, untouched for `settle` seconds, size and time steady."""
        found = []
        for path in sorted(self.inbox.iterdir()):
            if not path.is_file() or path.suffix.lower() != ".csv" or path.name.startswith(IGNORED_PREFIXES) or path.name.lower().endswith(IGNORED_SUFFIXES):
                continue
            before = path.stat()
            if self.clock() - before.st_mtime < self.settle:
                continue                                       # modified recently: it may still be being written
            self.sleep(0.2)
            after = path.stat()
            if (before.st_size, before.st_mtime) == (after.st_size, after.st_mtime):
                found.append(path)
        return found

    # ---- doing the work ----
    def process(self, path):
        """Run shadow mode on one file. Returns 'done', 'failed' or 'known'."""
        digest = sha256_of(path)
        if digest in self.state["processed"]:
            return "known"
        if not self.started:
            audit.append(self.trail, "watch_started", dict(config_sha256=audit.file_hash(self.config_path), inbox=str(self.inbox), read_only=True))
            self.started = True
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        run_dir = self.out / "runs" / f"{stamp}_{digest[:8]}"
        audit.append(self.trail, "file_seen", dict(file=path.name, sha256=digest, size=path.stat().st_size))
        self.log(f"New export: {path.name} ({digest[:8]}). Running shadow mode...")
        entry = dict(file=path.name, run=str(run_dir.relative_to(self.out)), time=stamp)
        try:
            report = self.runner(self.config_path, run_dir, self.candidate, self.sweep, self.max_days, "fast", self.log, self.calibrate, None, data_file=path)
        except Exception as error:                              # a bad file must never stop the watcher
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "error.txt").write_text(f"{type(error).__name__}: {error}\n")
            entry.update(status="failed", error=str(error)[:500])
            audit.append(self.trail, "run_failed", dict(file=path.name, sha256=digest, error=str(error)[:500]))
            self.log(f"  Failed: {str(error).splitlines()[0] if str(error) else type(error).__name__}")
            outcome = "failed"
        else:
            rec = report.get("recommendation") or {}
            diff = report["appraisal"].get("difference") or {}
            entry.update(status="done", validation=report["validation"]["status"], recommendation=rec.get("status"), energy_pct=diff.get("energy_pct"),
                         window=f"{report['window']['start'][:10]} to {report['window']['end'][:10]}", calibration=(report.get("calibration") or {}).get("status"))
            report_path = run_dir / "report.json"
            audit.append(self.trail, "run_completed", dict(file=path.name, sha256=digest, run=entry["run"], report_sha256=audit.file_hash(report_path),
                                                          validation=entry["validation"], recommendation=entry["recommendation"]))
            (self.out / "latest_report.json").write_text(report_path.read_text())
            (self.out / "latest_report.html").write_text((run_dir / "report.html").read_text())
            self.log(f"  Model check: {entry['validation'].replace('_', ' ')}; recommendation: {(entry['recommendation'] or 'none').replace('_', ' ')}")
            outcome = "done"
        self.state["processed"][digest] = entry
        self.state_path.write_text(json.dumps(self.state, indent=1))
        self.write_index()
        return outcome

    def poll_once(self):
        """One pass over the inbox. Returns the number of files processed (done or failed)."""
        return sum(self.process(p) in ("done", "failed") for p in self.candidates())

    def run(self, interval=30.0, once=False, max_runs=None):
        """Poll until interrupted. once=True does a single pass and returns; max_runs stops after that many files."""
        total = 0
        self.log(f"Watching {self.inbox} (read only). Reports go to {self.out}. Press Ctrl-C to stop.")
        while True:
            total += self.poll_once()
            if once or (max_runs is not None and total >= max_runs):
                return total
            self.sleep(interval)

    # ---- the index page ----
    def write_index(self):
        e = _html.escape
        rows = sorted(self.state["processed"].items(), key=lambda kv: kv[1]["time"], reverse=True)
        head = ("<!doctype html><meta charset='utf-8'><title>Shadow mode watch folder</title><style>body{font:15px/1.5 system-ui,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem}"
                "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd;padding:5px 9px;text-align:left}th{background:#eef3f3}.bad{color:#b5481f}.ok{color:#1b7f5f}</style>"
                "<h1>Shadow mode watch folder</h1><p>Advice only. Each row is one export file that was run through shadow mode. The inbox is read only: "
                "this tool never changes or moves your files.</p><table><tr><th>Time (UTC)</th><th>File</th><th>Model check</th><th>Recommendation</th><th>Report</th></tr>")
        body = []
        for digest, r in rows:
            if r["status"] == "failed":
                body.append(f"<tr><td>{e(r['time'])}</td><td>{e(r['file'])}</td><td class='bad' colspan='2'>failed: {e(r.get('error', ''))}</td><td><a href='{e(r['run'])}/error.txt'>error</a></td></tr>")
            else:
                ok = "ok" if r["validation"] == "validated" else "bad"
                body.append(f"<tr><td>{e(r['time'])}</td><td>{e(r['file'])}</td><td class='{ok}'>{e(r['validation'].replace('_', ' '))}</td>"
                            f"<td>{e((r.get('recommendation') or 'none').replace('_', ' '))}</td><td><a href='{e(r['run'])}/report.html'>report</a></td></tr>")
        (self.out / "index.html").write_text(head + "".join(body) + "</table>")
