<div align="center">

# Video Dynamic Timestamp Batch Tool

**A Windows desktop app that burns a second-by-second ticking timestamp overlay onto videos in bulk — with live preview, automatic contrast-aware colours, crop-and-scale, and automatic 15 MB size-capping.**

[![License: GPL-2.0-or-later](https://img.shields.io/badge/License-GPL--2.0--or--later-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-informational.svg)](https://learn.microsoft.com/windows/release-health/)
[![GUI](https://img.shields.io/badge/GUI-Tkinter-purple.svg)](https://docs.python.org/3/library/tkinter.html)
[![Build](https://img.shields.io/badge/build-PyInstaller%206.22-blue.svg)](https://pyinstaller.org/)

English | [简体中文](README.md)

</div>

<div align="center">
  <img src="docs/screenshot.png" width="800" alt="Main window of the Video Dynamic Timestamp Batch Tool, showing the live preview panel on the right">
</div>

> The screenshot above shows the main window: parameters and the log on the left, a live preview on the right. Notice the timestamp renders **white over the dark part of the frame and flips to black over the light part** — that is the *Auto Contrast* switch at work.

---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Feature Reference](#feature-reference)
- [Building the Single-File Executable](#building-the-single-file-executable)
- [Command-Line Diagnostics](#command-line-diagnostics)
- [How It Works](#how-it-works)
- [Project Structure](#project-structure)
- [Fonts](#fonts)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

---

## Features

| Feature | Description |
| --- | --- |
| **Dynamic timestamp** | The clock ticks with the video instead of staying static. The date part is a literal string; the six `HH:MM:SS` digits are evaluated per frame by FFmpeg's `drawtext` `eif` expression. |
| **Live preview** | Every parameter change refreshes the preview automatically. Uses *throttling*, not debouncing, so the image keeps following you **even while you hold a spinner and drag**. |
| **Per-character styling** | Colour and font size per character via `index=colour[@size]`, with range support such as `1,7,9-11`. |
| **Automatic contrast colours** | Samples the brightness behind the text, flipping the whole glyph between white and black automatically — what you see in preview is what you get. |
| **Crop & scale** | Crop by any margin then stretch to 1920×1080. Font size, offsets and outline width are all specified in **source-video pixels**, so toggling the feature never shifts the layout. |
| **Batch processing** | One file or a whole folder. Output is re-encoded down to **≤ 15 MB** and a matching `.jpg` cover is exported. |
| **Encoder speed presets** | `ultrafast` / `fast` / `medium` / GPU hardware acceleration (NVIDIA, Intel, AMD). GPU failures silently fall back to CPU. |
| **JK16 / JK5 rules** | Files whose names contain `JK16` or `JK5` automatically get a preset rendering profile. |
| **Native dialogs** | All prompts use `tkinter.messagebox`, inheriting your Windows theme, DPI scaling, system fonts and colours. No custom-drawn popups. |
| **Pause / resume / cancel** | Interrupt a batch run at any time; cancelling removes the incomplete output directory for you. |
| **Zero dependencies** | `python video_batch_tool.py` just works — **no `pip install` required**, standard library only. |
| **Single-file distribution** | FFmpeg, FFprobe and the font are embedded in one exe. The target machine needs nothing pre-installed. |

---

## Requirements

| Item | Requirement |
| --- | --- |
| OS | **Windows 10 / 11** (uses `winsound`, `ctypes` and other Windows-only modules) |
| Python | **3.8 or newer** (developed and tested on 3.14) |
| Third-party packages | **None.** Standard library only (`tkinter`, `subprocess`, `queue`, `threading`, …) |
| Disk space | ~10 MB to run from source; ~280 MB for the full release payload (88 MB exe + 98 MB ffmpeg + 98 MB ffprobe) |
| GPU | Optional. Only needed for the hardware-accelerated preset, and it degrades to CPU automatically. |

---

## Installation

### Option 1 — use the prebuilt exe (recommended)

Take `video_batch_tool.exe` from the `dist/` directory and copy it to the target machine, then double-click. The release exe is self-contained; the sibling `ffmpeg.exe`, `ffprobe.exe` and `.ttf` files are only needed when building or intentionally overriding the embedded resources.

> The single-file exe already embeds every resource. At startup the app looks for FFmpeg and the font in this order: **next to the exe → embedded resources → system `PATH`**. Dropping your own `ffmpeg.exe` beside the exe overrides the bundled one.

### Option 2 — run from source

No `pip install` needed. Clone and run:

```bash
git clone https://github.com/user1745/video-batch-tool.git
cd video-batch-tool
python video_batch_tool.py
```

### Option 3 — install the build tool (only if you want to rebuild the exe)

```bash
pip install pyinstaller==6.22.1
```

---

## Quick Start

1. **Choose an input** — click **Select File** for a single video, or **Select Folder** to process a whole directory.
2. **Choose an output** — pick a destination in *Save directory* (leave empty to get an `output` folder beside the input).
3. **Tune the parameters** — format, position, font, size, X/Y offset, outline, and so on. The preview on the right refreshes as you type.
4. **Press play** — hit **▶ Start**; progress and logs appear in the bottom panel.

### Usage example

```bash
# 1) Launch the GUI
python video_batch_tool.py

# 2) Verify FFmpeg and the font are usable
#    (report is written to %TEMP%\video_batch_tool_selftest.txt)
video_batch_tool.exe --selftest

# 3) Check whether the success/failure cues are audible on this machine
video_batch_tool.exe --cue-test
```

---

## Feature Reference

<details>
<summary><b>Timestamp formats (6 built in)</b></summary>

`YYYY-MM-DD HH:MM:SS` · `YYYY/MM/DD HH:MM:SS` · `DD-MM-YYYY HH:MM:SS` · `YYYY年MM月DD日 HH:MM:SS` · `YYYY-MM-DD HH:MM` · `HH:MM`

The start time defaults to *now* and can be overridden.

</details>

<details>
<summary><b>Display positions (7)</b></summary>

Centre · Top-left · Top-right · Bottom-left · Bottom-right · Top-centre · Bottom-centre

The X and Y offsets nudge away from the chosen anchor, measured in **source-video pixels**.

</details>

<details>
<summary><b>Per-character styling syntax</b></summary>

Enter `index=colour[@size]` in the character-rules field. Separate multiple rules with `;`. Colour names may be given in Chinese, and index ranges are supported:

```text
1,7,9-11=black
1=red@30
1,2,3=#ff8800;4,5=blue@28
```

Numbering: spaces are skipped, all other visible characters are numbered from `1` upwards.

</details>

<details>
<summary><b>The four switches</b></summary>

| Switch | Effect |
| --- | --- |
| **Crop & scale** | Crop by the four margins, then stretch to 1920×1080 |
| **Dynamic timestamp** | Overlay the ticking timestamp |
| **Auto contrast colours** | Flip between black and white glyphs based on background brightness |
| **Font outline** | Add an outline; the colour can default to the automatic contrast pair |

</details>

<details>
<summary><b>Encoder speed presets</b></summary>

`ultrafast` (strongly recommended) · `fast` (balanced) · `medium` (best compression) · GPU hardware acceleration (NVIDIA / Intel / AMD)

</details>

<details>
<summary><b>Output size handling</b></summary>

After overlaying the watermark the app runs **two x264 passes** to squeeze each output under **15 MB**, and writes a same-named `.jpg` cover alongside it. Useful for platforms with a hard upload limit.

</details>

---

## Building the Single-File Executable

The project ships a PyInstaller spec that folds FFmpeg, FFprobe and the font into a single exe:

```bash
# Install the build tool
pip install pyinstaller==6.22.1

# Build (artifacts go to dist_new/, intermediate files to build/)
python -m PyInstaller --noconfirm --distpath dist_new --workpath build video_batch_tool.spec
```

Then copy `dist_new/video_batch_tool.exe` over `dist/`.

> ⚠️ **Prerequisite**: `video_batch_tool.spec` reads `ffmpeg.exe`, `ffprobe.exe` and `凤凰点阵体VonwaonBitmap16px.ttf` from the `dist/` directory. Those files must be present or the build fails.

> 💡 **Smaller alternative**: for an *exe + sibling resources* layout, blank out `binaries` and `datas` in the spec — you then just have to ship FFmpeg and the font beside the exe.

---

## Command-Line Diagnostics

Two flags are recognised. Double-clicking is unaffected; they only act when passed explicitly:

| Flag | Purpose |
| --- | --- |
| `--selftest` | Verifies ffmpeg / ffprobe / the font and performs a real timestamp render test. The report is written to `%TEMP%\video_batch_tool_selftest.txt`; exit code `0` means everything passed. |
| `--cue-test` | Plays the success cue then the failure cue, to confirm the machine can actually make noise. |

```powershell
# Use Start-Process to read the exit code — a console-less exe will not set $LASTEXITCODE
Start-Process -Wait -PassThru -FilePath .\dist\video_batch_tool.exe -ArgumentList "--selftest"
```

---

## How It Works

<details>
<summary><b>How does the timestamp actually tick?</b></summary>

The timestamp is split into **character slots**. The year/month/day portion is a literal (`static`) string; the six `HH:MM:SS` digits are dynamic expressions evaluated per frame by `drawtext`'s `eif` against the frame time `(U + t)`, where `U` is the start time as a Unix timestamp:

```text
text='%{eif\:trunc((U+t)/3600)%360\:d}'
```

**Each character is its own `drawtext` filter**, which is what makes per-character colour and size possible. Baseline alignment is unified via `y_align=baseline`, and the `x` coordinate accumulates using East-Asian full/half width metrics.

</details>

<details>
<summary><b>How does automatic contrast work?</b></summary>

A small region around the text is cropped, blurred with `gblur`, reduced to luminance with `lut`, binarised with `geq`, then temporally smoothed with `tmix=frames=75`. That mask is used by `maskedmerge` to blend a black-glyph pass with a white-glyph pass. Sampling is grouped by year/month/day/hour/minute/second so a whole glyph — never half of one — flips colour at a time.

</details>

<details>
<summary><b>Why is the preview fast?</b></summary>

Preview renders **only the first frame** (`-frames:v 1`) on a background thread and hands the PNG back through a queue, so the UI never blocks. Scheduling uses a **140 ms throttle** rather than a debounce: dragging a spinner no longer keeps resetting the timer, and the next frame starts the moment the current one lands.

</details>

<details>
<summary><b>Resource lookup order</b></summary>

```
next to the exe        (lets users override the bundled build)
        ↓ if missing
sys._MEIPASS           (the temp dir onefile builds unpack into)
        ↓ if missing
system PATH            (locally installed ffmpeg / ffprobe / fonts)
```

The chosen source is written to the log at startup and can be verified with `--selftest`.

</details>

---

## Project Structure

```text
video-batch-tool/
├── video_batch_tool.py              # All source code (single file, ~3900 lines)
├── video_batch_tool.spec            # PyInstaller single-file build config
├── README.md                         # Simplified Chinese docs (GitHub renders this by default)
├── README-en.md                      # This file (English)
├── LICENSE                           # GPL-2.0-or-later (GitHub only detects this exact name)
├── CONTRIBUTING.md                   # Contributing guide (Simplified Chinese)
├── CONTRIBUTING-en.md                # Contributing guide (English)
├── .gitignore
│
├── docs/
│   └── screenshot.png               # UI screenshot
│
├── dist/                            # Release payload directory
│   ├── video_batch_tool.exe         #   Prebuilt single-file application
│   ├── ffmpeg.exe                   #   FFmpeg (embedded at build time)
│   ├── ffprobe.exe                  #   FFprobe (embedded at build time)
│   └── 凤凰点阵体VonwaonBitmap16px.ttf  #  Font embedded at build time
│
├── VonwaonBitmap-16px.ttf           # Alternate font (wins at runtime by sort order)
└── 凤凰点阵体VonwaonBitmap16px.ttf   # The font referenced by the spec
```

<details>
<summary><b>Why are there two font files?</b></summary>

`find_font_file()` picks the **first result after sorting by filename** when several `.ttf` files are present. `VonwaonBitmap-16px.ttf` sorts before the Chinese-named file, so it wins at runtime; the spec file, meanwhile, explicitly bundles `凤凰点阵体VonwaonBitmap16px.ttf`. Both are 16 px bitmap-style fonts.

</details>

---

## Fonts

The default is a **bitmap pixel font**, which gives the retro "security camera" look. To use your own:

- **At runtime** — drop any `.ttf` next to the exe; it is picked up automatically (with several present, the first by filename sort wins).
- **From the UI** — use **Browse** next to the *Font file* field.
- **Baked into the exe** — edit the `_FONT` variable in `video_batch_tool.spec`, or replace the file in `dist/` and rebuild.

> Note: the app lays glyphs out on a **fixed grid** (0.5 em for half-width, 1 em for full-width) rather than the font's real advance widths. That keeps spacing identical across clips of different resolutions.

---

## Troubleshooting

<details>
<summary><b>The exe does nothing when double-clicked</b></summary>

Run the self-test first:

```bash
.\dist\video_batch_tool.exe --selftest
```

If it reports FFmpeg missing, make sure `ffmpeg.exe`, `ffprobe.exe` and the font sit in the same folder as the exe.

</details>

<details>
<summary><b>The preview feels slow</b></summary>

*Auto contrast colours* renders the text **twice** (a black pass and a white pass) and blends them, which doubles the `drawtext` count and roughly triples render time. Preview fidelity stays correct either way, so switch it off if you need the speed.

</details>

<details>
<summary><b>I cannot hear the cues</b></summary>

Run `--cue-test` to play the success and failure tones. If silent, check the Windows system volume and the *System sounds* device.

</details>

<details>
<summary><b>Output still exceeds 15 MB</b></summary>

Two x264 passes already run automatically. Very long or visually complex clips can still overshoot — switch to the *medium* preset or trim the source.

</details>

---

## Contributing

Issues and pull requests are welcome. See the **[Contributing Guide](CONTRIBUTING-en.md)** for the full workflow.

---

## License

Released under the **[GNU General Public License v2.0 or later](LICENSE)**.

```
Copyright (c) 2026 Dong JianXue
```

<details>
<summary><b>Third-party components</b></summary>

This project bundles **no third-party source code**. The following binaries ship in the release artifacts and remain under their own licences:

| Component | Version | Licence |
| --- | --- | --- |
| FFmpeg | 9.0.1 | GPL-2.0-or-later build (`--enable-gpl`) |
| FFprobe | 9.0.1 | Same as FFmpeg |
| 凤凰点阵体 VonwaonBitmap 16px font | — | See the notice inside the font file |

> ⚠️ **Distribution notice**: the bundled FFmpeg was built with `--enable-gpl`, so this project and its bundled executable distribution are released under GPL-2.0-or-later. The FFmpeg 9.0.1 source is available from the [official FFmpeg release archive](https://ffmpeg.org/releases/ffmpeg-9.0.1.tar.xz); the build configuration is recorded in the bundled binary's `-version` output. Any redistributed executable must preserve the GPL notices and provide the corresponding source under the same terms.

</details>