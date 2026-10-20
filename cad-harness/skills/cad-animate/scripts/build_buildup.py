"""Generate a snapshot ``--job`` array for a build-up assembly reveal.

The model is a single static STEP. Each stage renders it with every
not-yet-introduced part hidden via ``selection.hide``, so parts appear one at a
time without rebuilding any geometry. The camera must be fixed so hiding a part
does not make the view auto-reframe (zoom/pan) between stages.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def parse_camera(raw: str):
    text = raw.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"--camera is not valid JSON: {exc}")
    return text


def parse_refs(raw: str) -> list[str]:
    refs = [r.strip() for r in raw.split(",") if r.strip()]
    if not refs:
        raise SystemExit("--refs requires at least one occurrence ref (e.g. #o1,#o2)")
    return refs


def job_for(source: str, camera, display: str, hidden: list[str], out_path: str) -> dict:
    job: dict = {
        "input": source,
        "mode": "view",
        "camera": camera,
        "display": {"mode": display},
        "outputs": [{"path": out_path, "camera": camera}],
    }
    if hidden:
        job["selection"] = {"hide": list(hidden)}
    return job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a hide-staged snapshot job array for a build-up reveal."
    )
    parser.add_argument("source", help="static STEP (or .step.py) to render per stage")
    parser.add_argument("--refs", required=True, help="ordered occurrence refs, e.g. #o1,#o2,#o3")
    parser.add_argument("--camera", required=True, help="fixed camera JSON {position,target,up} (or a preset)")
    parser.add_argument("--display", default="transparent", help="snapshot display mode")
    parser.add_argument("--hold", type=int, default=4, help="hold frames after the last part appears")
    parser.add_argument("--out", type=Path, default=Path("buildup"), help="output dir for PNGs")
    parser.add_argument("--prefix", default="frame", help="frame filename prefix")
    parser.add_argument("--job", type=Path, default=Path("buildup_jobs.json"), help="job JSON output path")
    args = parser.parse_args(argv)

    refs = parse_refs(args.refs)
    camera = parse_camera(args.camera)
    if not isinstance(camera, dict):
        print(
            "WARNING: --camera is a preset, not a fixed camera; the view auto-reframes "
            "each stage as parts are hidden. Pass explicit JSON {position,target,up} for a "
            "stable frame.",
            file=sys.stderr,
        )

    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    jobs: list[dict] = []
    total = len(refs) + args.hold
    for i in range(total):
        visible_up_to = min(i, len(refs) - 1)
        hidden = refs[visible_up_to + 1 :]
        out_path = str(out_dir / f"{args.prefix}_{i:03d}.png")
        jobs.append(job_for(args.source, camera, args.display, hidden, out_path))

    payload = {"jobs": jobs}
    args.job.write_text(json.dumps(payload, indent=2))
    print(f"wrote {args.job} ({len(jobs)} stages: {len(refs)} build + {args.hold} hold)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
