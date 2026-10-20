# Animation playbook

The two recipes and the gotchas that actually matter. Everything here was learned
by animating a slider-crank engine: a kinematic crank-rotation GIF and a build-up
assembly GIF.

## Pattern 1 — kinematic motion (parameter sweep)

Use when a part actually translates/rotates between frames. The geometry changes,
so each frame is a fresh STEP.

1. The generator must expose a module-level parameter that `gen_step()` reads:

   ```python
   CRANK_ANGLE_DEG = 0.0

   def gen_step():
       crank = _moving_parts(CRANK_ANGLE_DEG)
       asm.add(crank, name="crankshaft", ...)
       return asm.build()
   ```

   `gen_step()` stays argument-free. The `$cad` build entry rejects args and
   variadics, so motion is expressed through module scope, not parameters.

2. Sweep it and export one STEP per frame:

   ```bash
   python scripts/kinematic_frames.py engine.step.py \
     --param CRANK_ANGLE_DEG --start 0 --end 360 --frames 24 \
     --out frames --camera iso --display transparent
   ```

   This writes `frames/frame_000.step` … `frame_023.step` plus
   `frames/render_jobs.json`.

3. Render all frames in one batch (one browser session):

   ```bash
   python $cad/scripts/snapshot --job frames/render_jobs.json
   ```

   Outputs land as `frames/frame_000_<timestamp>.png` — the snapshot CLI appends
   a shared UTC-seconds timestamp before the extension. `make_gif.py` sorts by
   the leading numeric index, so the timestamp suffix is harmless.

4. Stitch:

   ```bash
   python scripts/make_gif.py frames engine_animation.gif --width 640 --duration 90
   ```

### Motion math example (slider-crank)

Given crank radius `r`, rod length `L`, and crank angle θ measured from top-dead
center:

- crank pin: `pin_y = -r·sinθ`, `pin_z = r·cosθ`
- wrist pin height: `z_wrist = pin_z + sqrt(L² - pin_y²)`
- rod tilt: `α = asin(pin_y / L)`

The piston follows `z_wrist`; the rod rotates by `α`. Model the crank, rod, and
piston as parts placed from these values so the whole mechanism moves coherently.

## Pattern 2 — build-up reveal (hide staging)

Use when the final assembly is static and parts should "pop in" one at a time. No
geometry is rebuilt — the same STEP is rendered with a growing set of visible
parts.

1. Get the ordered occurrence refs. `$cad` snapshot `list` mode prints them, or
   `$cad` `inspect refs` lists them. Order matters: first ref appears first.

2. Generate the staged job:

   ```bash
   python scripts/build_buildup.py engine.step \
     --refs "#o1,#o2,#o3,#o4,#o5,#o6,#o7,#o8,#o9,#o10,#o11,#o12,#o13,#o14" \
     --camera '{"position":[147.4,-135.4,154.8],"target":[12.0,0.0,46.5],"up":[0.0,0.0,1.0]}' \
     --display transparent --hold 4 --out buildup
   ```

   Stage `i` hides `refs[i+1:]`, so part 0 is visible alone at stage 0 and the
   full assembly appears at stage `len(refs)-1`. The `--hold` frames repeat the
   full assembly so the GIF pauses on the finished model.

3. Render once, then stitch:

   ```bash
   python $cad/scripts/snapshot --job buildup_jobs.json
   python scripts/make_gif.py buildup buildup_animation.gif
   ```

## Camera — the part that bites

**Auto-framing refits every frame.** With a preset like `iso`, the snapshot
frames the camera on the *visible* bounding box. In a build-up, hiding the
flywheel changed the bbox and zoomed the whole image (a ~45% pixel change in the
middle third just from hiding one part). For kinematic sweeps a moving part does
the same. **Fix the camera** whenever anything appears, disappears, or moves.

Fixed camera = explicit `{position, target, up}` JSON. With an explicit
position/target/up the viewer switches to perspective projection; that is fine.

### Deriving a fixed camera from the assembly bbox

Compute the full assembly bounds (including parts you plan to hide) so the frame
never changes:

- `center = (min + max) / 2`
- `radius = max(size.length() / 2, minModelRadius)` where `size = max - min`
- iso direction (normalized `[1, -1, 0.8]`): `[0.6155, -0.6155, 0.4924]`
- `position = center + direction * distance`

The default auto distance is `radius * 3.2`, but that can be too tight. For the
engine (center `[12, 0, 46.5]`, radius ≈ 102.89) `radius*3.2 ≈ 329` left the model
tiny (429 px wide). Distance 150 and 180 **clipped vertically** (the engine is
taller than wide, so it overflows the frame's Y). Distance 220 fit with no
clipping (Y 55..1121 of 1200). Tune the distance against the actual aspect ratio
— tall models need more distance than `radius*3.2` suggests.

Worked values for the engine: center `[12, 0, 46.5]`, distance 220 →
position `[147.4, -135.4, 154.8]`, up `[0, 0, 1]`.

## Display — internal parts need x-ray

`solid` hides anything inside an enclosing body: the piston, rod, and crank
vanished inside the sealed block, so the solid crank GIF only showed the flywheel
rotating. Switch to `--display transparent` (x-ray) to reveal the mechanism.
`rendered` also shows internals with shading. Verify with a pixel diff: the solid
variant changed only the flywheel region between frames, while `transparent`
changed the full mechanism region.

## Gotchas

- **One browser session per animation.** Pass a single `--job` array to snapshot;
  do not invoke it once per frame. A batch array renders all frames in one
  headless-browser lifecycle.
- **`gen_step()` is argument-free.** Parameterize through module globals, not args.
- **Export per-frame STEP with `export_build123d_step_file`.** An
  `AssemblyHelper` returns a Compound, which has no `.export()` method; use
  `cadgen.step_export.export_build123d_step_file(shape, path)`.
- **Frame budget.** Animated renders accumulate pixels fast; ~120 Mpx total is a
  safe cap for a GIF render pass. Reduce frame count or width if you exceed it.
- **Verify programmatically.** The Read tool cannot display images here, so check
  each frame with PIL/numpy pixel diffs or `snapshot --json` bbox before trusting
  the animation. A stable camera should change only the moving/hidden region
  between frames; a full-frame change means auto-reframing crept back in.
- **Numeric sort.** `frame_10` must sort after `frame_9`; `make_gif.py` sorts by
  the numeric runs in the filename, so zero-padded indices plus timestamp
  suffixes are safe.
