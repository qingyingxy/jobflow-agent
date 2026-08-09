from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the deterministic discovery demo GIF.")
    parser.add_argument("--frame", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frames = [Image.open(path).convert("RGB") for path in args.frame]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        args.output,
        save_all=True,
        append_images=frames[1:],
        duration=[1_200, 1_800, 2_600],
        loop=0,
        optimize=True,
    )


if __name__ == "__main__":
    main()
