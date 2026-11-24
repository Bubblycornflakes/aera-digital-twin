"""A tamper-evident record of what was done: every import, replay and approval is appended to a hash-chained log.

Each line holds the hash of the previous line, so editing or deleting an earlier line breaks every later hash and `verify`
reports it. This shows that the record has not been changed; it does not stop someone writing a new log from scratch."""
import getpass
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

GENESIS = "0" * 64

def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def _digest(previous, body):
    return hashlib.sha256((previous + json.dumps(body, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()

def read(path):
    path = Path(path)
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []

def append(path, action, details):
    """Add one entry. details must be JSON serialisable. Returns the entry."""
    path = Path(path)
    entries = read(path)
    previous = entries[-1]["hash"] if entries else GENESIS
    body = dict(n=len(entries) + 1, time=datetime.now(timezone.utc).isoformat(timespec="seconds"), user=getpass.getuser(),
                action=action, details=details)
    entry = dict(body, previous=previous, hash=_digest(previous, body))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")
    return entry

def head(path):
    """The hash of the latest entry. Copy it somewhere outside this folder: it is what lets you detect later that entries were removed."""
    entries = read(path)
    return entries[-1]["hash"] if entries else GENESIS

def verify(path, expected_head=None):
    """Returns (ok, message). Checks the chain from the first entry. If you kept a head hash, pass it (full or the first
    characters) to also detect that entries were cut from the end, which the chain alone cannot show."""
    previous = GENESIS
    entries = read(path)
    for i, e in enumerate(entries, 1):
        body = {k: e[k] for k in ("n", "time", "user", "action", "details")}
        if e.get("previous") != previous or e.get("hash") != _digest(previous, body) or e.get("n") != i:
            return False, f"The record has been changed at entry {i} ({e.get('action', '?')})."
        previous = e["hash"]
    if expected_head is not None and not any(e["hash"].startswith(expected_head) for e in entries):
        return False, "The head hash you kept is not in this record: entries have been removed or the record was replaced."
    if expected_head is not None and not entries[-1]["hash"].startswith(expected_head):
        return True, f"{len(entries)} entries, chain intact. The head you kept is entry {next(i for i, e in enumerate(entries, 1) if e['hash'].startswith(expected_head))}; later entries were added after it."
    return True, f"{len(entries)} entries, chain intact." + ("" if expected_head else " (Without a kept head hash, removal of the last entries cannot be detected.)")

def approve(path, report_path, name, note, override_reason=None):
    """Record a named person's decision on a report. Records the report's hash and recommendation; it does not change any plant setting.
    Refuses a report that is not 'ready for operator review' unless an override reason is given (which is then recorded), and refuses a
    report that no longer matches the one the replay recorded."""
    report_path = Path(report_path)
    report = json.loads(report_path.read_text())
    status = (report.get("recommendation") or {}).get("status", "no recommendation")
    replays = [e for e in read(path) if e["action"] == "replay" and e["details"].get("report") == report_path.name]
    if not replays:
        raise ValueError("The audit record has no replay of this report. Approve the report that the replay wrote, in the same folder.")
    if replays[-1]["details"]["report_sha256"] != file_hash(report_path):
        raise ValueError("This report differs from the one the replay recorded: it has been changed. It cannot be approved.")
    if status != "ready_for_operator_review" and not override_reason:
        raise ValueError(f"The recommendation is '{status}', not 'ready for operator review'. To record an approval anyway, give --override-reason.")
    return append(path, "approval", dict(report=str(report_path), report_sha256=file_hash(report_path), recommendation_status=status, approved_by=name,
                                          note=note, override_reason=override_reason, effect="record only; this tool never changes a plant setting"))
