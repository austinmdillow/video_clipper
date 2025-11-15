import argparse
from pathlib import Path
import subprocess
import json
from tqdm import tqdm
from pprint import pprint
from dataclasses import dataclass
import re
import shutil
import sys

KEY_ORIGINAL_FILENAME = "original"
KEY_START = "start"
KEY_END = "end"
KEY_CLIPS = "clips"

EXAMPLE_MANIFEST = """\
Example manifest file
[
    {
        "original": "2593592-15.mp4",
        "clips": [
            {
                "start": "00:10:00",
                "end": "00:31:56"
            }
        ]
    },
    {
        "original": "2593592-16.mp4",
        "clips": [
            {
                "start": "00:00:00",
                "end": "00:01:58"
            },
            {
                "start": "00:01:59",
                "end": "00:08:40"
            }
        ]
    }
]
"""


@dataclass
class VideoClipInfo:
    original_path: Path
    clip_path: Path
    start_timestamp: str
    end_timestamp: str


def check_ffmpeg():
    try:
        subprocess.run(["ffmpeg", "-version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("FFmpeg is not installed!")
        sys.exit(1)


def is_valid_time_format(timestamp: str) -> bool:
    if not re.match(r"^\d{2}:\d{2}:\d{2}$", timestamp):
        return False
    hours, minutes, seconds = map(int, timestamp.split(":"))
    return 0 <= hours <= 24 and 0 <= minutes <= 60 and 0 <= seconds <= 60


def validate_manifest(manifest_json, output_dir: Path) -> bool:
    for file_entry in manifest_json:
        original: str = file_entry.get(KEY_ORIGINAL_FILENAME)
        if original is None:
            print(f"Could not find '{KEY_ORIGINAL_FILENAME}' key in entry")
            return False

        if not Path(output_dir / original).is_file():
            print(f"Could not locate original file {original} at path {Path(output_dir / original)}")
            return False

        for idx, clip_entry in enumerate(file_entry.get("clips")):
            if KEY_START not in clip_entry:
                print(f"Missing '{KEY_START}' timstamp of the form 'HH:MM:SS' for clip {idx} in entry:")
                pprint(file_entry)
                print()
                return False

            if KEY_END not in clip_entry:
                print(f"Missing '{KEY_END}' timstamp of the form 'HH:MM:SS' for clip {idx} in entry:")
                pprint(file_entry)
                print()
                return False

            if not is_valid_time_format(clip_entry.get(KEY_START)):
                print(f"Invalid '{KEY_START}' timestamp for clip {idx}. Should be of the form 'HH:MM:SS'")
                pprint(file_entry)
                print()
                return False

            if not is_valid_time_format(clip_entry.get(KEY_END)):
                print(f"Invalid '{KEY_END}' timestamp for clip {idx}. Should be of the form 'HH:MM:SS'")
                pprint(file_entry)
                print()
                return False

    return True


def parse_manifest(manifest_json, input_dir: Path, output_dir: Path, overwrite: bool) -> list[VideoClipInfo]:
    video_clips = []
    skip_count = 0
    for file_entry in manifest_json:
        original_filename: str = file_entry.get(KEY_ORIGINAL_FILENAME)
        original_filepath = Path(input_dir / original_filename)
        for idx, clip_entry in enumerate(file_entry.get(KEY_CLIPS)):
            clip_filepath = output_dir / f"{original_filepath.stem}_{idx}{original_filepath.suffix}"

            if not overwrite and clip_filepath.exists():
                skip_count += 1
                continue

            start_timestamp: str = clip_entry.get(KEY_START)
            end_timestamp: str = clip_entry.get(KEY_END)
            video_clips.append(VideoClipInfo(original_filepath, clip_filepath, start_timestamp, end_timestamp))

    print(f"Found {len(video_clips)} clips. Skipped {skip_count}")

    return video_clips


def clip_video(clip: VideoClipInfo):
    try:
        # Set up ffmpeg command
        cmd = [
            "ffmpeg",
            "-ss",
            clip.start_timestamp,
            "-to",
            clip.end_timestamp,
            "-i",
            str(clip.original_path),
            "-c",
            "copy",
            str(clip.clip_path),
            "-y",
        ]

        tqdm.write(f"Creating clip {clip.clip_path}")
        process = subprocess.run(cmd, capture_output=True, text=True)

        if process.returncode != 0:
            tqdm.write(f"Error creating clip {clip.clip_path}: {process.stderr}")

    except subprocess.CalledProcessError as e:
        tqdm.write(f"Error creating clip: {e}")

def get_file_entry_clips(manifest, filename:str) -> list | None:
    for file_entry in manifest:
        original_filename: str = file_entry.get(KEY_ORIGINAL_FILENAME)
        if original_filename == filename:

            if "clips" not in file_entry:
                print(f"Error: Failed to find {KEY_CLIPS} in entry for {filename}")
                return None

            return file_entry.get(KEY_CLIPS)
    
    new_entry = {KEY_ORIGINAL_FILENAME: filename, KEY_CLIPS:[]}
    manifest.append(new_entry)

    return new_entry.get(KEY_CLIPS)

def add_command(args: argparse.Namespace)->bool:
    try:
        with open(args.manifest) as f:
            manifest = json.load(f)
    except Exception as e:
        print(f"Error loading manifest file: {e}")
        return False

    if not is_valid_time_format(args.start):
        print(f"Error: Invalid start timestamp. Should be of the form 'HH:MM:SS'")
        return False
    
    if not is_valid_time_format(args.end):
        print(f"Error: Invalid end timestamp. Should be of the form 'HH:MM:SS'")
        return False
    
    if args.start >= args.end:
        print(f"Error: Start '{args.start}' comes after End '{args.end}'")
        return False

    clips_array = get_file_entry_clips(manifest, args.filename)
    if clips_array is None:
        return False

    print(clips_array)

    clips_array.append({KEY_START: args.start, KEY_END:args.end})

    shutil.copy2(args.manifest, f"{args.manifest}.backup")

    with open(args.manifest, 'w') as json_file:
        json.dump(manifest, json_file, indent=4, sort_keys=False)

    return True
    

def clip_command(args: argparse.Namespace):
     # Set up paths
    originals_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)

    if args.overwrite:
        print("Warning: Will overwrite existing clips")

    # Check if original dir
    if not originals_dir.exists():
        print(f"Error: Originals dir not found at {originals_dir}")
        return

    if not originals_dir.is_dir():
        print(f"Error: Input dir is not a directory {originals_dir}")
        return

    try:
        with open(args.manifest) as f:
            manifest = json.load(f)
    except Exception as e:
        print(f"Error loading manifest file: {e}")
        return

    if not validate_manifest(manifest, originals_dir):
        print("Failed to validate json manifest")
        return

    clips = parse_manifest(manifest, originals_dir, output_dir, args.overwrite)

    if len(clips) == 0:
        print("Warning: Nothing to process!")

    for clip in tqdm(clips, desc="Processing clips"):
        clip_video(clip)

def main():
    # Prechecks
    check_ffmpeg()

    parser = argparse.ArgumentParser(
        description="Create clips from multiple video files",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=EXAMPLE_MANIFEST,
    )
    parser.add_argument(
        "--manifest",
        type=str,
        required=True,
        help="JSON file containing clip timestamps",
    )
    subparsers = parser.add_subparsers(dest="command")

    add_parser = subparsers.add_parser("add", help="Add a clip definition to the manifest.json")
    add_parser.add_argument("--filename", type=str, required=True, help="Name of the file relative to your desired directory")
    add_parser.add_argument("--start", type=str, required =True, help="start timestamp HH:MM:SS")
    add_parser.add_argument("--end", type=str, required= True, help="end timestamp HH:MM:SS")

    clip_parser = subparsers.add_parser("clip", help="Clip videos based on the manifest.json")
    clip_parser.add_argument("--input-dir", type=str, required=True, help="Path to original files' directory")
    clip_parser.add_argument("--output-dir", type=str, default="clips", help="Output directory for clips")
    clip_parser.add_argument("--overwrite", action="store_true", help="Overwrite existing files. Otherwise skip")
    args = parser.parse_args()

    if args.command == "add":
        
        add_command(args)
    elif args.command == "clip":
        clip_command(args)
    else:
        print(f"Invalid command '{args.command}'!")
        parser.print_help()
   
if __name__ == "__main__":
    main()
