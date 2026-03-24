# Batch Watermark Pro

Desktop application for bulk image watermarking with optional per-image enhancement, live preview, and fast batch processing.

Built with:
- Python
- Tkinter (GUI)
- Pillow (image processing)

## What This App Does

Batch Watermark Pro lets you:
- Load many images from a folder or file picker
- Select a logo/watermark image
- Tune watermark size, opacity, margin, and position
- Preview results live before export
- Optionally apply enhancement per selected image
- Process all images into a timestamped output folder

## Key Features

- Incremental thumbnail loading to keep UI responsive
- Background preview caching for faster image switching
- Per-image enhancement toggle from thumbnail gallery
- Optional advanced sharpening (Unsharp Mask)
- Auto enhancement pipeline (brightness, contrast, gamma, HSV)
- Keyboard navigation:
	- Left/Right arrows: switch image
	- Space: toggle enhancement for current image
- Safe stop button during processing
- Persistent settings in `watermark_config.json`
- Optional debug mode to save enhancement pipeline steps

## Requirements

- Python 3.9+
- Pillow

Tkinter is usually included with standard Python installs.

## Installation

1. Create and activate a virtual environment (recommended).
2. Install dependencies:

```bash
pip install pillow
```

## Run

Normal mode:

```bash
python main.py
```

Debug mode (saves intermediate enhancement steps):

```bash
python main.py --debug
# or
python main.py -d
```

## UI Workflow

1. Select input images
2. Select watermark image
3. Select output folder
4. Adjust settings and optional enhancements
5. Click PROCESS IMAGES

During processing, output files are written into a subfolder inside your chosen output directory, named with the current timestamp:

`YYYY-MM-DD HH-MM-SS`

## Supported Formats

Input images:
- `.jpg`
- `.jpeg`
- `.png`
- `.bmp`
- `.webp`
- `.tiff`

Watermark selector allows PNG and common image formats.

## Processing Behavior

- EXIF orientation is normalized before preview/export.
- Each output image is downscaled to fit inside a max `3840x3840` box.
- JPEG outputs are saved as RGB with `quality=95`.
- Non-JPEG outputs keep alpha when possible.

## Enhancement Pipeline

When enhancement is enabled for an image, the app applies:
1. Brightness balancing (based on luminance statistics)
2. Contrast increase for low-contrast images
3. Gamma adjustment
4. HSV saturation/value boost
5. Optional advanced sharpen filter

In debug mode, intermediate enhancement steps are saved in the same run output folder with suffixes like:
- `_01_beta`
- `_02_alpha`
- `_03_gamma`
- `_04_hsv`

## Configuration File

The app automatically reads/writes `watermark_config.json` in the project root.

Saved values include:
- `watermark_path`
- `output_dir`
- `scale`
- `opacity`
- `margin`
- `position`
- `use_sharpen`

## Notes

- Watermark is optional only if at least one image has enhancement enabled.
- If neither watermark nor enhancement is selected, processing is blocked.
- Stopping processing ends the current run early and keeps already generated files.
