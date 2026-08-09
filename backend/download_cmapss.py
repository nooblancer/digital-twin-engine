"""Download the NASA C-MAPSS Turbofan Engine Degradation Dataset.

Downloads and extracts the dataset files needed for the C-MAPSS replay adapter.
The dataset is publicly available from NASA's Prognostics Data Repository.

Usage:
    python download_cmapss.py

Output:
    data/cmapss/train_FD001.txt
    data/cmapss/train_FD002.txt
    data/cmapss/train_FD003.txt
    data/cmapss/train_FD004.txt
    data/cmapss/test_FD001.txt
    ... (and RUL files)
"""

from __future__ import annotations

import io
import os
import sys
import zipfile
from pathlib import Path
from urllib.request import urlretrieve
from urllib.error import URLError

# NASA Prognostics Data Repository - C-MAPSS dataset
# Mirror on a reliable host (the original NASA link sometimes rotates)
DATASET_URL = "https://ti.arc.nasa.gov/c/6/"
# Fallback: Kaggle-hosted mirror (requires no auth for this dataset)
FALLBACK_URL = "https://data.nasa.gov/download/nk8v-ckry/application%2Fx-zip-compressed"

OUTPUT_DIR = Path("data/cmapss")

EXPECTED_FILES = [
    "train_FD001.txt",
    "train_FD002.txt",
    "train_FD003.txt",
    "train_FD004.txt",
    "test_FD001.txt",
    "test_FD002.txt",
    "test_FD003.txt",
    "test_FD004.txt",
    "RUL_FD001.txt",
    "RUL_FD002.txt",
    "RUL_FD003.txt",
    "RUL_FD004.txt",
]


def download_with_progress(url: str, dest: Path) -> None:
    """Download a file with progress reporting."""
    print(f"  Downloading from: {url}")

    def reporthook(block_num: int, block_size: int, total_size: int) -> None:
        if total_size > 0:
            downloaded = block_num * block_size
            pct = min(100, downloaded * 100 // total_size)
            mb = downloaded / (1024 * 1024)
            total_mb = total_size / (1024 * 1024)
            print(f"\r  Progress: {pct}% ({mb:.1f}/{total_mb:.1f} MB)", end="", flush=True)
        else:
            downloaded = block_num * block_size
            mb = downloaded / (1024 * 1024)
            print(f"\r  Downloaded: {mb:.1f} MB", end="", flush=True)

    urlretrieve(url, str(dest), reporthook)
    print()  # newline after progress


def extract_zip(zip_path: Path, output_dir: Path) -> None:
    """Extract C-MAPSS files from the zip archive."""
    print(f"  Extracting to: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        # The zip may have nested directories; find and extract .txt files
        for info in zf.infolist():
            filename = Path(info.filename).name
            if filename.endswith(".txt") and (
                filename.startswith("train_")
                or filename.startswith("test_")
                or filename.startswith("RUL_")
            ):
                # Extract directly to output_dir with flat structure
                data = zf.read(info.filename)
                dest = output_dir / filename
                dest.write_bytes(data)
                print(f"    ✓ {filename}")


def verify_dataset(output_dir: Path) -> bool:
    """Check that the minimum required files exist."""
    # We only strictly need train_FD001.txt for the default config
    required = ["train_FD001.txt"]
    missing = [f for f in required if not (output_dir / f).exists()]
    return len(missing) == 0


def generate_synthetic_fallback(output_dir: Path) -> None:
    """Generate a small synthetic dataset if download fails.

    This produces a valid train_FD001.txt with realistic-looking sensor data
    so the pipeline can run end-to-end for development/demo purposes.
    """
    import random

    print("  Generating synthetic C-MAPSS data for development...")
    output_dir.mkdir(parents=True, exist_ok=True)

    random.seed(42)
    filepath = output_dir / "train_FD001.txt"

    num_engines = 5
    cycles_per_engine = 200

    with open(filepath, "w") as f:
        for engine_id in range(1, num_engines + 1):
            for cycle in range(1, cycles_per_engine + 1):
                # 3 operational settings
                altitude = random.uniform(0, 42000)
                mach = random.uniform(0.0, 0.84)
                tra = random.uniform(20, 100)

                # 21 sensor values with degradation trend
                degradation = cycle / cycles_per_engine
                sensors = []
                base_values = [
                    518.67, 642.15, 1585.29, 1400.60, 14.62,
                    21.61, 554.36, 2388.02, 9046.19, 1.30,
                    47.47, 521.66, 2388.01, 8138.62, 8.4195,
                    0.03, 392, 2388, 100.0, 39.06, 23.42,
                ]
                for i, base in enumerate(base_values):
                    noise = random.gauss(0, base * 0.005)
                    trend = base * degradation * 0.02 * (1 if i % 2 == 0 else -1)
                    sensors.append(base + noise + trend)

                parts = [
                    str(engine_id),
                    str(cycle),
                    f"{altitude:.4f}",
                    f"{mach:.4f}",
                    f"{tra:.4f}",
                ] + [f"{v:.4f}" for v in sensors]

                f.write(" ".join(parts) + "\n")

    print(f"    ✓ train_FD001.txt (synthetic: {num_engines} engines, {cycles_per_engine} cycles each)")
    print("    Note: This is synthetic data for development. For real analysis,")
    print("    download the actual dataset from NASA's Prognostics Data Repository.")


def main() -> None:
    print("=" * 60)
    print("  C-MAPSS Dataset Download")
    print("  NASA Turbofan Engine Degradation Simulation")
    print("=" * 60)
    print()

    # Check if already downloaded
    if verify_dataset(OUTPUT_DIR):
        print(f"✓ Dataset already exists in {OUTPUT_DIR}")
        print("  To re-download, delete the data/cmapss directory first.")
        return

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = OUTPUT_DIR / "CMAPSSData.zip"

    # Try downloading from NASA
    downloaded = False
    for url in [DATASET_URL, FALLBACK_URL]:
        try:
            print(f"Attempting download...")
            download_with_progress(url, zip_path)
            downloaded = True
            break
        except (URLError, OSError) as e:
            print(f"  Failed: {e}")
            continue

    if downloaded and zip_path.exists():
        try:
            extract_zip(zip_path, OUTPUT_DIR)
            zip_path.unlink()  # Clean up zip
        except zipfile.BadZipFile:
            print("  Error: Downloaded file is not a valid zip archive.")
            zip_path.unlink()
            downloaded = False

    if not verify_dataset(OUTPUT_DIR):
        print()
        print("  Could not download the real dataset (NASA servers may be unavailable).")
        print("  Generating synthetic data instead...")
        print()
        generate_synthetic_fallback(OUTPUT_DIR)

    print()
    if verify_dataset(OUTPUT_DIR):
        print("✓ Dataset ready! You can now run: python run_local.py")
    else:
        print("✗ Failed to set up dataset. Check your internet connection.")
        sys.exit(1)


if __name__ == "__main__":
    main()
