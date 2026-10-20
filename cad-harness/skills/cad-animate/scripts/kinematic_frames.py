"""Sweep a module-level parameter of a gen_step() generator into per-frame STEP files.

Loads ``<name>.step.py`` via importlib, sets its module-level parameter to each
value in turn, calls ``gen_step()``, and exports one STEP per frame into an output
directory. Also emits a matching snapshot ``--job`` array so the frames can be
rendered to PNGs in a single batch.

The parameter must live at *module scope* (e.g. ``CRANK_ANGLE_DEG = 0.0``);
``gen_step()`` stays argument-free, so motion is expressed through that global.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

from cadgen.step_export import export_build123d_step_file


def load_generator(source: Path):
    spec = importlib.util.spec_from_file_location("cad_animate_gen", source)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load generator: {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["cad_animate_gen"] = module
    spec.loader.exec_module(module)
    if not callable(getattr(module, "gen_step", None)):
        raise SystemExit(f"{source} has no callable gen_step()")
    return module


def values_from_args(args) -> list[float]:
    if args.values:
        return [float(v) for v in args.values.split(",") if v.strip() != ""]
    if args.frames < 1:
        raise SystemExit("--frames must be >= 1")
    if args.frames == 1:
        return [args.start]
    return [args.start + (args.end - args.start) * i / (args.frames - 1) for i in range(args.frames)]


def build_render_jobs(frame_names: list[str], camera, display, out_dir: Path) -> dict:
    jobs = []
    for name in frame_names:
        jobs.append({
            "input": str(out_dir / name),
            "mode": "view",
            "display": {"mode": display},
            "outputs": [{"path": str(out_dir / (Path(name).stem + ".png")), "camera": camera}],
        })
    return {"jobs": jobs}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sweep a gen_step() parameter into per-frame STEP files + a render job."
    )
    parser.add_argument("source", type=Path, help="path to <name>.step.py generator")
    parser.add_argument("--param", default="CRANK_ANGLE_DEG", help="module-level parameter to sweep")
    parser.add_argument("--start", type=float, default=0.0, help="first parameter value")
    parser.add_argument("--end", type=float, default=360.0, help="last parameter value")
    parser.add_argument("--frames", type=int, default=24, help="number of frames")
    parser.add_argument("--values", help="comma-separated explicit values (overrides start/end/frames)")
    parser.add_argument("--out", type=Path, default=Path("frames"), help="output dir")
    parser.add_argument("--prefix", default="frame", help="frame filename prefix")
    parser.add_argument("--camera", default="iso", help="snapshot camera for the render job")
    parser.add_argument("--display", default="transparent", help="snapshot display mode")
    parser.add_argument("--no-render-jobs", action="store_true", help="do not emit render_jobs.json")
    args = parser.parse_args(argv)

    module = load_generator(args.source)
    values = values_from_args(args)
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    frame_names: list[str] = []
    for i, value in enumerate(values):
        setattr(module, args.param, float(value))
        shape = module.gen_step()
        name = f"{args.prefix}_{i:03d}.step"
        export_build123d_step_file(shape, out_dir / name)
        frame_names.append(name)
        print(f"wrote {out_dir / name} at {args.param}={value:g}")

    if not args.no_render_jobs:
        jobs = build_render_jobs(frame_names, args.camera, args.display, out_dir)
        job_path = out_dir / "render_jobs.json"
        job_path.write_text(json.dumps(jobs, indent=2))
        print(f"wrote {job_path} ({len(jobs['jobs'])} jobs)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
