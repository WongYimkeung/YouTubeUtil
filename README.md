# YouTube 下载与校验工具

两个独立的 Python 脚本，用于下载和校验 YouTube 音频/视频文件。

- `yt_download.py` — 下载工具，支持单个视频和播放列表，可下载音频（MP3）或视频（MP4）
- `yt_verify.py` — 校验工具，检查媒体文件的格式、编码、流信息和完整性

---

## 一、使用环境

### 系统要求

- **操作系统**：Windows 10 / 11（脚本路径用 Windows 风格，但代码本身跨平台）
- **Python**：3.8 及以上（实测 3.10.11）
- **网络**：能访问 YouTube（中国大陆需要代理）

### 依赖安装

打开命令行（PowerShell 或 CMD），在脚本所在目录执行：

```bash
pip install -r requirements.txt
```

依赖说明：

| 包 | 版本要求 | 作用 |
|---|---|---|
| `yt-dlp[default]` | >= 2026.0.0 | YouTube 视频下载核心，`[default]` 附带 brotli/mutagen/pycryptodomex/yt-dlp-ejs，提升下载稳定性 |
| `requests` | >= 2.28.0 | 调用 YouTube innertube API 展开播放列表 |
| `imageio-ffmpeg` | >= 0.4.0 | 提供 ffmpeg 二进制（无需单独安装 ffmpeg） |

`requirements.txt` 内容：

```
yt-dlp[default]>=2026.0.0
requests>=2.28.0
imageio-ffmpeg>=0.4.0
```

### 额外依赖

- **Node.js**（用于执行 YouTube 的反爬验证脚本）
  - **为什么需要**：YouTube 会给每个下载请求设置 JS 验证挑战，yt-dlp 必须用 JS 运行时执行这些验证脚本才能下载。yt-dlp 默认只启用 Deno，但脚本通过 `--js-runtimes node` 改用更通用的 Node.js
  - **版本要求**：yt-dlp 要求 Node.js **>= 22.0.0**（部分挑战甚至要求 23.5.0+）。低于此版本会触发警告，详见下方"常见问题"
  - 下载安装：https://nodejs.org/（建议 LTS 版本，实测 v20.15.1）
  - 安装后确认 `node --version` 能输出版本号
  - 脚本已内置 `--js-runtimes node` 参数，会自动调用
  - **替代方案**：如果不想装 Node.js，可以装 Deno（https://deno.com/，最低要求 2.3.0，版本要求更宽松），但要手动删掉脚本里的 `--js-runtimes node` 参数

### 代理配置（可选）

如果你在中国大陆，需要代理才能访问 YouTube。脚本支持两种方式：

1. **系统代理**（推荐）：在 Windows 设置 → 网络和 Internet → 代理 里配置，脚本会自动读取
2. **命令行指定**：用 `--proxy http://127.0.0.1:1080` 参数显式指定

---

## 二、yt_download.py — 下载工具

### 基本用法

```bash
python yt_download.py <子命令> [参数]
```

两个子命令：

- `fetch` — 获取播放列表的视频清单（不下载，只列出）
- `download` — 下载音频或视频

### 子命令：fetch

获取 YouTube 播放列表的全部视频清单，写入 txt 文件。

```bash
python yt_download.py fetch -u <播放列表URL> [-o <输出文件>] [--proxy <代理>]
```

**参数**：

| 参数 | 必填 | 说明 |
|---|---|---|
| `-u, --url` | 是 | 播放列表 URL |
| `-o, --output` | 否 | 输出 txt 文件路径，默认当前目录 `playlist_videos.txt` |
| `--proxy` | 否 | 代理地址 |

**示例**：

```bash
# 获取播放列表视频清单
python yt_download.py fetch -u "https://www.youtube.com/playlist?list=PLXXXXX"

# 指定输出文件
python yt_download.py fetch -u "https://www.youtube.com/playlist?list=PLXXXXX" -o my_list.txt
```

**输出文件格式**（每行一个视频）：

```
001|视频ID|视频标题
002|视频ID|视频标题
...
```

**说明**：yt-dlp 默认只能拿到播放列表前 100 条视频（YouTube 限制）。本脚本用 YouTube innertube `next` API（IOS 客户端）绕过这个限制，能拿到全部视频。

### 子命令：download

下载音频或视频。

