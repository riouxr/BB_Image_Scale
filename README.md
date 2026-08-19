# BB Image Scale

A lightweight drag-and-drop batch image resizer for Linux, built and tested on **Rocky Linux 9**. Drop images or whole folders onto the window and they are resized by percentage or to an exact width and height. No ImageMagick, no cloud, no per-file clicking.

![Python](https://img.shields.io/badge/Python-3.9%2B-blue?style=flat-square&logo=python)
![Platform](https://img.shields.io/badge/Platform-Linux-lightgrey?style=flat-square&logo=linux)
![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)

---

## Features

- **Drag & drop** — files, folders, or a mix of both, as many at once as you like
- **Two ways to resize**
  - **Percent** — 1 % to 400 %, slider plus a typed value and 25 / 50 / 100 / 200 shortcuts
  - **Width x Height** — type exact pixel values, with **512 / 1024 / 2048** presets one click away
- **Keep aspect ratio** (on by default) — the width and height act as a bounding box the image fits inside; switch it off to stretch to the exact numbers
- **Save to subfolder** (on by default) — output lands in `./resized/` next to each source file, so originals are never touched. Rename the folder, or switch it off to overwrite in place
- **Include subfolders** (on by default) — folder drops recurse, and the output folder is skipped so re-runs never resize their own results
- **Don't enlarge** — a guard for batches where some files are already smaller than the target
- **Format preserved** — a PNG stays a PNG, a JPEG stays a JPEG, quality is kept high (JPEG/WebP 95)
- **Animation aware** — animated GIF and WebP keep every frame, their timing, and their loop count
- **Metadata carried over** — EXIF and ICC colour profiles survive the resize
- **Live log** — every file, its old and new size, with success and error counts

Resampling uses **Lanczos**, the best-quality filter Pillow offers for downscaling.

---

## Install on Rocky 9

Tk is not part of the base Python install on Rocky, so pull it in first:

```bash
sudo dnf install -y python3 python3-tkinter
```

Then clone and run:

```bash
git clone https://github.com/riouxr/BB_Image_Scale.git
```

```bash
cd BB_Image_Scale && ./run.sh
```

`run.sh` creates a `.venv` on first launch, installs Pillow and tkinterdnd2 into it, and starts the app. Later launches skip straight to the app.

---

## Add it to the desktop menu

```bash
./install.sh
```

That drops a launcher in `~/.local/bin`, an icon in `~/.local/share/icons`, and a `.desktop` entry in `~/.local/share/applications`. "BB Image Scale" then shows up in the Activities menu, and you can drop files straight onto its icon or use **Open With** from Files.

To remove it again:

```bash
./install.sh --uninstall
```

---

## Build a standalone binary (optional)

```bash
./build_binary.sh
```

Produces `dist/BBImageScale`, a single self-contained executable with Python, Pillow, Tk, and tkdnd bundled in — copy it to any x86-64 Linux box, no Python needed. Running `./install.sh` afterwards picks up the binary automatically instead of the source launcher.

---

## How resizing behaves

| Setting | Result on an 800 x 600 image |
|---|---|
| Percent 50 % | 400 x 300 |
| Percent 200 % | 1600 x 1200 |
| 1024 x 1024, keep aspect | 1024 x 768 — fits inside the box |
| 1024 x 1024, exact | 1024 x 1024 — stretched |
| Width 256, height blank | 256 x 192 — the blank side follows the ratio |
| 2048 x 2048, don't enlarge | 800 x 600 — left alone |

Output paths mirror the input tree. Dropping `photos/` with subfolders on gives you `photos/resized/` and `photos/holiday/resized/`, each next to its own source files.

Writes go to a temporary file that is renamed into place only once the save succeeds, so an unreadable or truncated file can never destroy an original — even when overwriting in place.

---

## Formats

Reads everything Pillow can open (PNG, JPEG, WebP, TIFF, BMP, GIF, TGA, ICO, PPM, and more — the list is built at runtime from Pillow's own registry) and writes each file back in the format it came in.

---

## Running from source without `run.sh`

```bash
pip install --user pillow tkinterdnd2 && python3 bb_image_scale.py
```

Drag and drop needs `tkinterdnd2`. Without it the app still starts and works through the **Files** and **Folder** buttons — it just says so in the log.

You can also hand it paths on the command line; they are queued and resized when you click the drop zone:

```bash
python3 bb_image_scale.py ~/Pictures/*.png
```

---

## Project structure

```
BB_Image_Scale/
├── bb_image_scale.py        # the whole application
├── run.sh                   # venv bootstrap + launch
├── build_binary.sh          # PyInstaller one-file build
├── install.sh               # desktop menu entry (--uninstall to remove)
├── bb-image-scale.desktop   # desktop entry template
├── bb-image-scale.svg       # app icon
├── requirements.txt
└── README.md
```

---

## Requirements

| Requirement | Version |
|---|---|
| Python | 3.9 or newer (Rocky 9 ships 3.9) |
| python3-tkinter | system package |
| Pillow | ≥ 10.0 |
| tkinterdnd2 | ≥ 0.3 (optional, enables drag & drop) |
| PyInstaller | ≥ 6.0 (only to build a binary) |

---

## License

MIT — do whatever you want with it.
