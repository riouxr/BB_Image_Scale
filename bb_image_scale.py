#!/usr/bin/env python3
"""BB Image Scale — drag-and-drop batch image resizer for Linux (Rocky 9)."""

from __future__ import annotations

import os
import queue
import sys
import threading
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname
from tkinter import *
from tkinter import font as tkfont
from tkinter import filedialog
from PIL import Image, ImageSequence

# Drag & drop is optional — without tkinterdnd2 the app still works through the
# Files / Folder buttons and command-line arguments.
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_OK = True
except Exception:                                    # pragma: no cover
    DND_OK = False
    DND_FILES = None

    class TkinterDnD:                                # type: ignore[no-redef]
        Tk = Tk

# All extensions Pillow can read (.png, .jpg, .webp, .tga, .tif, …)
SUPPORTED_EXTS: frozenset = frozenset(Image.registered_extensions().keys())

# Note: PIL is imported after "from tkinter import *" on purpose — tkinter
# exports an Image class of its own and we want Pillow's.
RESAMPLE = Image.LANCZOS      # best quality Pillow offers for downscaling

DEFAULT_SUBFOLDER = "resized"
PRESETS = (512, 1024, 2048)
PERCENT_MIN, PERCENT_MAX = 1, 400


# ── sizing ─────────────────────────────────────────────────────────────────────

def target_size(w: int, h: int, *,
                mode: str,
                percent: int,
                tw: int | None,
                th: int | None,
                keep_aspect: bool,
                no_enlarge: bool) -> tuple[int, int]:
    """Compute the output size for a source image of w x h pixels."""
    if mode == "percent":
        scale = percent / 100.0
        if no_enlarge:
            scale = min(scale, 1.0)
        return max(1, round(w * scale)), max(1, round(h * scale))

    # pixel mode — a blank field means "derive from the other one"
    if tw is None and th is None:
        return w, h

    if keep_aspect:
        if tw is None:
            scale = th / h
        elif th is None:
            scale = tw / w
        else:
            scale = min(tw / w, th / h)     # fit inside the box
        if no_enlarge:
            scale = min(scale, 1.0)
        return max(1, round(w * scale)), max(1, round(h * scale))

    nw = tw if tw else w
    nh = th if th else h
    if no_enlarge:
        nw, nh = min(nw, w), min(nh, h)
    return max(1, nw), max(1, nh)


# ── file collection ────────────────────────────────────────────────────────────

def collect_files(paths: list[Path], recursive: bool, skip_dir: str = "") -> list[Path]:
    """Expand a mixed list of files and folders into supported image files.

    Output folders found *inside* a dropped folder are skipped so a second run
    never resizes its own results — but a folder the user drops on purpose is
    always processed, even if it happens to be called `resized`.
    """
    result: list[Path] = []
    seen: set[Path] = set()

    def add(f: Path):
        if f not in seen:
            seen.add(f)
            result.append(f)

    def is_image(f: Path) -> bool:
        return f.is_file() and f.suffix.lower() in SUPPORTED_EXTS

    for p in paths:
        if p.is_dir():
            for f in sorted(p.glob("**/*" if recursive else "*")):
                if not is_image(f):
                    continue
                if skip_dir and skip_dir in f.relative_to(p).parts:
                    continue
                add(f)
        elif is_image(p):
            add(p)
    return result


def _tokenize_drop(data: str) -> list[str]:
    """Split a tkdnd payload: paths with spaces come wrapped in braces, and
    file managers may hand over a newline-separated uri-list instead."""
    tokens: list[str] = []
    raw = data.strip()
    i = 0
    while i < len(raw):
        if raw[i] in " \t\r\n":
            i += 1
        elif raw[i] == "{":
            end = raw.find("}", i)
            if end == -1:
                tokens.append(raw[i + 1:])
                break
            tokens.append(raw[i + 1:end])
            i = end + 1
        else:
            end = i
            while end < len(raw) and raw[end] not in " \t\r\n":
                end += 1
            tokens.append(raw[i:end])
            i = end
    return [t for t in tokens if t]


def to_path(token: str) -> Path:
    """GNOME Files and friends drop percent-encoded file:// URIs."""
    token = token.strip()
    if token.startswith("file:"):
        token = url2pathname(urlparse(token).path)
    return Path(token)