```bash
python yt_download.py download -u <URL> [选项]
```

**参数**：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `-u, --url` | （必填） | 视频或播放列表 URL |
| `-t, --type` | `audio` | 下载类型：`audio`（转 MP3）或 `video`（MP4） |
| `-o, --output` | `~/Downloads/yt_downloads` | 输出目录 |
| `-q, --quality` | `1080` | 视频质量（仅 video 有效），如 `720` / `1080` / `1440` |
| `-p, --parallel` | `3` | 并发下载数 |
| `--playlist-items` | 无 | 只下载播放列表的指定项，如 `1:3`（第 1-3 集）或 `5`（第 5 集） |
| `--prefix-index` | 关 | 单视频场景也加序号前缀（默认只有播放列表加） |
| `--quiet` | 关 | 静默模式，不显示下载进度条（只显示阶段信息） |
| `--proxy` | 无 | 代理地址 |
| `extra` | 无 | 额外传给 yt-dlp 的参数，用 `--` 分隔 |

### 下载示例

**1. 下载单个视频的音频**

```bash
python yt_download.py download -u "https://www.youtube.com/watch?v=XXXX" -t audio
```

输出文件：`视频标题.mp3`

**2. 下载单个视频的视频（1080p）**

```bash
python yt_download.py download -u "https://www.youtube.com/watch?v=XXXX" -t video
```

输出文件：`视频标题.mp4`

**3. 下载整个播放列表的音频**

```bash
python yt_download.py download -u "https://www.youtube.com/playlist?list=XXXX" -t audio
```

输出文件：`001-标题.mp3`、`002-标题.mp3`、...（按播放列表顺序编号）

**4. 下载播放列表前 10 集视频（720p）**

```bash
python yt_download.py download -u "https://www.youtube.com/playlist?list=XXXX" -t video -q 720 --playlist-items 1:10
```

**5. 自定义输出目录 + 代理**

```bash
python yt_download.py download -u "..." -t audio -o "D:\my_music" --proxy http://127.0.0.1:1080
```

**6. 透传 yt-dlp 原生参数**

```bash
# 用 -- 传额外参数给 yt-dlp（例如限制下载速度）
python yt_download.py download -u "..." -t video -- --limit-rate 5M
```

### 下载行为说明

- **音频**：下载后转为 MP3，VBR 最高质量（`-q:a 0`），48kHz 立体声
- **视频**：优先选 h264 编码（兼容性好、YouTube 限流少），合并视频+音频为 MP4；分辨率不超过指定值（默认 1080p）
- **断点续传**：已存在的文件自动跳过（`--no-overwrites --continue`）
- **失败重试**：单视频失败重试 10 次，分片失败重试 10 次
- **进度显示**：
  - 默认显示下载进度（百分比、已下载大小、速度、剩余时间）
  - 在真正的终端里直接运行，会看到一行不断刷新的动态进度条
  - 加 `--quiet` 可关闭进度显示，只保留阶段信息（适合日志记录场景）
- **命名规则**：
  - 播放列表：`序号-标题.ext`（三位补零，如 `001-标题.mp3`）
  - 单视频：`标题.ext`（不加序号，可用 `--prefix-index` 强制加）

### 常见问题

**Q: 命令报 "'list' 不是内部或外部命令" 之类的错误？**
A: URL 含有 `&` 符号（如 `?v=XXX&list=YYY&index=116`），shell 会把 `&` 当成命令分隔符，把 URL 拆成多段。**解决：URL 必须用双引号包起来**：

```bash
# 错误（shell 把 &list=... 当成新命令）
python yt_download.py download -u https://www.youtube.com/watch?v=XXX&list=YYY -t audio

# 正确
python yt_download.py download -u "https://www.youtube.com/watch?v=XXX&list=YYY" -t audio
```

**附带提示**：如果 URL 带 `&list=...`，yt-dlp 会默认下载整个播放列表。只想下单个视频，有两个办法：
- 去掉 URL 里的 `&list=...&index=...`，只保留 `https://www.youtube.com/watch?v=XXX`
- 或者用 `--playlist-items <序号>` 指定只下载播放列表的某一项

**Q: 下载报 "HTTP Error 403" 怎么办？**
A: 通常是 YouTube 对 av01 编码限流。脚本已优先选 h264，若仍失败可降低质量重试（如 `-q 720`），或加 `--proxy` 换出口。

