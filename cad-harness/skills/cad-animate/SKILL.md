---
name: cad-animate
description: Animate CAD assemblies and parts into GIF or PNG sequences — kinematic motion by sweeping a parameterized gen_step() over frame-by-frame STEP exports, or build-up assembly reveals by staging selection.hide over one STEP. Use when a STEP model should turn, cycle, or assemble step-by-step into an animation.
---

# CAD animation (frame sequences and GIFs)

Turn an existing parametric STEP model into a rendered animation. This skill
owns the *motion* layer on top of the `$cad` skill: it assumes a valid
`<name>.step.py` generator already exists and produces per-frame STEP files,
renders them, and stitches the frames into an animated GIF or PNG sequence.

There are two distinct patterns, and they use different mechanisms:

1. **Kinematic motion** — a part genuinely moves. The generator exposes a
   module-level parameter (e.g. `CRANK_ANGLE_DEG`); you sweep it, rebuild the
   assembly per value, and export one STEP per frame.
2. **Build-up reveal** — parts appear one at a time over a *single* static STEP.
   You render the same model repeatedly, hiding the not-yet-introduced parts
   with `selection.hide`, so nothing has to be rebuilt.

Pick the pattern by whether the geometry actually changes between frames. If a
part translates/rotates/scales, it is kinematic. If the final assembly is fixed
and you just want the parts to "pop in", it is a build-up.

## Use this skill when

Use this skill when the user asks to animate a CAD model, "make it turn/move",
show a mechanism cycling through its range of motion, or assemble a model
piece-by-piece into a GIF or PNG sequence. Also use it when the user wants a
turntable, a section sweep, or a parameter sweep rendered as frames.

Do not use this skill to create or modify the geometry itself — that is `$cad`.
This skill consumes a working `gen_step()` generator and adds motion.

## Two entry points

### Kinematic motion (parameter sweep)

1. The generator already declares a module-level parameter (e.g.
   `CRANK_ANGLE_DEG = 0.0`) and a `gen_step()` that reads it. If it does not,
   refactor it in `$cad` first: `gen_step()` must stay argument-free (the
   `$cad` build entry rejects args), so the parameter lives at module scope.
2. Sweep the parameter and export one STEP per frame with
   `scripts/kinematic_frames.py`:

   ```bash
   python scripts/kinematic_frames.py engine.step.py \
     --param CRANK_ANGLE_DEG --start 0 --end 360 --frames 24 \
     --out frames --camera iso --display transparent
   ```

   This writes `frames/frame_000.step` … `frame_023.step` plus a matching
   `frames/render_jobs.json`.
3. Render all frames in one batch (one headless-browser session) with the
   `$cad` snapshot CLI:

   ```bash
   python $cad/scripts/snapshot --job frames/render_jobs.json
   ```

4. Stitch the PNGs into a GIF with `scripts/make_gif.py`.

### Build-up reveal (hide staging)

1. Discover the ordered occurrence refs of the parts (`#o1`, `#o2`, …) with the
   `$cad` snapshot `list` mode, or from `$cad` `inspect refs`.
2. Generate the staged render job with `scripts/build_buildup.py`:

   ```bash
   python scripts/build_buildup.py engine.step \
     --refs "#o1,#o2,#o3,#o4" \
     --camera '{"position":[147.4,-135.4,154.8],"target":[12,0,46.5],"up":[0,0,1]}' \
     --display transparent --hold 4 --out buildup
   ```

3. Render with `python $cad/scripts/snapshot --job buildup/buildup_jobs.json`,
   then `scripts/make_gif.py buildup buildup.gif`.

## Tools and paths

```bash
python scripts/kinematic_frames.py SOURCE ...   # parameter sweep -> per-frame STEP + render jobs
python scripts/build_buildup.py  SOURCE ...     # hide-staged render job JSON
python scripts/make_gif.py        DIR [OUT]     # PNG sequence -> animated GIF
```

Run scripts from the workspace that owns the model; pass cwd-relative paths so
frames and outputs land next to the generator. Use `python scripts/<tool> --help`
for the full current interface; the playbook shows recommended workflows.

The actual rendering is delegated to `$cad`'s snapshot CLI
(`python $cad/scripts/snapshot --job …`). This skill only generates the frames
and jobs; it never launches a viewer or server.

## Non-negotiables

- `gen_step()` stays argument-free. Motion is parameterized through module-level
  state, never through function arguments.
- One browser session per animation: pass a single `--job` array to snapshot so
  all frames render in one headless-browser lifecycle. Do not invoke snapshot
  once per frame.
- Fix the camera for any animation where parts appear or disappear. Auto-framing
  refits the view to the visible bounding box every frame, so hiding or moving a
  part makes the whole image zoom/pan. See `references/playbook.md`.
- Use `transparent` (or `rendered`) display when internal parts must be visible
  through an enclosing body; `solid` hides them.
- Verify each frame programmatically (pixel diffs, `snapshot --json` bbox) before
  trusting a visual. The render tool cannot be "eyeballed" here — review the
  saved PNGs/GIF and the per-frame diffs in the final response.

## Progressive references

- `references/playbook.md` — the full recipe for both patterns: camera math and
  fixed-framing, display choice, frame budget, batch rendering, and the gotchas
  that bit during the engine animation (auto-reframe zoom, vertical clipping,
  solid-vs-transparent, arg-free `gen_step`).

Final responses should include the produced GIF/PNG paths, the frame count and
size, the parameter range or staged order used, and any per-frame diff checks
that actually ran.
