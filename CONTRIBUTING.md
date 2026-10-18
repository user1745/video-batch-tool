# 参与贡献 · 视频动态时间戳批量处理工具

感谢你愿意花时间参与贡献！本文说明如何反馈问题、提交改动，以及维护者对 Pull Request 的期望。

[English](CONTRIBUTING-en.md) | <b>简体中文</b>

---

## 贡献方式

| 我想…… | 请这样 |
| --- | --- |
| 报告 Bug | [提交 Issue](#报告-bug) |
| 提需求 | 提交 Issue 并加 *enhancement* 标签 |
| 修 Bug / 写代码 | [提交 Pull Request](#提交-pull-request) |
| 改进文档 | 修改 `README.md` / `README-en.md` 后提交 PR |
| 翻译界面 | 请先提 Issue，以便统一收拢文案 |

---

## 报告 Bug

请尽量附上以下信息 —— 这是「一分钟修好」和「猜一周」的分水岭：

1. **你做了什么** —— 可复现问题的具体步骤。
2. **你期望什么**、**实际发生了什么**。
3. **自检输出**（最重要的一份材料）：

   ```powershell
   .\dist\video_batch_tool.exe --selftest
   type $env:TEMP\video_batch_tool_selftest.txt
   ```

   它会报告实际使用的是哪个 ffmpeg / ffprobe / 字体，并做一次真实渲染测试。
4. **运行环境** —— Windows 版本、显示缩放（如 100% / 125% / 200%）、若用了硬件加速请附显卡型号。
5. **日志面板**内容，尽量以文本形式粘贴。

> 🔒 **请勿粘贴任何密钥或隐私信息。** 本工具不含 API Key，但若路径或文件名涉及隐私仍请先行脱敏。

---

## 提需求

提交 Issue 时请描述**使用场景**而不是实现方案。写「我每天要处理 40 条片子，同一组偏移量要重复填 40 次」远比「加个循环」有用。

---

## 提交 Pull Request

### 1. 准备环境

```bash
git clone https://github.com/user1745/video-batch-tool.git
cd video-batch-tool
```

无需安装任何依赖 —— 程序只用标准库。

### 2. 新建分支

```bash
git checkout -b fix/preview-throttle
```

### 3. 推送前请先自查

下面四项检查都很快，且都不需要联网：

```bash
# 1) 语法检查
python -m py_compile video_batch_tool.py

# 2) 资源自检（源码运行或已打包的 exe 均可）
python video_batch_tool.py --selftest

# 3) 冒烟测试：启动、确认窗口正常渲染、关闭
python video_batch_tool.py

# 4) 若改动涉及打包，重新构建 exe
pip install pyinstaller==6.22.1
python -m PyInstaller --noconfirm --distpath dist_new --workpath build video_batch_tool.spec
```

### 4. 代码约定

- **保持单文件结构。** 全部源码位于 `video_batch_tool.py`。若你想拆分模块，请先开 Issue 讨论。
- **注释写「为什么」，不写「做了什么」。** 与现有风格保持一致：用中文写密集的块注释，记录实测数据、踩过的坑以及被否决的方案。
- **绝不要无意间改变渲染结果。** 滤镜串就是本工具的产品。任何会改变 FFmpeg 输出的改动都应视为行为变更，并在 PR 描述中明确指出。

  <details>
  <summary><b>已知陷阱：不要合并 <code>drawtext</code> 滤镜</b></summary>

  把字号与颜色都相同的相邻字符合并成一条 `drawtext`，看起来能省下约 200ms，**但并不安全**。本工具按固定网格排字（半角 0.5em、全角 1em），而合并后的 `drawtext` 会改用字体真实的步进宽度。用内置字体在字号 60 下实测：

  | 字体 | 数字步进 | 汉字步进 |
  | --- | --- | --- |
  | VonwaonBitmap（点阵体） | 33 px | 36 px |
  | 微软雅黑 | 约 35 px | 100 px |

  没有一个与网格吻合，合并会让整行字距悄悄错位 —— **预览和导出的成片都会变形**。

  </details>

- **界面保持原生。** 提示弹窗使用 `tkinter.messagebox`，以便继承 Windows 主题与 DPI 缩放，请勿重新引入自绘的 `Toplevel` 弹窗。
- **注释与文档字符串**可使用中文，与现有文件保持一致。

### 5. 提交信息

使用中文撰写，按类别加前缀，与现有历史保持一致：

```text
界面: 将「修改参数自动刷新预览」移到预览面板右上角
预览: 500ms 防抖改为 140ms 限流, 修复拖动时不刷新
修复: _char_width 未处理全角标点导致的字距偏移
```

### 6. 提交 Pull Request

请说明**改了什么**、**为什么改**、**如何验证**。如果做了性能测量，请把数字附上 —— 耗时、帧数、改前改后对比。

---

## 添加字体

1. 把 `.ttf` 放到仓库根目录。
2. 若放在其他位置，请在 `.gitignore` 中加入例外规则。
3. 若要打包进 exe，请更新 `video_batch_tool.spec` 中的 `_FONT` 变量。
4. 重新打包并运行 `--selftest` 验证。

注意：`find_font_file()` 取的是**按文件名排序后的第一个**，因此存在多个字体时字母序在前的那一个会在运行时生效。

---

## 行为准则

请友善相处，保持善意假设；批评代码而不是人；认真对待无障碍与本地化 —— 这是一个面向中文用户的 Windows 工具，这一语境很重要。

---

## 许可证

你的贡献将以 [GNU GPL-2.0-or-later](LICENSE) 授权。