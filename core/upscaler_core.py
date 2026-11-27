import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Optional

VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
MEDIA_EXTENSIONS = VIDEO_EXTENSIONS | IMAGE_EXTENSIONS

FFMPEG_DOWNLOAD_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
REALESRGAN_DOWNLOAD_URL = (
    "https://github.com/xinntao/Real-ESRGAN/releases/download/"
    "v0.2.5.0/realesrgan-ncnn-vulkan-20220424-windows.zip"
)


@dataclass
class UpscaleConfig:
    mode: str = "fast"  # "fast" | "ai"
    ai_model: str = "realesrgan-x4plus"  # realesrgan-x4plus | realesr-animevideov3 | realesrgan-x4plus-anime
    target_short_side: int = 1080
    crf: int = 18  # 18 = Kualitas Tinggi, 21 = Seimbang
    tile_size: int = 0  # 0 = Auto, 128/200 = Hemat VRAM (anti-crash)
    skip_existing: bool = True
    delete_source: bool = False
    output_mode: str = "same_suffix"  # "same_suffix" | "overwrite" | "custom_folder"
    output_dir: str = ""
    watch_folder: str = ""


def get_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def is_file_ready(path: Path, wait_seconds: float = 1.2) -> bool:
    """Return True if file exists, is non-empty, and size is stable (finished downloading)."""
    try:
        if not path.is_file():
            return False
        size1 = path.stat().st_size
        if size1 == 0:
            return False
        time.sleep(wait_seconds)
        if not path.is_file():
            return False
        size2 = path.stat().st_size
        return size1 == size2
    except OSError:
        return False


def get_bin_dir() -> Path:
    return get_app_dir() / "bin"


def get_settings_path() -> Path:
    return get_app_dir() / "settings.json"


def load_settings() -> UpscaleConfig:
    path = get_settings_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            valid_fields = {f for f in UpscaleConfig.__dataclass_fields__}
            filtered = {k: v for k, v in data.items() if k in valid_fields}
            return UpscaleConfig(**filtered)
        except Exception:
            pass
    return UpscaleConfig()


