# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the application
python main.py

# Run in debug mode (saves intermediate enhancement pipeline steps)
python main.py --debug
# or
python main.py -d

# Install dependencies
pip install pillow
```

No test suite or linter is configured.

## Architecture

The entire application lives in a single file: `main.py`. It is a Tkinter desktop GUI app with two classes:

- **`Tooltip`** — simple hover tooltip wrapper for any Tkinter widget.
- **`WatermarkApp`** — the full application. Instantiated once in `__main__`.

### Threading model

The app uses two background threads alongside the Tkinter main loop:

1. **Preview caching thread** (`_preview_caching_worker`) — a daemon thread started at startup that continuously pre-loads high-res previews (±9 images around the current index) into `self.cached_previews`. Access to this dict is guarded by `self.preview_cache_lock`.
2. **Processing worker thread** (`_process_worker`) — spawned when the user clicks "PROCESS IMAGES". All UI updates from this thread must go through `self.root.after(0, ...)`.

Incremental thumbnail loading uses `root.after(5, ...)` to load one thumbnail per Tkinter event-loop tick, keeping the UI responsive.

### Key pipelines

**Enhancement pipeline** (`auto_enhance_image`): brightness balancing → contrast boost → gamma adjustment → HSV saturation/value boost → optional Unsharp Mask sharpening. Operates on RGB (alpha is split off and re-applied). In debug mode, each step is saved to disk with suffixes `_01_beta`, `_02_alpha`, `_03_gamma`, `_04_hsv`.

**Watermark pipeline** (`apply_watermark`): scales watermark proportionally to image width, applies opacity via alpha channel manipulation, then pastes using the alpha as mask. Used for both live preview and final export.

**Preview vs. export margin scaling**: The preview scales the pixel margin proportionally (`margin * thumb_w / orig_w`) so watermark placement looks accurate at thumbnail resolution.

### Persistent config

Settings are read/written to `watermark_config.json` in the working directory (i.e., wherever `python main.py` is run from). Loaded on startup in `load_config()`, saved on every relevant UI interaction in `save_config()`.

### Preview debouncing

Slider moves and checkbox toggles call `schedule_preview_update()`, which cancels any pending timer and reschedules `update_preview()` 100 ms later. Window resize uses a separate 200 ms debounce via `_resize_timer`.

### Output structure

Each processing run writes to a timestamped subfolder inside the chosen output directory: `<output_dir>/YYYY-MM-DD HH-MM-SS/`. JPEGs are saved as RGB with `quality=95`; other formats preserve alpha where possible. All images are downscaled to fit within a 3840×3840 bounding box before processing.