**Q: 播放列表只下载了前 100 集？**
A: 不会。脚本用 innertube API 展开全部视频。若确实只下了部分，检查 `fetch` 命令能否拿到全部清单。

**Q: 下载中断了怎么办？**
A: 直接重跑同一命令。已下载的文件会自动跳过，未完成的分片会续传。

**Q: 文件名太长报错？**
A: YouTube 标题可能很长。脚本已限制文件名 200 字符，若仍报错可缩短输出目录路径。

---

## 三、yt_verify.py — 校验工具

### 基本用法

```bash
python yt_verify.py <子命令> [参数]
```

两个子命令：

- `check` — 检查单个文件
- `verify` — 批量校验目录下的文件

### 子命令：check

检查单个媒体文件，输出详细的格式、编码、流信息。

```bash
python yt_verify.py check -f <文件路径> [--decode]
```

**参数**：

| 参数 | 必填 | 说明 |
|---|---|---|
| `-f, --file` | 是 | 文件路径 |
| `--decode` | 否 | 全量解码校验（验证每一帧完好，较慢但最可靠） |

**示例**：

```bash
# 快速检查（只读元数据）
python yt_verify.py check -f "D:\downloads\song.mp3"

# 完整校验（全量解码）
python yt_verify.py check -f "D:\downloads\video.mp4" --decode
```

**输出示例**：

```
文件: D:\downloads\video.mp4
大小: 176,151,292 bytes (168.0 MB)

容器格式: mov
时长: 52:43 (52.7 分钟)
比特率: 235 kb/s
流: 视频:h264(1280x720) + 音频:aac(48000Hz 5.1)

全量解码校验中...
解码完成: 实际时长 52:43
结论: 完整无损
```

### 子命令：verify

批量校验目录下的媒体文件。

```bash
python yt_verify.py verify -d <目录> [选项]
```

**参数**：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `-d, --directory` | （必填） | 目录路径 |
| `-e, --extensions` | `mp3,mp4,m4a,webm,mkv,mov,flac,wav` | 文件扩展名，逗号分隔 |
| `--decode` | 关 | 全量解码校验（较慢但最可靠） |
| `-p, --parallel` | `4` | 并发数 |
| `--report` | 无 | 报告输出路径（可选） |

**示例**：

```bash
# 校验目录下所有 mp3
python yt_verify.py verify -d "D:\downloads\audio" -e mp3

# 校验多种格式 + 全量解码 + 输出报告
python yt_verify.py verify -d "D:\downloads" -e mp3,mp4,m4a --decode --report report.txt

# 只校验视频文件
python yt_verify.py verify -d "D:\downloads\video" -e mp4,mkv,mov
```

**输出示例**：

```
[verify] 共 116 个文件，并发 4
[1/116] OK       001-视频标题-001.mp3
[2/116] OK       002-视频标题-002.mp3
...
[116/116] OK     116-视频标题-116.mp3

================================================================================
完整 (OK): 116
损坏 (BROKEN): 0
错误 (ERROR): 0

文件名                                             容器    时长        流信息
----------------------------------------------------------------------------------------------------
001-视频标题-001.mp3                              mp3     52:43       音频:mp3(48000Hz stereo)
002-视频标题-002.mp3                              mp3     57:08       音频:mp3(48000Hz stereo)
...
```

### 校验内容说明

| 校验项 | 不带 `--decode` | 带 `--decode` |
|---|---|---|
| 容器格式（mp3/mp4/mov 等） | ✅ | ✅ |
| 编码格式（mp3/aac/h264/vp9 等） | ✅ | ✅ |
| 流信息（音频/视频流、分辨率、采样率） | ✅ | ✅ |
| 时长、比特率 | ✅ | ✅ |
| 文件可解析性 | ✅ | ✅ |
| 每一帧完好性 | ❌ | ✅ |
| 实际解码时长 | ❌ | ✅ |

**何时用 `--decode`**：
- 下载完成后做最终确认
- 怀疑文件损坏（如播放器进度条异常、播放卡顿）
- 重要资料归档前

**何时不带 `--decode`**：
- 快速浏览目录下有哪些文件
- 只想知道格式和时长

### 支持的格式

校验工具依赖 ffmpeg，理论上支持 ffmpeg 能解析的所有格式，包括但不限于：