def parse_dropped(data: str) -> list[Path]:
    """Turn a drop payload into the folders and images it points at."""
    paths = [to_path(t) for t in _tokenize_drop(data)]
    return [p for p in paths if p.is_dir() or p.suffix.lower() in SUPPORTED_EXTS]


# ── resizing ───────────────────────────────────────────────────────────────────

def _save_kwargs(fmt: str, info: dict) -> dict:
    """Quality settings plus any colour/EXIF metadata worth carrying over."""
    kwargs: dict = {}
    if fmt == "JPEG":
        kwargs.update(quality=95, optimize=True)
    elif fmt == "WEBP":
        kwargs.update(quality=95)
    elif fmt == "PNG":
        kwargs.update(compress_level=6)

    if info.get("icc_profile"):
        kwargs["icc_profile"] = info["icc_profile"]
    if info.get("exif") and fmt in ("JPEG", "WEBP", "TIFF", "PNG"):
        kwargs["exif"] = info["exif"]
    return kwargs


def _resize_frame(frame: Image.Image, size: tuple[int, int], fmt: str) -> Image.Image:
    """Resize one frame, converting palette images so LANCZOS actually applies."""
    if frame.mode == "P":
        frame = frame.convert("RGBA" if "transparency" in frame.info else "RGB")
    elif frame.mode in ("1", "I;16", "CMYK") and fmt in ("JPEG", "WEBP"):
        frame = frame.convert("RGB")
    out = frame.resize(size, RESAMPLE)
    if fmt == "JPEG" and out.mode in ("RGBA", "LA", "PA"):
        bg = Image.new("RGB", out.size, (255, 255, 255))
        bg.paste(out, mask=out.split()[-1])
        out = bg
    return out


