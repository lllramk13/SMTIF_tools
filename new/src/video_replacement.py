import hashlib
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


NEW_DIRECTORY = Path(__file__).resolve().parent.parent
PROJECT_DIRECTORY = NEW_DIRECTORY.parent
DEFAULT_VIDEO_DIRECTORY = PROJECT_DIRECTORY / "MP4_Subtitle"
DEFAULT_OUTPUT_DIRECTORY = NEW_DIRECTORY / "build" / "subtitle_videos"
DEFAULT_JPSXDEC_JAR = (
    PROJECT_DIRECTORY.parent
    / "tools"
    / "jpsxdec_v2.1-beta"
    / "jpsxdec.jar"
)
ORIGINAL_DATA_DIRECTORY = PROJECT_DIRECTORY / "extrac" / "D"

VIDEO_NAME_RE = re.compile(r"^(F\d{4})(?:\.[^.]+)*\.avi$", re.IGNORECASE)
INDEX_INFO_RE = re.compile(
    r"Dimensions:(?P<width>\d+)x(?P<height>\d+).*?"
    r"Frame Count:(?P<frames>\d+)",
    re.DOTALL,
)
CACHE_VERSION = 1


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _tool_path(value, name):
    if value is None:
        found = shutil.which(name)
        if found is None:
            raise FileNotFoundError(f"Required tool is not on PATH: {name}")
        return Path(found)
    path = Path(value).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Required tool does not exist: {path}")
    return path


def discover_subtitle_videos(video_directory=DEFAULT_VIDEO_DIRECTORY):
    video_directory = Path(video_directory).resolve()
    if not video_directory.is_dir():
        raise FileNotFoundError(f"Subtitle-video directory not found: {video_directory}")

    videos = {}
    for path in sorted(video_directory.iterdir()):
        if not path.is_file():
            continue
        match = VIDEO_NAME_RE.match(path.name)
        if match is None:
            continue
        video_id = match.group(1).upper()
        if video_id in videos:
            raise ValueError(f"Multiple AVI files map to {video_id}: {videos[video_id]}, {path}")
        videos[video_id] = path

    if not videos:
        raise ValueError(f"No Fxxxx*.AVI subtitle videos found in {video_directory}")
    return videos


