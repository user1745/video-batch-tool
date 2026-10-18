# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller 打包配置 —— 生成"单文件、双击即用、无外部依赖"的 exe。
#
# 用法:
#   python -m PyInstaller --noconfirm --distpath dist_new --workpath build video_batch_tool.spec
#
# 说明:
#   * ffmpeg.exe / ffprobe.exe / 字体全部打进 exe。单文件模式启动时会先把它们
#     解压到临时目录, 程序通过 sys._MEIPASS 自动定位, 见 video_batch_tool.py 里的
#     resource_dirs() / find_ffmpeg_exe() / find_ffprobe_exe() / find_font_file()。
#   * 外挂在 exe 同目录的 ffmpeg.exe / *.ttf 优先级仍高于内置版本, 方便覆盖。
#   * 想回到"exe + 同目录资源"的小体积分发方式, 把 binaries / datas 清空即可。
import os

try:
    _BASE = SPECPATH          # spec 所在目录 = 项目根目录
except NameError:             # 兜底: 直接当脚本执行 spec 时
    _BASE = os.path.dirname(os.path.abspath(__file__))

_FONT = '凤凰点阵体VonwaonBitmap16px.ttf'

a = Analysis(
    ['video_batch_tool.py'],
    pathex=[],
    binaries=[
        (os.path.join(_BASE, 'dist', 'ffmpeg.exe'), '.'),
        (os.path.join(_BASE, 'dist', 'ffprobe.exe'), '.'),
    ],
    datas=[
        (os.path.join(_BASE, 'dist', _FONT), '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='video_batch_tool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # ffmpeg/ffprobe 已是静态自解压二进制, 再走 UPX 收益极低而耗时极长, 直接排除
    upx_exclude=['ffmpeg.exe', 'ffprobe.exe'],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