def save_settings(config: UpscaleConfig) -> None:
    try:
        get_settings_path().write_text(
            json.dumps(asdict(config), indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def detect_gpu_name() -> str:
    """Detect primary GPU name on Windows for user guidance."""
    if os.name != "nt":
        return "Unknown GPU"
    try:
        res = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name) -join ', '",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        name = (res.stdout or "").strip()
        return name if name else "Tidak terdeteksi"
    except Exception:
        return "Tidak terdeteksi"


def find_executable(name: str, extra_subpaths: tuple[str, ...] = ()) -> Optional[Path]:
    """Find an executable in local bin/ directory or system PATH."""
    bin_dir = get_bin_dir()
    candidates = [bin_dir / name]
    for sub in extra_subpaths:
        candidates.append(bin_dir / sub)

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    found = shutil.which(name)
    if found:
        return Path(found)
    return None


def get_tool_paths() -> dict[str, Optional[Path]]:
    return {
        "ffmpeg": find_executable("ffmpeg.exe", ("ffmpeg/bin/ffmpeg.exe",)),
        "ffprobe": find_executable("ffprobe.exe", ("ffmpeg/bin/ffprobe.exe",)),
        "realesrgan": find_executable(
            "realesrgan-ncnn-vulkan.exe",
            ("realesrgan/realesrgan-ncnn-vulkan.exe",),
        ),
    }


def _download_file(
    url: str,
    dest: Path,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "VideoUpscalerApp/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        downloaded = 0
        chunk_size = 256 * 1024
        last_pct = -1
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0 and progress_cb:
                    pct = int(downloaded * 100 / total)
                    if pct >= last_pct + 5 or pct == 100:
                        last_pct = pct
                        mb_done = downloaded / (1024 * 1024)
                        mb_total = total / (1024 * 1024)
                        progress_cb(f"Mengunduh... {pct}% ({mb_done:.1f}/{mb_total:.1f} MB)")


def install_ffmpeg(progress_cb: Optional[Callable[[str], None]] = None) -> Path:
    bin_dir = get_bin_dir()
    ffmpeg_dir = bin_dir / "ffmpeg"
    ffmpeg_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "ffmpeg.zip"
        if progress_cb:
            progress_cb("Mengunduh FFmpeg portable...")
        _download_file(FFMPEG_DOWNLOAD_URL, zip_path, progress_cb)

        if progress_cb:
            progress_cb("Mengekstrak FFmpeg...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.namelist():
                lower = member.lower()
                if lower.endswith("/bin/ffmpeg.exe") or lower.endswith("/bin/ffprobe.exe"):
                    target_name = Path(member).name
                    out_bin = ffmpeg_dir / "bin"
                    out_bin.mkdir(parents=True, exist_ok=True)
                    with zf.open(member) as src, open(out_bin / target_name, "wb") as dst:
                        shutil.copyfileobj(src, dst)

    exe = ffmpeg_dir / "bin" / "ffmpeg.exe"
    if not exe.is_file():
        raise RuntimeError("Gagal menemukan ffmpeg.exe setelah ekstrak.")
    return exe


def install_realesrgan(progress_cb: Optional[Callable[[str], None]] = None) -> Path:
    bin_dir = get_bin_dir()
    esrgan_dir = bin_dir / "realesrgan"
    esrgan_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "realesrgan.zip"
        if progress_cb:
            progress_cb("Mengunduh Real-ESRGAN AI portable...")
        _download_file(REALESRGAN_DOWNLOAD_URL, zip_path, progress_cb)

        if progress_cb:
            progress_cb("Mengekstrak Real-ESRGAN AI...")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(esrgan_dir)

    exe = esrgan_dir / "realesrgan-ncnn-vulkan.exe"
    if not exe.is_file():
        for found in esrgan_dir.rglob("realesrgan-ncnn-vulkan.exe"):
            parent = found.parent
            if parent != esrgan_dir:
                for item in parent.iterdir():
                    dest = esrgan_dir / item.name
                    if dest.exists():
                        if dest.is_dir():
                            shutil.rmtree(dest)
                        else:
                            dest.unlink()
                    shutil.move(str(item), str(dest))
            break

    if not exe.is_file():
        raise RuntimeError("Gagal menemukan realesrgan-ncnn-vulkan.exe setelah ekstrak.")
    return exe


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTENSIONS


def collect_videos(
    folder: Path, ignore_upscaled: bool = True, media_filter: str = "all"
) -> list[Path]:
    if not folder.is_dir():
        return []
    if media_filter == "video":
        allowed = VIDEO_EXTENSIONS
    elif media_filter == "image":
        allowed = IMAGE_EXTENSIONS
    else:
        allowed = MEDIA_EXTENSIONS

    result = []
    for p in sorted(folder.iterdir()):
        if not p.is_file() or p.suffix.lower() not in allowed:
            continue
        if ignore_upscaled and p.stem.endswith("_1080p"):
            continue
        result.append(p)
    return result


def probe_video_info(ffprobe_path: Path, video_path: Path) -> dict:
    cmd = [
        str(ffprobe_path),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,nb_frames",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(video_path),
    ]
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=True,
        creationflags=creationflags,
    )
    data = json.loads(res.stdout or "{}")
    stream = (data.get("streams") or [{}])[0]
    fmt = data.get("format") or {}

    fps_str = stream.get("r_frame_rate", "30/1")
    if "/" in fps_str:
        num, den = fps_str.split("/", 1)
        fps = float(num) / float(den) if float(den) != 0 else 30.0
    else:
        fps = float(fps_str) if fps_str else 30.0

    duration = float(fmt.get("duration") or 0.0)
    nb_frames = int(stream.get("nb_frames") or 0)
    if nb_frames == 0 and duration > 0:
        nb_frames = max(1, int(round(duration * fps)))

    return {
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "fps": fps,
        "fps_str": fps_str,
        "duration": duration,
        "nb_frames": nb_frames,
    }


def build_scale_filter(short_side: int) -> str:
    """Scale preserving aspect ratio so the shorter side equals short_side (even dims)."""
    return (
        f"scale='if(gte(iw,ih),-2,{short_side})':"
        f"'if(gte(iw,ih),{short_side},-2)':flags=lanczos"
    )


def _run_cancellable(
    cmd: list[str],
    cancel_check: Optional[Callable[[], bool]] = None,
    line_cb: Optional[Callable[[str], None]] = None,
    cwd: Optional[Path] = None,
) -> None:
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd) if cwd else None,
        creationflags=creationflags,
    )
    output_tail: list[str] = []
    try:
        assert proc.stdout is not None
        while True:
            if cancel_check and cancel_check():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise InterruptedError("Proses dibatalkan oleh pengguna.")

            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                continue
            cleaned = line.strip()
            if cleaned:
                output_tail.append(cleaned)
                if len(output_tail) > 20:
                    output_tail.pop(0)
                if line_cb:
                    line_cb(cleaned)

        rc = proc.wait()
        if rc != 0:
            tail_text = "\n".join(output_tail[-5:])
            raise RuntimeError(f"Perintah gagal (kode {rc}):\n{tail_text}")
    except Exception:
        if proc.poll() is None:
            proc.kill()
        raise


