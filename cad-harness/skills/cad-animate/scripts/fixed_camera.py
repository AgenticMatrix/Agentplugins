"""Derive a fixed perspective camera for animating a CAD artifact.

The snapshot viewer auto-frames the camera on the *visible* bounding box every
frame, which makes an animation zoom/pan as parts move, appear, or spread.
This helper computes one fixed ``{position, target, up}`` camera from the full
assembly bounds so every frame renders through the same lens.

Accepts either a ``<name>.step.py`` generator (builds ``gen_step()`` once at the
given parameter value) or a static ``<name>.step`` file (imported via build123d),
and prints the camera as a single JSON object on stdout.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import sys
from pathlib import Path

# Normalized isometric view direction [1, -1, 0.8] (see cad-animate playbook).
_ISO_DIR = (0.6155, -0.6155, 0.4924)


def _load_generator(source: Path):
    spec = importlib.util.spec_from_file_location("cad_fixed_camera_gen", source)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load generator: {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["cad_fixed_camera_gen"] = module
    spec.loader.exec_module(module)
    if not callable(getattr(module, "gen_step", None)):
        raise SystemExit(f"{source} has no callable gen_step()")
    return module


def _bounds(shape) -> tuple[list[float], list[float]]:
    bb = shape.bounding_box()
    mn, mx = bb.min, bb.max
    return ([mn.X, mn.Y, mn.Z], [mx.X, mx.Y, mx.Z])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Derive a fixed animation camera.")
    parser.add_argument("source", type=Path, help="<name>.step.py generator or <name>.step")
    parser.add_argument("--param", default="CRANK_ANGLE_DEG", help="module-level parameter to set before gen_step()")
    parser.add_argument("--value", type=float, default=0.0, help="parameter value for the reference pose")
    parser.add_argument(
        "--distance-scale",
        type=float,
        default=3.5,
        help="camera distance = bbox diagonal/2 * this scale (raise to fit exploded spreads)",
    )
    args = parser.parse_args(argv)

    name = args.source.name
    if name.endswith(".step.py") or name.endswith(".py"):
        module = _load_generator(args.source)
        setattr(module, args.param, args.value)
        shape = module.gen_step()
    else:
        import build123d as bd

        shape = bd.import_step(str(args.source))

    mn, mx = _bounds(shape)
    center = [(mn[i] + mx[i]) / 2.0 for i in range(3)]
    size = [mx[i] - mn[i] for i in range(3)]
    radius = max(math.sqrt(sum(s * s for s in size)) / 2.0, 1.0)
    distance = radius * args.distance_scale
    position = [center[i] + _ISO_DIR[i] * distance for i in range(3)]

    print(json.dumps({"position": position, "target": center, "up": [0.0, 0.0, 1.0]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
