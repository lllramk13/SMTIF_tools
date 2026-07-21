#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path


NEW_DIRECTORY = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(NEW_DIRECTORY))

from src.video_replacement import (
    DEFAULT_JPSXDEC_JAR,
    DEFAULT_OUTPUT_DIRECTORY,
    DEFAULT_VIDEO_DIRECTORY,
    prepare_subtitle_videos,
)


def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Re-encode translated AVI frames into the original PS1 video containers."
    )
    parser.add_argument("--video-dir", type=Path, default=DEFAULT_VIDEO_DIRECTORY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIRECTORY)
    parser.add_argument("--jpsxdec-jar", type=Path, default=DEFAULT_JPSXDEC_JAR)
    parser.add_argument("--ffmpeg", type=Path)
    parser.add_argument("--ffprobe", type=Path)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--only", action="append", metavar="FXXXX")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_arguments()
    prepare_subtitle_videos(
        video_directory=arguments.video_dir,
        output_directory=arguments.output_dir,
        jpsxdec_jar=arguments.jpsxdec_jar,
        ffmpeg_path=arguments.ffmpeg,
        ffprobe_path=arguments.ffprobe,
        force=arguments.force,
        video_ids=arguments.only,
    )