- **音频**：mp3, m4a, aac, flac, wav, ogg, opus
- **视频**：mp4, mkv, mov, webm, avi, flv, ts

---

## 四、完整工作流示例

### 场景：下载并校验一个播放列表

```bash
# 1. 先看播放列表有多少视频
python yt_download.py fetch -u "https://www.youtube.com/playlist?list=PLXXXXX"

# 2. 下载全部音频
python yt_download.py download -u "https://www.youtube.com/playlist?list=PLXXXXX" -t audio -o "D:\my_audio"

# 3. 校验下载结果（快速）
python yt_verify.py verify -d "D:\my_audio" -e mp3

# 4. 校验下载结果（完整解码，确认无损）
python yt_verify.py verify -d "D:\my_audio" -e mp3 --decode --report "D:\my_audio\校验报告.txt"
```

### 场景：下载单个视频的最高质量

```bash
# 下载 1080p 视频
python yt_download.py download -u "https://www.youtube.com/watch?v=XXXX" -t video -q 1080

# 校验
python yt_verify.py check -f "~/Downloads/yt_downloads/视频标题.mp4" --decode
```

---

## 五、故障排查

### 问题：下载报 "No supported JavaScript runtime"

**现象**：下载时出现警告：

```
WARNING: [youtube] No supported JavaScript runtime could be found.
Only deno is enabled by default; to use another runtime add --js-runtimes RUNTIME[:PATH]
YouTube extraction without a JS runtime has been deprecated, and some formats may be missing.
```

**原因**：Node.js 版本太低。yt-dlp 要求 Node.js **>= 22.0.0**（源码 `utils/_jsruntime.py` 第 120 行写死），低于此版本会被标记为 "unsupported" 并触发警告。脚本已经带了 `--js-runtimes node`，所以不是没传参数——是 Node.js 版本不达标。

**实际影响**：**通常无影响**。实测 Node.js v20.15.1 下：
- ✅ 音频下载正常（转 MP3）
- ✅ 视频下载正常（含 1080p/2160p）
- ✅ 播放列表下载正常（实测 116 集全部完成）
- ✅ 所有视频格式可见（用 `yt-dlp -F <url>` 验证）

警告说的"some formats may be missing"是预防性提示，**大多数视频不启用强制 JS 挑战**，用旧的 android vr 客户端 API 就能拿到全部格式。

**何时需要处理**：
- 如果某次下载突然失败或质量明显受限，再考虑升级 Node.js
- 如果想彻底消除警告，升级到 Node.js 22 LTS 或更高

**升级 Node.js**（可选）：到 https://nodejs.org/ 下载 LTS 版本（v22+）覆盖安装，然后 `node --version` 确认版本。

---

### 问题：下载报 "HTTP Error 403: Forbidden"

**原因**：YouTube 对某些视频格式限流，通常是 av01 编码。

**解决**：
1. 脚本已优先选 h264，若仍失败，降低质量重试：`-q 720`
2. 换代理出口：`--proxy http://127.0.0.1:1080`
3. 隔几分钟重试（YouTube 限流是临时的）

### 问题：播放列表只下载了部分视频

**原因**：yt-dlp 默认只能拿前 100 条，本脚本用 innertube API 绕过，但 API 偶尔会失败。

**解决**：
1. 先用 `fetch` 命令确认能拿到全部视频清单
2. 若 `fetch` 也只拿到部分，重试几次
3. 用 `--playlist-items` 分批下载：`--playlist-items 1:50`、`--playlist-items 51:100`

### 问题：校验显示"无流"

**原因**：ffmpeg 输出格式变化，正则没匹配到流信息。

**解决**：用 `check` 命令看完整输出，确认 ffmpeg 能识别该文件。若 ffmpeg 都识别不了，文件可能已损坏。

### 问题：中文文件名乱码

**原因**：Windows 控制台默认 GBK 编码，Python 输出 UTF-8 时显示乱码。

**解决**：不影响实际功能，文件名本身是正确的。若想让控制台显示正常，运行前执行 `chcp 65001` 切换到 UTF-8 代码页。

---

## 六、文件说明

```
YouTubeUtil/
├── yt_download.py        # 下载工具
├── yt_verify.py          # 校验工具
├── requirements.txt      # Python 依赖清单
└── README.md             # 本文档
```
