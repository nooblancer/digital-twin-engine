"""Download NASA C-MAPSS Turbofan Engine Degradation Dataset.

Downloads from the GitHub mirror (edwardzjl/CMAPSSData) since NASA's
data portal can be unreliable. The data is public domain.

Usage:
    python download_cmapss.py
"""

import io
import os
import sys
import urllib.request
import zipfile

GITHUB_RAW_BASE = "https://raw.githubusercontent.com/edwardzjl/CMAPSSData/master"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "cmapss")

FILES = [
    "train_FD001.txt",
    "test_FD001.txt",
    "RUL_FD001.txt",
    "train_FD002.txt",
    "test_FD002.txt",
    "RUL_FD002.txt",
    "train_FD003.txt",
    "test_FD003.txt",
    "RUL_FD003.txt",
    "train_FD004.txt",
    "test_FD004.txt",
    "RUL_FD004.txt",
]


def download_file(filename: str) -> bool:
    """Download a single file from the GitHub mirror."""
    url = f"{GITHUB_RAW_BASE}/{filename}"
    dest = os.path.join(DATA_DIR, filename)

    if os.path.exists(dest):
        print(f"  [skip] {filename} (already exists)")
        return True

    try:
        print(f"  [downloading] {filename}...", end=" ", flush=True)
        urllib.request.urlretrieve(url, dest)
        size_kb = os.path.getsize(dest) / 1024
        print(f"OK ({size_kb:.0f} KB)")
        return True
    except Exception as e:
        print(f"FAILED: {e}")
        return False


def main():
    print("=" * 60)
    print("  NASA C-MAPSS Turbofan Engine Degradation Dataset")
    print("  Downloading from GitHub mirror...")
    print("=" * 60)
    print()

    os.makedirs(DATA_DIR, exist_ok=True)

    success = 0
    failed = 0

    for filename in FILES:
        if download_file(filename):
            success += 1
        else:
            failed += 1

    print()
    print(f"  Results: {success} downloaded, {failed} failed")
    print(f"  Location: {DATA_DIR}")

    if failed > 0:
        print()
        print("  Some files failed to download. You can manually download from:")
        print("  https://data.nasa.gov/dataset/cmapss-jet-engine-simulated-data")
        sys.exit(1)
    else:
        print()
        print("  Dataset ready! Run the replay adapter:")
        print("  python -m digital_twin_engine.adapters.cmapss_replay")


if __name__ == "__main__":
    main()
