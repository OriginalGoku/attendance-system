#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import shutil
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cycle fixture lease files into an output file.")
    parser.add_argument("--output", required=True, help="Path to the lease file to update.")
    parser.add_argument(
        "--fixtures-dir",
        default="fixtures",
        help="Directory containing sample lease fixtures.",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Seconds to wait between updates.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Loop forever instead of running one pass.",
    )
    return parser.parse_args()


def fixture_sequence(fixtures_dir: Path) -> list[Path]:
    return [
        fixtures_dir / "sample_leases_empty.txt",
        fixtures_dir / "sample_leases_one_device.txt",
        fixtures_dir / "sample_leases_multiple_devices.txt",
        fixtures_dir / "sample_leases_one_device.txt",
        fixtures_dir / "sample_leases_empty.txt",
    ]


def main() -> None:
    args = parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fixtures = fixture_sequence(Path(args.fixtures_dir))

    iterator = itertools.cycle(fixtures) if args.loop else iter(fixtures)
    for fixture in iterator:
        shutil.copyfile(fixture, output_path)
        print(f"wrote {fixture} -> {output_path}")
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
