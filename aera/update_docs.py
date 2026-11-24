"""Keep the result tables in the docs identical to results/ (no hand-copied numbers).

    python -m aera.update_docs           # rewrite the generated blocks
    python -m aera.update_docs --check   # exit 1 if any block is out of date (used by the tests)
"""
import re
import sys
from pathlib import Path
from . import leaderboard, sensitivity

ROOT = Path(__file__).resolve().parent.parent
BLOCKS = {"README.md": ["leaderboard-short"], "docs/AEROBENCH.md": ["leaderboard-full", "sensitivity"]}

def render(name):
    rows = leaderboard.build()
    if name == "leaderboard-short":
        return leaderboard.markdown(rows, failures=False)
    if name == "leaderboard-full":
        return leaderboard.markdown(rows)
    if name == "sensitivity":
        return sensitivity.markdown(sensitivity.table())
    raise KeyError(name)

def update(text, name, body):
    pattern = re.compile(rf"(<!-- {name}:start -->\n)(.*?)(\n<!-- {name}:end -->)", re.S)
    if not pattern.search(text):
        raise ValueError(f"marker {name} missing")
    return pattern.sub(lambda m: m.group(1) + body + m.group(3), text)

def main(check=False):
    stale = []
    for path, names in BLOCKS.items():
        file = ROOT / path
        text = file.read_text()
        new = text
        for name in names:
            new = update(new, name, render(name))
        if new != text:
            stale.append(path)
            if not check:
                file.write_text(new)
    return stale

if __name__ == "__main__":
    stale = main(check="--check" in sys.argv)
    print("out of date:" if "--check" in sys.argv else "updated:", stale or "nothing")
    sys.exit(1 if stale and "--check" in sys.argv else 0)
