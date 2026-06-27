"""
YouTube 通用下载工具

支持两种子命令：
  fetch    获取播放列表的视频清单（不下载），写入 txt 文件
  download 下载音频或视频

输入方式：
  - 单个视频 URL         直接下载该视频
  - 播放列表 URL         自动展开为列表内所有视频，按序号编号
  - 单个视频 URL + 列表  也会按列表顺序编号（yt-dlp 自动识别）

输出命名：
  默认 序号-标题.ext（播放列表场景）
  单个视频场景默认直接用标题，不加序号（可用 --prefix 强制加）

用法示例：
  # 下载单个视频的音频
  python yt_download.py download -u "https://www.youtube.com/watch?v=XXXX" -t audio

  # 下载整个播放列表的视频（默认 1080p）
  python yt_download.py download -u "https://www.youtube.com/playlist?list=XXXX" -t video

  # 获取播放列表的视频清单（不下载）
  python yt_download.py fetch -u "https://www.youtube.com/playlist?list=XXXX"

  # 自定义输出目录和并发数
  python yt_download.py download -u "..." -t audio -o "D:\\downloads" -p 5

  # 指定视频质量（720p）
  python yt_download.py download -u "..." -t video -q 720

  # 通过代理下载
  python yt_download.py download -u "..." --proxy http://127.0.0.1:1080
"""
import argparse
import os
import re
import sys
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import imageio_ffmpeg

FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()
API_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
NEXT_URL = f"https://www.youtube.com/youtubei/v1/next?key={API_KEY}"
WEB_HEADERS = {
    # 用通用 UA，不绑定具体平台，YouTube 不挑 UA
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


# ============================================================
# 播放列表展开（处理 YouTube 超过 100 条的限制）
# ============================================================

def _get_visitor_data(playlist_url, proxy=None):
    proxies = {"http": proxy, "https": proxy} if proxy else None
    r = requests.get(playlist_url, headers=WEB_HEADERS, timeout=60, proxies=proxies)
    r.raise_for_status()
    m = re.search(r'"visitorData":"([^"]+)"', r.text)
    if not m:
        raise RuntimeError("无法从播放列表页面提取 visitorData")
    return m.group(1)


def _extract_panel_videos(obj, found):
    """递归找出所有 playlistPanelVideoRenderer"""
    if isinstance(obj, dict):
        if "playlistPanelVideoRenderer" in obj:
            v = obj["playlistPanelVideoRenderer"]
            vid = v.get("videoId")
            if vid:
                title = v.get("title", {})
                if "simpleText" in title:
                    title_str = title["simpleText"]
                elif "runs" in title:
                    title_str = "".join(r.get("text", "") for r in title["runs"])
                else:
                    title_str = ""
                idx = v.get("navigationEndpoint", {}).get("watchEndpoint", {}).get("index", 0) or 0
                found.append({"videoId": vid, "title": title_str, "index": idx})
        for v in obj.values():
            _extract_panel_videos(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _extract_panel_videos(v, found)


def expand_playlist(playlist_url, proxy=None):
    """
    用 innertube next API 展开 YouTube 播放列表的全部视频。
    yt-dlp 默认只能拿 100 条（YouTube 限制），这个方法用 IOS 客户端拿全部。

    流程：
    1. 用 yt-dlp --flat-playlist 拿播放列表的第一个视频 ID（yt-dlp 至少能拿前 100 条）
    2. 用这个 videoId + playlistId 调 innertube next API（IOS 客户端），一次性拿全部视频

    返回 [{"videoId": ..., "title": ..., "index": ...}, ...]，按 playlist 顺序排序。
    """
    playlist_id_match = re.search(r"list=([A-Za-z0-9_-]+)", playlist_url)
    if not playlist_id_match:
        raise ValueError(f"无法从 URL 解析播放列表 ID: {playlist_url}")
    playlist_id = playlist_id_match.group(1)

    # 步骤 1：用 yt-dlp 拿第一个视频 ID
    yt_dlp_cmd = ["yt-dlp", "--flat-playlist", "--print", "%(id)s",
                  "--playlist-items", "1", "--js-runtimes", "node"]
    if proxy:
        yt_dlp_cmd += ["--proxy", proxy]
    yt_dlp_cmd.append(playlist_url)
    first_video_id = ""
    try:
        result = subprocess.run(yt_dlp_cmd, capture_output=True, text=True, timeout=120,
                                encoding="utf-8", errors="replace")
        # yt-dlp 可能输出警告行，找第一个 11 位字符串（YouTube videoId 固定 11 位）
        if result.stdout:
            for line in result.stdout.split("\n"):
                line = line.strip()
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", line):
                    first_video_id = line
                    break
    except subprocess.TimeoutExpired:
        print(f"[warn] yt-dlp 获取第一个视频 ID 超时，退回默认展开（可能只能拿前 100 条）",
              file=sys.stderr)
        return _expand_playlist_via_ytdlp(playlist_url, proxy)
    except Exception as e:
        raise RuntimeError(f"用 yt-dlp 获取第一个视频 ID 失败: {e}")

    if not first_video_id:
        # yt-dlp 拿不到，退回用 yt-dlp 的完整 flat-playlist（至少能拿前 100 条）
        print(f"[warn] 无法获取第一个视频 ID，退回 yt-dlp 默认（可能只能拿前 100 条）",
              file=sys.stderr)
        return _expand_playlist_via_ytdlp(playlist_url, proxy)

    # 步骤 2：拿 visitorData
    visitor_data = _get_visitor_data(playlist_url, proxy)

    # 步骤 3：调 next API
    body = {
        "context": {
            "client": {
                "clientName": "IOS",
                "clientVersion": "20.10.38",
                "hl": "zh-CN",
                "gl": "CN",
                "visitorData": visitor_data,
            }
        },
        "videoId": first_video_id,
        "playlistId": playlist_id,
    }
    headers = {
        "User-Agent": "com.google.ios.youtube/20.10.38 (iPhone; U; CPU iOS 17_5_1)",
        "Content-Type": "application/json",
    }
    try:
        r = requests.post(NEXT_URL, json=body, headers=headers, timeout=60,
                          proxies={"http": proxy, "https": proxy} if proxy else None)
        r.raise_for_status()
        data = r.json()
    except requests.exceptions.RequestException as e:
        # next API 失败（限流/网络/key 失效），退回 yt-dlp 兜底
        print(f"[warn] innertube next API 请求失败: {e}", file=sys.stderr)
        print(f"[warn] 退回 yt-dlp 默认展开（可能只能拿前 100 条）", file=sys.stderr)
        return _expand_playlist_via_ytdlp(playlist_url, proxy)

    videos = []
    _extract_panel_videos(data, videos)

    if not videos:
        # next API 没返回数据，退回 yt-dlp
        print(f"[warn] next API 未返回视频数据，退回 yt-dlp 默认", file=sys.stderr)
        return _expand_playlist_via_ytdlp(playlist_url, proxy)

    # 去重并按 index 排序
    seen = set()
    unique = []
    for v in videos:
        if v["videoId"] not in seen:
            seen.add(v["videoId"])
            unique.append(v)
    unique.sort(key=lambda v: v["index"] if v["index"] else 0)
    return unique


def _expand_playlist_via_ytdlp(playlist_url, proxy=None):
    """用 yt-dlp --flat-playlist 展开播放列表（受 YouTube 限制，可能只返回前 100 条）"""
    cmd = ["yt-dlp", "--flat-playlist", "--print", "%(playlist_index)s|%(id)s|%(title)s",
           "--js-runtimes", "node"]
    if proxy:
        cmd += ["--proxy", proxy]
    cmd.append(playlist_url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        raise RuntimeError("yt-dlp 展开播放列表超时（>5分钟）")
    videos = []
    for line in result.stdout.splitlines():
        parts = line.split("|", 2)
        if len(parts) >= 2:
            idx = int(parts[0]) if parts[0].isdigit() else 0
            vid = parts[1]
            title = parts[2] if len(parts) > 2 else ""
            videos.append({"videoId": vid, "title": title, "index": idx})
    return videos


# ============================================================
# yt-dlp 调用
# ============================================================

def _build_output_template(output_dir, is_playlist, prefix_index):
    """
    构建 yt-dlp 输出路径模板。
    - 播放列表场景或 prefix_index=True：序号-标题.ext
    - 单视频场景：标题.ext
    """
    if is_playlist or prefix_index:
        # %(playlist_index)s 是 yt-dlp 内置的播放列表序号变量
        # 02d 表示两位补零，但播放列表可能超过 99 集，用动态宽度
        return os.path.join(output_dir, "%(playlist_index)03d-%(title)s.%(ext)s")
    return os.path.join(output_dir, "%(title)s.%(ext)s")


def _build_cmd(url, media_type, output_template, quality, proxy, extra_args,
               playlist_items=None, parallel=1, quiet=False, no_playlist=False):
    """构建 yt-dlp 命令行"""
    cmd = [
        "yt-dlp",
        "--ffmpeg-location", FFMPEG_PATH,
        "--js-runtimes", "node",
        "-o", output_template,
        "--no-overwrites",
        "--continue",
        "--retries", "10",
        "--fragment-retries", "10",
        "--newline",  # 每条进度换行，避免 \r 刷新造成显示混乱
    ]
    if quiet:
        cmd.append("--no-progress")
    if no_playlist:
        # 带 list 参数的单视频 URL，强制只下该视频，不下整个播放列表
        cmd.append("--no-playlist")
    if proxy:
        cmd += ["--proxy", proxy]
    if playlist_items:
        cmd += ["--playlist-items", playlist_items]
    if parallel > 1:
        cmd += ["--concurrent-fragments", str(parallel)]
    if media_type == "audio":
        cmd += ["-x", "--audio-format", "mp3", "--audio-quality", "0"]
    elif media_type == "video":
        # 视频格式选择策略：
        # 1. 优先 avc1(h264) 编码的 mp4 视频 + m4a 音频（兼容性好、YouTube 限流少）
        # 2. 退回到任意 <= 指定分辨率的最佳 mp4
        # 3. 最后退回到任意最佳格式
        height = quality.rstrip("p") if quality else "1080"
        cmd += [
            "-f",
            (f"bv*[height<={height}][vcodec^=avc1][ext=mp4]"
             f"+ba[ext=m4a]"
             f"/bv*[height<={height}][ext=mp4]+ba[ext=m4a]"
             f"/b[height<={height}]"
             f"/b"),
            "--merge-output-format", "mp4",
        ]
    # 过滤掉 extra_args 里的 '--' 分隔符（argparse REMAINDER 会保留它）
    extra_args = [a for a in extra_args if a != "--"]
    cmd += extra_args
    cmd.append(url)
    return cmd


# ============================================================
# fetch 子命令
# ============================================================

def cmd_fetch(args):
    """获取播放列表的视频清单，写入 txt 文件"""
    url = args.url
    # 默认输出到脚本所在目录，避免 cwd 不确定时写到意外位置
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output = args.output or os.path.join(script_dir, "playlist_videos.txt")

    print(f"[fetch] 获取播放列表: {url}", flush=True)
    videos = expand_playlist(url, proxy=args.proxy)
    print(f"[fetch] 共 {len(videos)} 个视频", flush=True)

    with open(output, "w", encoding="utf-8") as f:
        for i, v in enumerate(videos, 1):
            title = v["title"].replace("|", " ").replace("\n", " ")
            f.write(f"{i:03d}|{v['videoId']}|{title}\n")
    print(f"[fetch] 已写入 {output}", flush=True)
    print(f"[fetch] 文件格式: 序号|视频ID|标题", flush=True)


# ============================================================
# download 子命令
# ============================================================

def cmd_download(args):
    """下载音频或视频"""
    url = args.url
    media_type = args.type
    output_dir = args.output
    quality = args.quality
    proxy = args.proxy

    os.makedirs(output_dir, exist_ok=True)

    # 判断 URL 类型：
    # - /playlist?list=XXX → 明确是播放列表，加序号前缀
    # - watch?v=XXX&list=YYY → 模糊情况，默认按单视频处理（加 --no-playlist），
    #   避免用户传带 list 参数的单视频 URL 时误下整个播放列表
    # - watch?v=XXX（不带 list）→ 单视频，不加序号
    is_playlist = "/playlist" in url
    is_single_with_list = ("watch?v=" in url and "list=" in url)
    prefix_index = is_playlist or args.prefix_index

    print(f"[download] 类型: {media_type}", flush=True)
    print(f"[download] 输出目录: {output_dir}", flush=True)
    if is_playlist:
        print(f"[download] 检测到播放列表 URL，将按序号编号（序号-标题.ext）", flush=True)
    elif is_single_with_list:
        print(f"[download] 检测到带 list 参数的单视频 URL，默认只下该视频（不加 --no-playlist 可下整个列表）", flush=True)
    elif args.prefix_index:
        print(f"[download] 单视频，加序号前缀（001-标题.ext）", flush=True)
    else:
        print(f"[download] 单视频，输出 标题.ext", flush=True)
    if media_type == "video":
        print(f"[download] 视频质量: {quality}p", flush=True)

    # yt-dlp 自己处理播放列表展开和并发下载（--concurrent-fragments）
    output_template = _build_output_template(output_dir, is_playlist, prefix_index)
    cmd = _build_cmd(url, media_type, output_template, quality, proxy,
                     args.extra or [], args.playlist_items, args.parallel, args.quiet,
                     no_playlist=is_single_with_list)

    print(f"[download] 开始下载...", flush=True)
    try:
        # 不捕获输出，让 yt-dlp 直接显示进度条到终端
        # yt-dlp 会用 \r 原地刷新进度，在真正的终端里显示漂亮的动态进度条
        result = subprocess.run(cmd)
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        print("\n[download] 用户中断", flush=True)
        sys.exit(130)


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="YouTube 通用下载工具（音频/视频，支持播放列表）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  # 下载单个视频的音频
  python yt_download.py download -u "https://www.youtube.com/watch?v=XXXX" -t audio

  # 下载整个播放列表的视频（默认 1080p）
  python yt_download.py download -u "https://www.youtube.com/playlist?list=XXXX" -t video

  # 获取播放列表视频清单（不下载）
  python yt_download.py fetch -u "https://www.youtube.com/playlist?list=XXXX"
""",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # fetch 子命令
    p_fetch = sub.add_parser("fetch", help="获取播放列表的视频清单")
    p_fetch.add_argument("-u", "--url", required=True, help="播放列表 URL")
    p_fetch.add_argument("-o", "--output", help="输出 txt 文件路径（默认脚本目录下 playlist_videos.txt）")
    p_fetch.add_argument("--proxy", help="代理地址，如 http://127.0.0.1:1080")

    # download 子命令
    p_dl = sub.add_parser("download", help="下载音频或视频")
    p_dl.add_argument("-u", "--url", required=True, help="视频或播放列表 URL")
    p_dl.add_argument("-t", "--type", choices=["audio", "video"], default="audio",
                       help="下载类型: audio(默认, 转 mp3) 或 video(默认 1080p mp4)")
    p_dl.add_argument("-o", "--output", default=os.path.join(os.path.expanduser("~"), "Downloads", "yt_downloads"),
                       help="输出目录（默认 ~/Downloads/yt_downloads）")
    p_dl.add_argument("-q", "--quality", default="1080",
                       help="视频质量，如 720/1080/1440（仅 video 类型有效，默认 1080）")
    p_dl.add_argument("-p", "--parallel", type=int, default=3,
                       help="并发下载数（仅多 URL 场景有效，默认 3）")
    p_dl.add_argument("--playlist-items", default=None,
                       help="只下载播放列表的指定项，如 1:3 表示第 1-3 集，5 表示第 5 集（仅播放列表有效）")
    p_dl.add_argument("--prefix-index", action="store_true",
                       help="单视频场景也加序号前缀（默认只有播放列表加）")
    p_dl.add_argument("--quiet", action="store_true",
                       help="静默模式，不显示下载进度条")
    p_dl.add_argument("--proxy", help="代理地址，如 http://127.0.0.1:1080")
    p_dl.add_argument("extra", nargs=argparse.REMAINDER,
                       help="额外传给 yt-dlp 的参数（用 -- 分隔）")

    args = parser.parse_args()

    if args.command == "fetch":
        cmd_fetch(args)
    elif args.command == "download":
        cmd_download(args)


if __name__ == "__main__":
    main()
