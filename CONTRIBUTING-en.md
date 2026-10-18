# Contributing to Video Dynamic Timestamp Batch Tool

Thanks for taking the time to contribute! This document covers how to report
problems, propose changes, and what the maintainer expects from a pull request.

English | [简体中文](CONTRIBUTING.md)

---

## Ways to contribute

| I want to… | Do this |
| --- | --- |
| Report a bug | [Open an issue](#reporting-a-bug) |
| Request a feature | [Open an issue](#requesting-a-feature) with the *enhancement* label |
| Fix a bug / add code | [Open a pull request](#submitting-a-pull-request) |
| Improve the docs | Edit `README.md` / `README-en.md` and open a pull request |
| Translate the UI | Open an issue first so strings can be centralised |

---

## Reporting a bug

Please include as much of the following as you can — it is the difference
between a one-minute fix and a week of guesswork:

1. **What you did** — the exact steps to reproduce.
2. **What you expected** and **what happened instead**.
3. **The self-test output.** This is the single most useful artifact:

   ```powershell
   .\dist\video_batch_tool.exe --selftest
   type $env:TEMP\video_batch_tool_selftest.txt
   ```

   It reports which ffmpeg / ffprobe / font was actually used, and runs a real
   render test.
4. **Environment** — Windows version, display scaling (e.g. 100% / 125% / 200%),
   GPU model if you used hardware acceleration.
5. **The log panel**, copied as text if possible.

> 🔒 **Never paste secrets.** This tool has no API keys, but please still redact
> personal paths and filenames if they are sensitive.

---

## Requesting a feature

Open an issue describing the use case rather than the implementation. "I need to
process 40 clips a day and re-typing the same offsets 40 times is painful" is far
more useful than "add a loop".

---

## Submitting a pull request

### 1. Set up

```bash
git clone https://github.com/user1745/video-batch-tool.git
cd video-batch-tool
```

There is nothing to install — the app is standard library only.

### 2. Branch

```bash
git checkout -b fix/preview-throttle
```

### 3. Verify before you push

Run these four checks. All of them are quick and none require network access.

```bash
# 1) Syntax check
python -m py_compile video_batch_tool.py

# 2) Resource self-test (built exe or source)
python video_batch_tool.py --selftest

# 3) Smoke test: launch, confirm the window renders, close it
python video_batch_tool.py

# 4) Rebuild the exe if your change affects packaging
pip install pyinstaller==6.22.1
python -m PyInstaller --noconfirm --distpath dist_new --workpath build video_batch_tool.spec
```

### 4. Coding conventions

- **Single-file layout.** All source lives in `video_batch_tool.py`. Please do not
  split it into modules without discussing it in an issue first.
- **Comments explain *why*, not *what*.** Match the surrounding style: dense
  Chinese block comments that record measurements, gotchas and rejected
  alternatives.
- **Never change rendered output unintentionally.** The filter graph is the
  product. If a change alters what FFmpeg emits, treat it as a behaviour change
  and say so explicitly in the PR description.

  <details>
  <summary><b>Known trap: do not merge <code>drawtext</code> filters</b></summary>

  Merging adjacent characters that share a font size and colour into a single
  `drawtext` looks like an easy ~200 ms win. **It is not safe.** The app lays
  glyphs out on a fixed grid (0.5 em / 1 em), while a merged `drawtext` uses the
  font's real advance widths. Measured on the bundled fonts at size 60:

  | Font | digit advance | CJK advance |
  | --- | --- | --- |
  | VonwaonBitmap (bitmap) | 33 px | 36 px |
  | Microsoft YaHei | ~35 px | 100 px |

  None of these match the grid, so merging silently shifts letter spacing across
  the whole line — in the preview *and* in the exported video.

  </details>

- **UI stays native.** Prompt dialogs use `tkinter.messagebox` so they inherit
  the Windows theme and DPI. Do not reintroduce custom-drawn `Toplevel` popups.
- **Comments and docstrings** may be in Chinese, matching the existing file.

### 5. Commit messages

Write them in Chinese, prefixed by category, matching the existing history:

```text
界面: 将「修改参数自动刷新预览」移到预览面板右上角
预览: 500ms 防抖改为 140ms 限流, 修复拖动时不刷新
修复: _char_width 未处理全角标点导致的字距偏移
```

### 6. Open the PR

Explain **what changed**, **why**, and **how you verified it**. If you measured
anything, include the numbers — timings, frame counts, before/after.

---

## Adding fonts

1. Put the `.ttf` in the repository root.
2. Add it to `.gitignore` **exceptions** if it lives elsewhere.
3. To bundle it, update `_FONT` in `video_batch_tool.spec`.
4. Rebuild and run `--selftest`.

Note that `find_font_file()` selects the **first file after sorting by name**, so
with several fonts present the alphabetically-first one wins at runtime.

---

## Code of conduct

Be decent to each other. Assume good faith, critique the code rather than the
person, and take accessibility and localisation seriously — this is a Chinese-
language Windows tool and that context matters.

---

## License

By contributing, you agree that your contributions are licensed under the
[GNU General Public License v2.0 or later](LICENSE).