def upscale_video_fast(
    ffmpeg_path: Path,
    ffprobe_path: Optional[Path],
    input_path: Path,
    output_path: Path,
    config: UpscaleConfig,
    status_cb: Optional[Callable[[str], None]] = None,
    progress_cb: Optional[Callable[[float], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = 0.0
    if ffprobe_path and ffprobe_path.is_file():
        try:
            info = probe_video_info(ffprobe_path, input_path)
            duration = info["duration"]
        except Exception:
            duration = 0.0

    vf = (
        f"hqdn3d=1.5:1.5:4:4,"
        f"{build_scale_filter(config.target_short_side)},"
        f"unsharp=5:5:0.75:3:3:0.3"
    )
    cmd = [
        str(ffmpeg_path),
        "-y",
        "-i",
        str(input_path),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-crf",
        str(config.crf),
        "-preset",
        "medium",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]

    if status_cb:
        status_cb(f"Memproses (Mode Cepat): {input_path.name}")

    time_re = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")

    def on_line(line: str) -> None:
        if duration > 0 and progress_cb:
            m = time_re.search(line)
            if m:
                h, mins, secs = float(m.group(1)), float(m.group(2)), float(m.group(3))
                cur = h * 3600 + mins * 60 + secs
                progress_cb(min(100.0, (cur / duration) * 100.0))

    _run_cancellable(cmd, cancel_check=cancel_check, line_cb=on_line)
    if progress_cb:
        progress_cb(100.0)


def upscale_video_ai(
    ffmpeg_path: Path,
    ffprobe_path: Optional[Path],
    realesrgan_path: Path,
    input_path: Path,
    output_path: Path,
    config: UpscaleConfig,
    status_cb: Optional[Callable[[str], None]] = None,
    progress_cb: Optional[Callable[[float], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fps_str = "30"
    if ffprobe_path and ffprobe_path.is_file():
        try:
            info = probe_video_info(ffprobe_path, input_path)
            fps_str = info["fps_str"] or "30"
        except Exception:
            pass

    with tempfile.TemporaryDirectory(prefix="upscale_ai_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        frames_in = tmp_path / "in"
        frames_out = tmp_path / "out"
        frames_in.mkdir()
        frames_out.mkdir()

        if status_cb:
            status_cb(f"[1/3] Mengekstrak frame (CFR sync): {input_path.name}")
        if progress_cb:
            progress_cb(5.0)

        # Force constant frame rate (CFR) during extraction to prevent audio desync
        extract_cmd = [
            str(ffmpeg_path),
            "-y",
            "-i",
            str(input_path),
            "-fps_mode",
            "cfr",
            "-qscale:v",
            "2",
            str(frames_in / "frame_%08d.png"),
        ]
        _run_cancellable(extract_cmd, cancel_check=cancel_check)

        extracted_count = len(list(frames_in.glob("*.png")))
        if extracted_count == 0:
            raise RuntimeError(f"Tidak ada frame yang berhasil diekstrak dari {input_path.name}")

        if status_cb:
            status_cb(f"[2/3] AI Upscaling ({extracted_count} frame): {input_path.name}")

        pct_re = re.compile(r"(\d+(?:\.\d+)?)%")

        def on_ai_line(line: str) -> None:
            m = pct_re.search(line)
            if m and progress_cb:
                ai_pct = float(m.group(1))
                progress_cb(10.0 + (ai_pct * 0.75))

        ai_cmd = [
            str(realesrgan_path),
            "-i",
            str(frames_in),
            "-o",
            str(frames_out),
            "-n",
            config.ai_model,
            "-s",
            "4",
            "-f",
            "png",
        ]
        if config.tile_size > 0:
            ai_cmd.extend(["-t", str(config.tile_size)])

        _run_cancellable(
            ai_cmd,
            cancel_check=cancel_check,
            line_cb=on_ai_line,
            cwd=realesrgan_path.parent,
        )

        if status_cb:
            status_cb(f"[3/3] Menggabungkan video 1080p + audio: {input_path.name}")
        if progress_cb:
            progress_cb(88.0)

        encode_cmd = [
            str(ffmpeg_path),
            "-y",
            "-framerate",
            fps_str,
            "-i",
            str(frames_out / "frame_%08d.png"),
            "-i",
            str(input_path),
            "-map",
            "0:v:0",
            "-map",
            "1:a?",
            "-vf",
            build_scale_filter(config.target_short_side),
            "-c:v",
            "libx264",
            "-crf",
            str(config.crf),
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        _run_cancellable(encode_cmd, cancel_check=cancel_check)
        if progress_cb:
            progress_cb(100.0)


def upscale_image_fast(
    ffmpeg_path: Path,
    input_path: Path,
    output_path: Path,
    config: UpscaleConfig,
    status_cb: Optional[Callable[[str], None]] = None,
    progress_cb: Optional[Callable[[float], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if status_cb:
        status_cb(f"Memproses Foto (Mode Cepat): {input_path.name}")
    if progress_cb:
        progress_cb(30.0)

    vf = f"{build_scale_filter(config.target_short_side)},unsharp=5:5:0.75:3:3:0.3"
    cmd = [
        str(ffmpeg_path),
        "-y",
        "-i",
        str(input_path),
        "-vf",
        vf,
        str(output_path),
    ]
    _run_cancellable(cmd, cancel_check=cancel_check)
    if progress_cb:
        progress_cb(100.0)


def upscale_image_ai(
    realesrgan_path: Path,
    input_path: Path,
    output_path: Path,
    config: UpscaleConfig,
    status_cb: Optional[Callable[[str], None]] = None,
    progress_cb: Optional[Callable[[float], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if status_cb:
        status_cb(f"AI Upscaling Foto: {input_path.name}")
    if progress_cb:
        progress_cb(15.0)

    ext = output_path.suffix.lower().lstrip(".")
    fmt = ext if ext in ("png", "jpg", "webp") else "png"
    cmd = [
        str(realesrgan_path),
        "-i",
        str(input_path),
        "-o",
        str(output_path),
        "-n",
        config.ai_model,
        "-s",
        "4",
        "-f",
        fmt,
    ]
    if config.tile_size > 0:
        cmd.extend(["-t", str(config.tile_size)])

    pct_re = re.compile(r"(\d+(?:\.\d+)?)%")

    def on_line(line: str) -> None:
        m = pct_re.search(line)
        if m and progress_cb:
            progress_cb(min(99.0, 15.0 + float(m.group(1)) * 0.85))

    _run_cancellable(
        cmd,
        cancel_check=cancel_check,
        line_cb=on_line,
        cwd=realesrgan_path.parent,
    )
    if progress_cb:
        progress_cb(100.0)