def _probe_avi(avi_path, ffprobe_path):
    command = [
        str(ffprobe_path),
        "-v", "error",
        "-count_frames",
        "-show_streams",
        "-show_format",
        "-of", "json",
        str(avi_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {avi_path}:\n{result.stderr}")
    data = json.loads(result.stdout)
    video_streams = [
        stream for stream in data.get("streams", ())
        if stream.get("codec_type") == "video"
    ]
    if len(video_streams) != 1:
        raise ValueError(f"Expected exactly one video stream in {avi_path}")
    stream = video_streams[0]
    frame_value = stream.get("nb_read_frames") or stream.get("nb_frames")
    if not frame_value or frame_value == "N/A":
        raise ValueError(f"ffprobe did not report a frame count for {avi_path}")
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "frames": int(frame_value),
        "frame_rate": stream.get("avg_frame_rate"),
        "audio_streams": sum(
            stream.get("codec_type") == "audio"
            for stream in data.get("streams", ())
        ),
    }


def _run_jpsxdec(arguments, jpsxdec_jar, cwd):
    command = [
        "java",
        "-Xms32m",
        "-Xmx256m",
        "-jar",
        str(jpsxdec_jar),
        *map(str, arguments),
    ]
    result = subprocess.run(command, cwd=cwd, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"jPSXdec failed with exit code {result.returncode}: "
            + " ".join(command)
        )


def _build_index(source_path, index_path, jpsxdec_jar, cwd):
    index_path.unlink(missing_ok=True)
    _run_jpsxdec(
        ("-f", source_path, "-x", index_path),
        jpsxdec_jar,
        cwd,
    )
    if not index_path.is_file():
        raise FileNotFoundError(f"jPSXdec did not create index: {index_path}")
    text = index_path.read_text(encoding="utf-8")
    match = INDEX_INFO_RE.search(text)
    if match is None:
        raise ValueError(f"Could not parse video metadata from {index_path}")
    if "Sector size:2048" not in text or "Type:Video" not in text:
        raise ValueError(f"Unsupported original video container: {source_path}")
    return {key: int(value) for key, value in match.groupdict().items()}


def _extract_frames(avi_path, frames_directory, ffmpeg_path):
    if frames_directory.exists():
        shutil.rmtree(frames_directory)
    frames_directory.mkdir(parents=True)
    pattern = frames_directory / "frame-%06d.png"
    command = [
        str(ffmpeg_path),
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(avi_path),
        "-map", "0:v:0",
        "-fps_mode", "passthrough",
        "-start_number", "0",
        "-compression_level", "1",
        str(pattern),
    ]
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg frame extraction failed for {avi_path}")
    return sorted(frames_directory.glob("frame-*.png"))


def _write_replacement_xml(xml_path, frame_paths):
    root = ET.Element("str-replace", {"version": "0.3"})
    for frame_number, frame_path in enumerate(frame_paths):
        element = ET.SubElement(root, "replace", {"frame": str(frame_number)})
        element.text = str(frame_path.resolve())
    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(xml_path, encoding="utf-8", xml_declaration=True)


def _cache_matches(cache_path, output_path, expected):
    if not cache_path.is_file() or not output_path.is_file():
        return False
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if any(cached.get(key) != value for key, value in expected.items()):
        return False
    if output_path.stat().st_size != cached.get("output_size"):
        return False
    return _sha256(output_path) == cached.get("output_sha256")


def prepare_subtitle_video(
    video_id,
    avi_path,
    output_directory=DEFAULT_OUTPUT_DIRECTORY,
    jpsxdec_jar=DEFAULT_JPSXDEC_JAR,
    ffmpeg_path=None,
    ffprobe_path=None,
    force=False,
):
    video_id = video_id.upper()
    avi_path = Path(avi_path).resolve()
    output_directory = Path(output_directory).resolve()
    jpsxdec_jar = Path(jpsxdec_jar).resolve()
    ffmpeg_path = _tool_path(ffmpeg_path, "ffmpeg")
    ffprobe_path = _tool_path(ffprobe_path, "ffprobe")
    if not jpsxdec_jar.is_file():
        raise FileNotFoundError(f"jPSXdec JAR not found: {jpsxdec_jar}")

    original_path = ORIGINAL_DATA_DIRECTORY / f"{video_id}.BIN"
    if not original_path.is_file():
        raise FileNotFoundError(f"Original video container not found: {original_path}")

    output_directory.mkdir(parents=True, exist_ok=True)
    output_path = output_directory / f"{video_id}.BIN"
    cache_path = output_directory / f"{video_id}.cache.json"
    work_directory = output_directory / f".{video_id}.work"
    index_path = work_directory / f"{video_id}.idx"

    avi_info = _probe_avi(avi_path, ffprobe_path)
    if avi_info["frame_rate"] != "15/1":
        raise ValueError(
            f"{video_id}: expected a 15 fps AVI, got {avi_info['frame_rate']}"
        )
    if avi_info["audio_streams"]:
        raise ValueError(
            f"{video_id}: AVI audio cannot be injected by frame replacement; "
            "provide a video-only AVI"
        )
    work_directory.mkdir(parents=True, exist_ok=True)
    original_info = _build_index(original_path, index_path, jpsxdec_jar, PROJECT_DIRECTORY)
    for field in ("width", "height", "frames"):
        if avi_info[field] != original_info[field]:
            raise ValueError(
                f"{video_id}: AVI {field}={avi_info[field]} does not match "
                f"original {field}={original_info[field]}"
            )

    expected_cache = {
        "cache_version": CACHE_VERSION,
        "video_id": video_id,
        "avi_sha256": _sha256(avi_path),
        "original_sha256": _sha256(original_path),
        "jpsxdec_sha256": _sha256(jpsxdec_jar),
        "width": avi_info["width"],
        "height": avi_info["height"],
        "frames": avi_info["frames"],
    }
    if not force and _cache_matches(cache_path, output_path, expected_cache):
        print(f"Subtitle video cache hit: {video_id} ({avi_info['frames']} frames)")
        return output_path

    print(
        f"Preparing {video_id}: {avi_info['width']}x{avi_info['height']}, "
        f"{avi_info['frames']} frames"
    )
    frames_directory = work_directory / "frames"
    frame_paths = _extract_frames(avi_path, frames_directory, ffmpeg_path)
    if len(frame_paths) != avi_info["frames"]:
        raise ValueError(
            f"{video_id}: ffmpeg extracted {len(frame_paths)} frames; "
            f"expected {avi_info['frames']}"
        )

    xml_path = work_directory / f"{video_id}-replace.xml"
    _write_replacement_xml(xml_path, frame_paths)
    temporary_output = work_directory / f"{video_id}.BIN.tmp"
    shutil.copyfile(original_path, temporary_output)
    try:
        _run_jpsxdec(
            (
                "-x", index_path,
                "-f", temporary_output,
                "-i", "0",
                "-replaceframes", xml_path,
            ),
            jpsxdec_jar,
            PROJECT_DIRECTORY,
        )
        if temporary_output.stat().st_size != original_path.stat().st_size:
            raise AssertionError(f"{video_id}: replacement changed container size")
        if _sha256(temporary_output) == expected_cache["original_sha256"]:
            raise AssertionError(f"{video_id}: all-frame replacement changed no bytes")
        verified_info = _build_index(
            temporary_output,
            work_directory / f"{video_id}-verify.idx",
            jpsxdec_jar,
            PROJECT_DIRECTORY,
        )
        if verified_info != original_info:
            raise AssertionError(
                f"{video_id}: replaced container metadata changed: "
                f"{original_info} -> {verified_info}"
            )
        temporary_output.replace(output_path)
    finally:
        temporary_output.unlink(missing_ok=True)
        if frames_directory.is_dir():
            shutil.rmtree(frames_directory)

    cache_data = dict(expected_cache)
    cache_data.update({
        "avi_path": str(avi_path),
        "original_path": str(original_path),
        "output_size": output_path.stat().st_size,
        "output_sha256": _sha256(output_path),
    })
    cache_path.write_text(
        json.dumps(cache_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Prepared subtitle video: {output_path}")
    return output_path


def prepare_subtitle_videos(
    video_directory=DEFAULT_VIDEO_DIRECTORY,
    output_directory=DEFAULT_OUTPUT_DIRECTORY,
    jpsxdec_jar=DEFAULT_JPSXDEC_JAR,
    ffmpeg_path=None,
    ffprobe_path=None,
    force=False,
    video_ids=None,
):
    videos = discover_subtitle_videos(video_directory)
    if video_ids:
        requested = {video_id.upper() for video_id in video_ids}
        missing = requested - set(videos)
        if missing:
            raise ValueError(f"Requested subtitle videos are missing: {sorted(missing)}")
        videos = {key: value for key, value in videos.items() if key in requested}

    outputs = {}
    for video_id, avi_path in videos.items():
        outputs[video_id] = prepare_subtitle_video(
            video_id,
            avi_path,
            output_directory=output_directory,
            jpsxdec_jar=jpsxdec_jar,
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
            force=force,
        )
    return outputs


def build_subtitle_video_replacements(**kwargs):
    outputs = prepare_subtitle_videos(**kwargs)
    return {
        f"D/{video_id}.BIN": path.read_bytes()
        for video_id, path in outputs.items()
    }
