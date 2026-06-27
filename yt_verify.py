"""
媒体文件通用校验工具

校验指定目录下的音频/视频文件：
1. 文件存在性、可解析性（ffmpeg 能读元数据）
2. 容器格式（mp3/mp4/m4a/webm 等）
3. 编码格式（mp3/aac/h264/h265/av01 等）
4. 流信息（音频流、视频流是否存在）
5. 时长是否合理（可配阈值）
6. 完整性校验（可选 --decode 全量解码验证每一帧完好）

用法示例：
  # 校验目录下所有 mp3
  python yt_verify.py verify -d "D:\\downloads\\audio" -e mp3

  # 校验所有 mp4 并全量解码
  python yt_verify.py verify -d "D:\\downloads\\video" -e mp4 --decode

  # 校验多种格式
  python yt_verify.py verify -d "D:\\downloads" -e mp3,mp4,m4a

  # 检查单个文件
  python yt_verify.py check -f "video.mp4"
"""
import argparse
import os
import re
import sys
import subprocess
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
import imageio_ffmpeg

FFMPEG_PATH = imageio_ffmpeg.get_ffmpeg_exe()


def probe_file(filepath):
    """
    用 ffmpeg -i 探测文件元信息。
    返回 dict: {
        ok: bool,                # 是否成功解析
        container: str,         # 容器格式（mp3/mp4/mov 等）
        duration_sec: float,    # 时长（秒）
        bitrate: int,           # 总比特率（kbps）
        streams: [{type, codec, ...}],  # 流信息
        has_audio: bool,
        has_video: bool,
        error: str,
    }
    """
    result = {
        "ok": False, "container": "", "duration_sec": None, "bitrate": None,
        "streams": [], "has_audio": False, "has_video": False, "error": "",
    }
    if not os.path.exists(filepath):
        result["error"] = "文件不存在"
        return result
    if os.path.getsize(filepath) == 0:
        result["error"] = "文件为空"
        return result

    try:
        r = subprocess.run([FFMPEG_PATH, "-i", filepath], capture_output=True, text=True,
                            timeout=60, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        result["error"] = "ffmpeg 探测超时"
        return result
    except Exception as e:
        result["error"] = f"运行异常: {e}"
        return result

    stderr = r.stderr or ""

    # 容器格式：Input #0, mp3, from '...'
    m_container = re.search(r"Input #0, (\w+),", stderr)
    if m_container:
        result["container"] = m_container.group(1)
    else:
        result["error"] = "无法解析容器格式"
        return result

    # 时长：Duration: 00:52:43.54
    m_dur = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
    if m_dur:
        h, mi, s = int(m_dur.group(1)), int(m_dur.group(2)), float(m_dur.group(3))
        result["duration_sec"] = h * 3600 + mi * 60 + s

    # 比特率：bitrate: 235 kb/s
    m_br = re.search(r"bitrate:\s*(\d+)\s*kb/s", stderr)
    if m_br:
        result["bitrate"] = int(m_br.group(1))

    # 流信息，按行扫描（避免跨行匹配）
    # mp3:  Stream #0:0: Audio: mp3 (mp3float), 48000 Hz, stereo, fltp, 196 kb/s
    # mp4:  Stream #0:0[0x1](und): Video: h264 (Main) (avc1 / 0x31637661), yuv420p, 1280x720, 60 fps
    # mkv:  Stream #0:1: Audio: aac (LC), 48000 Hz, stereo, fltp
    for line in stderr.splitlines():
        m = re.match(r"\s*Stream #\d+:\d+(?:\[[^\]]*\])?(?:\([^)]*\))?: (\w+): (.+)", line)
        if m:
            stream_type = m.group(1).lower()  # audio / video / subtitle / data
            rest = m.group(2).strip()
            # 第一个字段通常是编码（到第一个逗号前）
            codec = rest.split(",")[0].strip()
            stream_info = {"type": stream_type, "codec": codec, "detail": rest}
            result["streams"].append(stream_info)
            if stream_type == "audio":
                result["has_audio"] = True
            elif stream_type == "video":
                result["has_video"] = True

    # 检查错误
    has_error = any(e in stderr for e in [
        "Invalid data found", "Error while decoding", "moov atom not found",
        "corrupt", "truncated", "header missing",
    ])

    result["ok"] = result["duration_sec"] is not None and not has_error
    if has_error:
        result["error"] = "解码过程有错误"
    elif not result["ok"]:
        result["error"] = "无法获取时长"
    return result


def decode_verify(filepath, timeout=900):
    """
    全量解码文件验证完整性。
    返回 (ok, actual_duration_sec, error)
    """
    if not os.path.exists(filepath):
        return False, None, "文件不存在"
    try:
        r = subprocess.run(
            [FFMPEG_PATH, "-i", filepath, "-f", "null", "-"],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace"
        )
    except subprocess.TimeoutExpired:
        return False, None, f"解码超时（>{timeout//60}分钟）"
    except Exception as e:
        return False, None, f"运行异常: {e}"

    stderr = r.stderr or ""
    times = re.findall(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
    actual_dur = None
    if times:
        last = times[-1]
        actual_dur = int(last[0]) * 3600 + int(last[1]) * 60 + float(last[2])

    has_error = any(e in stderr for e in [
        "Invalid data found", "Error while decoding", "moov atom not found",
        "corrupt", "truncated",
    ])

    if actual_dur is None:
        return False, None, "无法获取实际解码时长"
    if has_error:
        return False, actual_dur, "解码过程有错误"
    return True, actual_dur, ""


def format_duration(sec):
    if sec is None:
        return "N/A"
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = int(sec % 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_streams(info):
    """把流信息格式化成简短字符串"""
    parts = []
    for s in info["streams"]:
        if s["type"] == "video":
            # 编码只取第一个词（h264 / vp9 / av1 等）
            codec = s["codec"].split()[0].split("(")[0].strip()
            # 提取分辨率（1280x720 格式，要求前面是逗号或行首，避免误匹配 0x31637661）
            res = re.search(r"(?:^|,\s*)(\d{2,4}x\d{2,4})(?:\s|$|\[)", s["detail"])
            res_str = res.group(1) if res else ""
            parts.append(f"视频:{codec}({res_str})" if res_str else f"视频:{codec}")
        elif s["type"] == "audio":
            codec = s["codec"].split()[0].split("(")[0].strip()
            # 提取采样率和声道
            sr = re.search(r"(\d+)\s*Hz", s["detail"])
            sr_str = sr.group(1) + "Hz" if sr else ""
            ch = re.search(r", (mono|stereo|\d+\.\d+)", s["detail"])
            ch_str = ch.group(1) if ch else ""
            info_str = " ".join(filter(None, [sr_str, ch_str]))
            parts.append(f"音频:{codec}({info_str})" if info_str else f"音频:{codec}")
    return " + ".join(parts) if parts else "无流"


# ============================================================
# check 子命令：检查单个文件
# ============================================================

def cmd_check(args):
    filepath = args.file
    print(f"文件: {filepath}")
    print(f"大小: {os.path.getsize(filepath):,} bytes ({os.path.getsize(filepath)/1024/1024:.1f} MB)")
    print()

    info = probe_file(filepath)
    if not info["ok"]:
        print(f"结论: 损坏 - {info['error']}")
        sys.exit(1)

    print(f"容器格式: {info['container']}")
    dur_sec = info['duration_sec']
    dur_str = f"{dur_sec/60:.1f} 分钟" if dur_sec else "N/A"
    print(f"时长: {format_duration(dur_sec)} ({dur_str})")
    print(f"比特率: {info['bitrate']} kb/s" if info["bitrate"] else "比特率: N/A")
    print(f"流: {format_streams(info)}")
    print()

    if args.decode:
        print("全量解码校验中...")
        ok, actual_dur, err = decode_verify(filepath)
        if ok:
            print(f"解码完成: 实际时长 {format_duration(actual_dur)}")
            diff = abs(actual_dur - info["duration_sec"]) if info["duration_sec"] else 0
            if diff > 5:
                print(f"警告: 实际时长与元数据差异 {diff:.1f} 秒")
            else:
                print("结论: 完整无损")
        else:
            print(f"结论: 损坏 - {err}")
            sys.exit(1)
    else:
        print("结论: 元数据正常（如需完整解码校验，加 --decode）")


# ============================================================
# verify 子命令：批量校验目录
# ============================================================

def cmd_verify(args):
    directory = args.directory
    extensions = [e.lower().lstrip(".") for e in args.extensions.split(",")]
    do_decode = args.decode
    parallel = args.parallel

    if not os.path.isdir(directory):
        print(f"错误: 目录不存在: {directory}", file=sys.stderr)
        sys.exit(1)

    # 收集所有匹配的文件
    all_files = []
    for name in sorted(os.listdir(directory)):
        ext = os.path.splitext(name)[1].lower().lstrip(".")
        if ext in extensions:
            all_files.append(os.path.join(directory, name))

    if not all_files:
        print(f"目录 {directory} 下未找到 {args.extensions} 文件")
        return

    print(f"[verify] 共 {len(all_files)} 个文件，并发 {parallel}", flush=True)
    if do_decode:
        print(f"[verify] 启用全量解码校验（较慢）", flush=True)
    print()

    results = []
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {pool.submit(_verify_one, fp, do_decode): fp for fp in all_files}
        done = 0
        for fut in as_completed(futures):
            fp = futures[fut]
            try:
                result = fut.result()
            except Exception as e:
                result = {"filepath": fp, "status": "ERROR", "error": str(e)}
            results.append(result)
            done += 1
            name = os.path.basename(fp)
            status = result["status"]
            print(f"[{done}/{len(all_files)}] {status:<8} {name}", flush=True)

    # 排序输出（按文件名）
    results.sort(key=lambda r: os.path.basename(r["filepath"]))

    # 汇总
    print()
    print("=" * 80)
    ok_count = sum(1 for r in results if r["status"] == "OK")
    broken_count = sum(1 for r in results if r["status"] == "BROKEN")
    error_count = sum(1 for r in results if r["status"] == "ERROR")
    print(f"完整 (OK): {ok_count}")
    print(f"损坏 (BROKEN): {broken_count}")
    print(f"错误 (ERROR): {error_count}")
    print()

    # 明细表
    print(f"{'文件名':<50}{'容器':<8}{'时长':<12}{'流信息'}")
    print("-" * 100)
    for r in results:
        name = os.path.basename(r["filepath"])
        if r["status"] == "OK":
            info = r["info"]
            dur = format_duration(info["duration_sec"])
            streams = format_streams(info)
            print(f"{name:<50}{info['container']:<8}{dur:<12}{streams}")
        else:
            print(f"{name:<50}{r['status']:<8}{r.get('error', '')}")

    # 写报告
    if args.report:
        with open(args.report, "w", encoding="utf-8") as f:
            f.write(f"媒体文件校验报告\n")
            f.write(f"目录: {directory}\n")
            f.write(f"扩展名: {args.extensions}\n")
            f.write(f"全量解码: {'是' if do_decode else '否'}\n")
            f.write(f"文件数: {len(results)}\n")
            f.write(f"完整: {ok_count}, 损坏: {broken_count}, 错误: {error_count}\n")
            f.write("=" * 100 + "\n\n")
            for r in results:
                name = os.path.basename(r["filepath"])
                if r["status"] == "OK":
                    info = r["info"]
                    f.write(f"{name}\n")
                    f.write(f"  容器: {info['container']}, 时长: {format_duration(info['duration_sec'])}, "
                            f"比特率: {info['bitrate']} kb/s\n")
                    f.write(f"  流: {format_streams(info)}\n")
                    if do_decode and r.get("actual_duration"):
                        f.write(f"  实际解码时长: {format_duration(r['actual_duration'])}\n")
                    f.write("\n")
                else:
                    f.write(f"{name}: {r['status']} - {r.get('error', '')}\n\n")
        print(f"\n报告已写入: {args.report}")


def _verify_one(filepath, do_decode):
    """校验单个文件。返回 result dict"""
    info = probe_file(filepath)
    if not info["ok"]:
        return {"filepath": filepath, "status": "BROKEN", "error": info["error"], "info": info}

    if do_decode:
        ok, actual_dur, err = decode_verify(filepath)
        if not ok:
            return {"filepath": filepath, "status": "BROKEN", "error": err, "info": info,
                    "actual_duration": actual_dur}
        return {"filepath": filepath, "status": "OK", "info": info, "actual_duration": actual_dur}

    return {"filepath": filepath, "status": "OK", "info": info}


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="媒体文件通用校验工具（音频/视频）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  # 校验目录下所有 mp3
  python yt_verify.py verify -d "D:\\downloads\\audio" -e mp3

  # 校验所有 mp4 并全量解码
  python yt_verify.py verify -d "D:\\downloads\\video" -e mp4 --decode

  # 检查单个文件（含全量解码）
  python yt_verify.py check -f "video.mp4" --decode
""",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # check 子命令
    p_check = sub.add_parser("check", help="检查单个文件")
    p_check.add_argument("-f", "--file", required=True, help="文件路径")
    p_check.add_argument("--decode", action="store_true", help="全量解码校验（验证每一帧完好）")

    # verify 子命令
    p_verify = sub.add_parser("verify", help="批量校验目录下的文件")
    p_verify.add_argument("-d", "--directory", required=True, help="目录路径")
    p_verify.add_argument("-e", "--extensions", default="mp3,mp4,m4a,webm,mkv,mov,flac,wav",
                           help="文件扩展名，逗号分隔（默认 mp3,mp4,m4a,webm,mkv,mov,flac,wav）")
    p_verify.add_argument("--decode", action="store_true", help="全量解码校验（较慢但最可靠）")
    p_verify.add_argument("-p", "--parallel", type=int, default=4, help="并发数（默认 4）")
    p_verify.add_argument("--report", help="报告输出路径（可选）")

    args = parser.parse_args()

    if args.command == "check":
        cmd_check(args)
    elif args.command == "verify":
        cmd_verify(args)


if __name__ == "__main__":
    main()
