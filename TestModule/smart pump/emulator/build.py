#!/usr/bin/env python3
"""Build on the target Raspberry Pi; no Python packages required."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
REVISION = "7a53f0a72a92de1621d30fc63703a29afe12bfaf"
TAG = "bacnet-stack-1.6.1"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-bip", action="store_true", help="developer BACnet/IP build; not the Pi MS/TP build")
    parser.add_argument("--jobs", type=int, default=min(os.cpu_count() or 1, 4))
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    if not shutil.which("cmake"):
        parser.error("Install build tools: sudo apt install build-essential cmake git")
    vendor = ROOT / "vendor" / "bacnet-stack"
    if not (vendor / "CMakeLists.txt").exists():
        subprocess.run(["git", "clone", "--depth", "1", "--branch", TAG,
                        "https://github.com/bacnet-stack/bacnet-stack.git", str(vendor)], check=True)
    if (vendor / ".git").exists():
        revision = subprocess.check_output(["git", "-C", str(vendor), "rev-parse", "HEAD"], text=True).strip()
        if revision != REVISION:
            parser.error(f"Expected BACnet stack {REVISION}, found {revision}")
    build = ROOT / ("build-test" if args.test_bip else "build")
    subprocess.run(["cmake", "-S", str(ROOT), "-B", str(build),
                    "-DPUMP_TEST_BIP=" + ("ON" if args.test_bip else "OFF"),
                    "-DCMAKE_BUILD_TYPE=Release"], check=True)
    subprocess.run(["cmake", "--build", str(build), "--parallel", str(args.jobs)], check=True)
    subprocess.run(["ctest", "--test-dir", str(build), "--output-on-failure"], check=True)
    print(f"Built {build / 'pump_emulator'}")
    if not args.test_bip and sys.platform == "linux":
        print(f"Built adapter-group binaries: {build / 'mstp_bus'} and {build / 'pump_worker'}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, subprocess.CalledProcessError) as exc:
        sys.exit(f"Build failed: {exc}")