def resize_file(src: Path, dst: Path, size: tuple[int, int],
                fmt: str, info: dict, frames: int) -> None:
    """Write the resized image, going through a temp file so a failure never
    truncates the original when saving in place."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".bbtmp")
    kwargs = _save_kwargs(fmt, info)

    try:
        with Image.open(src) as img:
            if frames > 1:
                seq, durations = [], []
                for frame in ImageSequence.Iterator(img):
                    # per-frame timing: WebP keeps it on the frame, not the file
                    durations.append(frame.info.get("duration")
                                     or info.get("duration") or 100)
                    seq.append(_resize_frame(frame.copy(), size, fmt))
                if fmt == "GIF":
                    seq = [f.convert("P", palette=Image.ADAPTIVE) for f in seq]
                seq[0].save(tmp, fmt, save_all=True, append_images=seq[1:],
                            duration=durations,
                            loop=info.get("loop", 0), **kwargs)
            else:
                _resize_frame(img, size, fmt).save(tmp, fmt, **kwargs)
        os.replace(tmp, dst)
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


def process_file(src: Path, opts: dict) -> tuple[bool, str]:
    """Resize one image. Returns (success, log line)."""
    try:
        with Image.open(src) as img:
            w, h = img.size
            fmt = img.format or "PNG"
            info = dict(img.info)
            frames = getattr(img, "n_frames", 1)

        size = target_size(w, h,
                           mode=opts["mode"],
                           percent=opts["percent"],
                           tw=opts["width"],
                           th=opts["height"],
                           keep_aspect=opts["keep_aspect"],
                           no_enlarge=opts["no_enlarge"])

        if opts["subfolder"]:
            dst = src.parent / opts["subfolder"] / src.name
        else:
            dst = src

        if size == (w, h) and dst == src:
            return False, f"–  {src.name}  —  already {w}x{h}, skipped"

        resize_file(src, dst, size, fmt, info, frames)

        where = f"{opts['subfolder']}/" if opts["subfolder"] else "in place"
        anim = f"  [{frames} frames]" if frames > 1 else ""
        return True, f"✓  {src.name}  {w}x{h} → {size[0]}x{size[1]}  ({where}){anim}"
    except Exception as e:
        return False, f"✗  {src.name}  —  {e}"


# ── UI ─────────────────────────────────────────────────────────────────────────

class App(TkinterDnD.Tk):
    DARK   = "#0f0f17"
    PANEL  = "#17172a"
    CARD   = "#1e1e35"
    ACCENT = "#7c3aed"
    GREEN  = "#4ade80"
    RED    = "#f87171"
    YELLOW = "#fbbf24"
    TEXT   = "#f1f5f9"
    MUTED  = "#64748b"
    BORDER = "#2d2d4e"
    HOVER  = "#252545"

    # Linux boxes rarely have Segoe UI / Cascadia Code — probe for what's there
    UI_CANDIDATES   = ("Cantarell", "Noto Sans", "DejaVu Sans",
                       "Liberation Sans", "Ubuntu", "Segoe UI")
    MONO_CANDIDATES = ("JetBrains Mono", "Fira Mono", "DejaVu Sans Mono",
                       "Liberation Mono", "Noto Sans Mono", "Monospace")

    def __init__(self, initial: list[Path] | None = None):
        super().__init__()
        self.title("BB Image Scale")
        self.geometry("660x780")
        self.minsize(560, 620)
        self.configure(bg=self.DARK)

        self._ui_family   = self._pick_font(self.UI_CANDIDATES, "TkDefaultFont")
        self._mono_family = self._pick_font(self.MONO_CANDIDATES, "TkFixedFont")

        # ── scaling state ───────────────────────────────────────────────────
        self._mode        = StringVar(value="percent")   # "percent" | "pixels"
        self._percent     = IntVar(value=50)
        self._percent_txt = StringVar(value="50")
        self._width       = StringVar(value="1024")
        self._height      = StringVar(value="1024")
        self._keep_aspect = BooleanVar(value=True)
        self._no_enlarge  = BooleanVar(value=False)

        # ── options ─────────────────────────────────────────────────────────
        self._recursive     = BooleanVar(value=True)
        self._use_subfolder = BooleanVar(value=True)
        self._subfolder     = StringVar(value=DEFAULT_SUBFOLDER)

        self._syncing = False
        self._pending: list[Path] = list(initial or [])
        self._busy = False
        self._queue: queue.Queue = queue.Queue()

        self.update_idletasks()
        x = (self.winfo_screenwidth()  - 660) // 2
        y = (self.winfo_screenheight() - 780) // 2
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

        self._build_ui()

        # one-time bindings — the mode panels are rebuilt on every switch, so
        # traces must not live inside their builders
        self._percent.trace_add("write", self._sync_from_slider)
        self._percent_txt.trace_add("write", self._sync_from_entry)
        for var in (self._width, self._height, self._subfolder):
            var.trace_add("write", self._refresh_drop_text)

        if self._pending:
            self._log(f"{len(self._pending)} path(s) from the command line — "
                      f"click the drop zone to resize them.", "head")
            self._refresh_drop_text()

    def _f(self, size: int, weight: str = "normal") -> tuple:
        return (self._ui_family, size, weight)

    def _pick_font(self, candidates: tuple, fallback: str) -> str:
        available = {f.lower() for f in tkfont.families(self)}
        for name in candidates:
            if name.lower() in available:
                return name
        return tkfont.nametofont(fallback).actual("family")

    # ── layout ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        pad = dict(padx=22)

        # ── header ──────────────────────────────────────────────────────────
        hdr = Frame(self, bg=self.PANEL, height=62)
        hdr.pack(fill=X)
        hdr.pack_propagate(False)

        hdr_left = Frame(hdr, bg=self.PANEL)
        hdr_left.pack(side=LEFT, padx=20, fill=Y)

        dot = Canvas(hdr_left, width=10, height=10, bg=self.PANEL,
                     highlightthickness=0)
        dot.pack(side=LEFT, padx=(0, 9))
        dot.create_oval(0, 0, 10, 10, fill=self.ACCENT, outline="")

        Label(hdr_left, text="BB Image Scale", bg=self.PANEL, fg=self.TEXT,
              font=self._f(14, "bold")).pack(side=LEFT)

        # ── mode bar ────────────────────────────────────────────────────────
        mode_bar = Frame(self, bg=self.PANEL)
        mode_bar.pack(fill=X)

        Label(mode_bar, text="Resize by", bg=self.PANEL, fg=self.MUTED,
              font=self._f(8)).pack(side=LEFT, padx=(22, 10), pady=(0, 8))

        pill = Frame(mode_bar, bg=self.BORDER, padx=2, pady=2)
        pill.pack(side=LEFT, pady=(0, 8))

        self._mode_btns: dict = {}
        for value, label in (("percent", "Percent"), ("pixels", "Width x Height")):
            btn = Label(pill, text=f"  {label}  ", font=self._f(9, "bold"),
                        pady=4, cursor="hand2")
            btn.pack(side=LEFT)
            btn.bind("<Button-1>", lambda _, v=value: self._set_mode(v))
            self._mode_btns[value] = btn

        # ── mode settings (rebuilt on mode change) ──────────────────────────
        self._settings = Frame(self, bg=self.PANEL, padx=22)
        self._settings.pack(fill=X)

        Frame(self, bg=self.ACCENT, height=2).pack(fill=X)

        # ── options ─────────────────────────────────────────────────────────
        opts = Frame(self, bg=self.DARK)
        opts.pack(fill=X, **pad, pady=(12, 0))

        Checkbutton(opts, text="Include subfolders", variable=self._recursive,
                    **self._cb_kw(self.DARK)).pack(side=LEFT)
        Checkbutton(opts, text="Don't enlarge", variable=self._no_enlarge,
                    **self._cb_kw(self.DARK)).pack(side=LEFT, padx=(20, 0))

        out = Frame(self, bg=self.DARK)
        out.pack(fill=X, **pad, pady=(4, 0))

        Checkbutton(out, text="Save to subfolder", variable=self._use_subfolder,
                    command=self._refresh_drop_text,
                    **self._cb_kw(self.DARK)).pack(side=LEFT)

        self._sub_entry = self._entry(out, self._subfolder, width=14, bg=self.CARD)
        self._sub_entry.pack(side=LEFT, padx=(6, 0))

        # ── drop zone ───────────────────────────────────────────────────────
        dz_wrap = Frame(self, bg=self.DARK)
        dz_wrap.pack(fill=X, **pad, pady=(12, 0))

        self.drop_zone = Frame(dz_wrap, bg=self.CARD,
                               highlightbackground=self.BORDER,
                               highlightthickness=2)
        self.drop_zone.pack(fill=X)

        inner = Frame(self.drop_zone, bg=self.CARD)
        inner.pack(fill=X, padx=4, pady=4)

        self._arrow = Label(inner, text="⬇", font=(self._ui_family, 32),
                            bg=self.CARD, fg=self.ACCENT)
        self._arrow.pack(pady=(18, 4))

        self._drop_title = Label(
            inner,
            text="Drop images or folders here" if DND_OK else "Click to choose images",
            font=self._f(12, "bold"), bg=self.CARD, fg=self.TEXT)
        self._drop_title.pack()

        self._drop_sub = Label(inner, text="", font=self._f(8),
                               bg=self.CARD, fg=self.MUTED)
        self._drop_sub.pack(pady=(3, 18))

        for w in (self.drop_zone, inner, self._arrow,
                  self._drop_title, self._drop_sub):
            w.configure(cursor="hand2")
            w.bind("<Button-1>", self._on_click_zone)
            if DND_OK:
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>",      self._on_drop)
                w.dnd_bind("<<DragEnter>>", self._on_enter)
                w.dnd_bind("<<DragLeave>>", self._on_leave)

        # ── stats row ───────────────────────────────────────────────────────
        stats = Frame(self, bg=self.DARK)
        stats.pack(fill=X, **pad, pady=(12, 0))

        self._lbl_ok = Label(stats, text="✓  0 resized", bg=self.DARK,
                             fg=self.GREEN, font=self._f(9, "bold"))
        self._lbl_ok.pack(side=LEFT)

        self._lbl_err = Label(stats, text="✗  0 errors", bg=self.DARK,
                              fg=self.RED, font=self._f(9, "bold"))
        self._lbl_err.pack(side=LEFT, padx=16)

        self._link(stats, "Clear", self._clear_log).pack(side=RIGHT)
        self._link(stats, "Folder", self._browse_folder).pack(side=RIGHT, padx=16)
        self._link(stats, "Files", self._browse_files).pack(side=RIGHT)

        # ── log ─────────────────────────────────────────────────────────────
        log_wrap = Frame(self, bg=self.DARK)
        log_wrap.pack(fill=BOTH, expand=True, **pad, pady=(6, 18))

        log_border = Frame(log_wrap, bg=self.BORDER, padx=1, pady=1)
        log_border.pack(fill=BOTH, expand=True)

        log_inner = Frame(log_border, bg=self.CARD)
        log_inner.pack(fill=BOTH, expand=True)

        self._log_text = Text(log_inner, bg=self.CARD, fg=self.TEXT,
                              font=(self._mono_family, 9), relief=FLAT, bd=0,
                              padx=12, pady=10, state=DISABLED, wrap=NONE,
                              selectbackground=self.ACCENT,
                              insertbackground=self.TEXT)
        sb = Scrollbar(log_inner, command=self._log_text.yview,
                       bg=self.CARD, troughcolor=self.CARD,
                       activebackground=self.BORDER, relief=FLAT)
        self._log_text.configure(yscrollcommand=sb.set)
        self._log_text.pack(side=LEFT, fill=BOTH, expand=True)
        sb.pack(side=RIGHT, fill=Y)

        for tag, colour in (("ok", self.GREEN), ("err", self.RED),
                            ("info", self.MUTED), ("head", self.YELLOW)):
            self._log_text.tag_config(tag, foreground=colour)

        self._ok_count = self._err_count = 0
        self._set_mode("percent")
        if not DND_OK:
            self._log("tkinterdnd2 not installed — drag & drop is off, "
                      "use the Files / Folder buttons instead.", "err")
        self._log("Ready — drop images or folders above.", "info")
        self._pump()

    # ── small widget helpers ────────────────────────────────────────────────

    def _cb_kw(self, bg: str) -> dict:
        return dict(bg=bg, fg=self.MUTED, activebackground=bg,
                    activeforeground=self.TEXT, selectcolor=self.CARD,
                    font=self._f(9), bd=0, highlightthickness=0, cursor="hand2")

    def _entry(self, parent, var: StringVar, width: int, bg: str) -> Entry:
        return Entry(parent, textvariable=var, width=width, bg=bg, fg=self.TEXT,
                     font=self._f(9), relief=FLAT, bd=0,
                     insertbackground=self.TEXT, justify=CENTER,
                     highlightthickness=1, highlightbackground=self.BORDER,
                     highlightcolor=self.ACCENT)

    def _link(self, parent, text: str, cmd) -> Label:
        lbl = Label(parent, text=text, bg=self.DARK, fg=self.MUTED,
                    font=self._f(9), cursor="hand2")
        lbl.bind("<Button-1>", lambda _: cmd())
        lbl.bind("<Enter>", lambda _: lbl.configure(fg=self.TEXT))
        lbl.bind("<Leave>", lambda _: lbl.configure(fg=self.MUTED))
        return lbl

    def _quick(self, parent, text: str, cmd) -> Label:
        btn = Label(parent, text=f"  {text}  ", bg=self.CARD, fg=self.MUTED,
                    font=self._f(9, "bold"), pady=3, cursor="hand2")
        btn.bind("<Button-1>", lambda _: cmd())
        btn.bind("<Enter>", lambda _: btn.configure(bg=self.HOVER, fg=self.TEXT))
        btn.bind("<Leave>", lambda _: btn.configure(bg=self.CARD, fg=self.MUTED))
        return btn

    # ── mode switching ──────────────────────────────────────────────────────

    def _set_mode(self, mode: str):
        self._mode.set(mode)
        for value, btn in self._mode_btns.items():
            active = value == mode
            btn.configure(bg=self.ACCENT if active else self.CARD,
                          fg=self.TEXT if active else self.MUTED)

        for w in self._settings.winfo_children():
            w.destroy()
        builder = self._build_percent if mode == "percent" else self._build_pixels
        builder(self._settings)
        self._refresh_drop_text()

    def _build_percent(self, parent):
        row = Frame(parent, bg=self.PANEL)
        row.pack(fill=X, pady=8)

        Label(row, text="Scale", bg=self.PANEL, fg=self.MUTED,
              font=self._f(8)).pack(side=LEFT, padx=(0, 8))

        Scale(row, variable=self._percent, from_=PERCENT_MIN, to=PERCENT_MAX,
              orient=HORIZONTAL, length=220, sliderlength=14, showvalue=False,
              bg=self.PANEL, troughcolor=self.BORDER,
              activebackground=self.ACCENT, highlightthickness=0, bd=0,
              relief=FLAT).pack(side=LEFT)

        self._entry(row, self._percent_txt, width=5,
                    bg=self.CARD).pack(side=LEFT, padx=(8, 4))
        Label(row, text="%", bg=self.PANEL, fg=self.TEXT,
              font=self._f(9, "bold")).pack(side=LEFT)

        for value in (25, 50, 100, 200):
            self._quick(row, f"{value}%",
                        lambda v=value: self._percent.set(v)).pack(side=LEFT,
                                                                   padx=(8, 0))
        self._sync_from_slider()

    def _build_pixels(self, parent):
        row = Frame(parent, bg=self.PANEL)
        row.pack(fill=X, pady=(8, 4))

        Label(row, text="Width", bg=self.PANEL, fg=self.MUTED,
              font=self._f(8)).pack(side=LEFT, padx=(0, 6))
        self._entry(row, self._width, width=6, bg=self.CARD).pack(side=LEFT)

        Label(row, text="x", bg=self.PANEL, fg=self.MUTED,
              font=self._f(9)).pack(side=LEFT, padx=6)

        Label(row, text="Height", bg=self.PANEL, fg=self.MUTED,
              font=self._f(8)).pack(side=LEFT, padx=(0, 6))
        self._entry(row, self._height, width=6, bg=self.CARD).pack(side=LEFT)

        Checkbutton(row, text="Keep aspect ratio", variable=self._keep_aspect,
                    command=self._refresh_drop_text,
                    **self._cb_kw(self.PANEL)).pack(side=LEFT, padx=(16, 0))

        preset_row = Frame(parent, bg=self.PANEL)
        preset_row.pack(fill=X, pady=(0, 8))

        Label(preset_row, text="Presets", bg=self.PANEL, fg=self.MUTED,
              font=self._f(8)).pack(side=LEFT, padx=(0, 8))
        for size in PRESETS:
            self._quick(preset_row, f"{size} x {size}",
                        lambda s=size: self._set_preset(s)).pack(side=LEFT,
                                                                 padx=(0, 8))

    def _set_preset(self, size: int):
        self._width.set(str(size))
        self._height.set(str(size))

    def _sync_from_slider(self, *_):
        if self._syncing:
            return
        self._syncing = True
        self._percent_txt.set(str(self._percent.get()))
        self._syncing = False
        self._refresh_drop_text()

    def _sync_from_entry(self, *_):
        if self._syncing:
            return
        text = self._percent_txt.get().strip().rstrip("%")
        if text.isdigit() and PERCENT_MIN <= int(text) <= PERCENT_MAX:
            self._syncing = True
            self._percent.set(int(text))
            self._syncing = False
        self._refresh_drop_text()

    # ── state read-out ──────────────────────────────────────────────────────

    @staticmethod
    def _as_int(text: str):
        text = text.strip()
        return int(text) if text.isdigit() and int(text) > 0 else None

    def _subfolder_name(self) -> str:
        if not self._use_subfolder.get():
            return ""
        name = self._subfolder.get().strip().strip("/\\")
        return name or DEFAULT_SUBFOLDER

    def _current_opts(self) -> dict:
        return {
            "mode":        self._mode.get(),
            "percent":     self._percent.get(),
            "width":       self._as_int(self._width.get()),
            "height":      self._as_int(self._height.get()),
            "keep_aspect": self._keep_aspect.get(),
            "no_enlarge":  self._no_enlarge.get(),
            "subfolder":   self._subfolder_name(),
        }

    def _refresh_drop_text(self, *_):
        if self._pending:
            self._drop_title.configure(
                text=f"{len(self._pending)} item(s) ready — click to resize")
        else:
            self._drop_title.configure(
                text="Drop images or folders here" if DND_OK
                else "Click to choose images")

        if self._mode.get() == "percent":
            what = f"{self._percent.get()}% of the original"
        else:
            w = self._as_int(self._width.get())
            h = self._as_int(self._height.get())
            fit = "fit inside" if self._keep_aspect.get() else "exact"
            what = f"{w or '?'} x {h or '?'} ({fit})"

        sub = self._subfolder_name()
        where = f"saved to ./{sub}/" if sub else "ORIGINALS OVERWRITTEN"
        self._drop_sub.configure(text=f"{what}  —  {where}")

    # ── input handlers ──────────────────────────────────────────────────────

    def _on_click_zone(self, _event=None):
        if self._pending:
            queued, self._pending = self._pending, []
            self._refresh_drop_text()
            self._start(queued)
        else:
            self._browse_files()

    def _browse_files(self):
        names = filedialog.askopenfilenames(title="Choose images")
        if names:
            self._start([Path(n) for n in names])

    def _browse_folder(self):
        folder = filedialog.askdirectory(title="Choose a folder of images")
        if folder:
            self._start([Path(folder)])

    def _on_drop(self, event):
        self._on_leave(event)
        self._start(parse_dropped(event.data))

    def _start(self, paths: list):
        if self._busy:
            self._log("Still working — wait for the current batch to finish.",
                      "err")
            return

        opts = self._current_opts()
        if opts["mode"] == "pixels" and not (opts["width"] or opts["height"]):
            self._log("Set a width and/or a height first.", "err")
            return

        files = collect_files(paths, self._recursive.get(), opts["subfolder"])
        if not files:
            self._log("No supported image files found.", "info")
            return

        self._busy = True
        threading.Thread(target=self._run_batch, args=(files, opts),
                         daemon=True).start()

    def _run_batch(self, files: list, opts: dict):
        """Worker thread — it only ever touches the queue, never a widget."""
        self._queue.put(("log", f"── Resizing {len(files)} file(s) ──", "head"))
        for path in files:
            ok, msg = process_file(path, opts)
            self._queue.put(("log", msg, "ok" if ok else "err"))
            self._queue.put(("count", ok, msg.startswith("✗")))
        self._queue.put(("log", "── Done ──", "info"))
        self._queue.put(("done",))

    def _pump(self):
        """Main thread — drain whatever the worker reported and repaint."""
        try:
            while True:
                kind, *args = self._queue.get_nowait()
                if kind == "log":
                    self._log(*args)
                elif kind == "count":
                    self._bump(*args)
                elif kind == "done":
                    self._busy = False
        except queue.Empty:
            pass
        self.after(80, self._pump)

    # ── drag feedback ───────────────────────────────────────────────────────

    def _drop_widgets(self) -> list:
        kids = list(self.drop_zone.winfo_children())
        for child in list(kids):
            kids += list(child.winfo_children())
        return [self.drop_zone] + kids

    def _on_enter(self, _event):
        self.drop_zone.configure(highlightbackground=self.ACCENT)
        for w in self._drop_widgets():
            try:
                w.configure(bg=self.HOVER)
            except TclError:
                pass

    def _on_leave(self, _event):
        self.drop_zone.configure(highlightbackground=self.BORDER)
        for w in self._drop_widgets():
            try:
                w.configure(bg=self.CARD)
            except TclError:
                pass

    # ── log ─────────────────────────────────────────────────────────────────

    def _log(self, msg: str, tag: str = ""):
        self._log_text.configure(state=NORMAL)
        self._log_text.insert(END, msg + "\n", tag)
        self._log_text.see(END)
        self._log_text.configure(state=DISABLED)

    def _clear_log(self):
        self._log_text.configure(state=NORMAL)
        self._log_text.delete("1.0", END)
        self._log_text.configure(state=DISABLED)
        self._ok_count = self._err_count = 0
        self._refresh_counts()

    def _bump(self, success: bool, is_error: bool):
        if success:
            self._ok_count += 1
        elif is_error:
            self._err_count += 1        # a skip is neither a win nor an error
        self._refresh_counts()

    def _refresh_counts(self):
        self._lbl_ok.configure(text=f"✓  {self._ok_count} resized")
        self._lbl_err.configure(text=f"✗  {self._err_count} errors")


def main():
    args = [Path(a) for a in sys.argv[1:] if not a.startswith("-")]
    App([p for p in args if p.exists()]).mainloop()


if __name__ == "__main__":
    main()
