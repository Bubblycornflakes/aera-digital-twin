"""Download the IWA BSM1 archive from the official release, verify its SHA256, and extract it under data/.

    python scripts/fetch_bsm1.py

The archive is not redistributed with this repository. Its agreement (Documents/BSM1_agreement_LU.pdf inside
the archive) asks users to acknowledge the Lund University implementation in published work.
"""
import hashlib
import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://github.com/wwtmodels/Benchmark-Simulation-Models/releases/download/BSM1_vR2019b/BSM1_R2019b.zip"
SHA256 = "f0ed19ed214e562317c719f9d0ec93cdb45d4db3feea642c67101afc9f191f06"
ROOT = Path(__file__).resolve().parent.parent / "data"

def main():
    target = ROOT / "bsm1_extracted" / "BSM1_R2019b"
    if (target / "dryinfluent.mat").exists():
        print("already present:", target)
        return 0
    ROOT.mkdir(exist_ok=True)
    archive = ROOT / "BSM1_R2019b.zip"
    print("downloading", URL)
    urllib.request.urlretrieve(URL, archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != SHA256:
        archive.unlink()
        print(f"checksum mismatch: got {digest}, expected {SHA256}", file=sys.stderr)
        return 1
    out = ROOT / "bsm1_extracted"
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():          # refuse path traversal before extracting anything
            if name.startswith("/") or ".." in Path(name).parts:
                print("unsafe path in archive:", name, file=sys.stderr)
                return 1
        z.extractall(out)
    print("verified and extracted to", out)
    return 0

if __name__ == "__main__":
    sys.exit(main())
