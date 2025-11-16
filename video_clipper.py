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
import hashlib

KEY_ORIGINAL_FILENAME = "original"
KEY_START = "start"
KEY_END = "end"
KEY_CLIPS = "clips"
KEY_SHA256_CHECKSUM = "sha256_checksum"

EXAMPLE_MANIFEST = """\
Example manifest file:
[
    {
        "original": "2593592-15.mp4",
        "clips": [
            {
                "start": "00:10:00",
                "end": "00:31:56"
            }.
            ... more clips
        ]
    },
    ... more videos
]
"""


@dataclass
class VideoClipInfo:
    original_path: Path  # full path
    clip_path: Path  # full path
    start_timestamp: str
    end_timestamp: str
    sha256_checksum: str | None
    original_clip_json: dict  # used for updating the sha256sum


def check_ffmpeg_installed() -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return True


def sha25_hash_of_file(filepath: Path) -> str:
    hasher = hashlib.sha256()

    with filepath.open("rb") as f:
        while True:
            data = f.read(131072)
            if not data:
                break
            hasher.update(data)
    return hasher.hexdigest()


def save_manifest(
    manifest, manifest_path: Path, no_backup: bool, dryrun=False
):
    if dryrun:
        # Nothing was modified, so there is nothing to save
        return

    if not no_backup:
        shutil.copy2(manifest_path, f"{manifest_path}.backup")

    with open(manifest_path, "w") as json_file:
        json.dump(manifest, json_file, indent=4, sort_keys=False)


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
            print(
                f"Could not locate original file {original} at path {Path(output_dir / original)}"
            )
            return False

        for idx, clip_entry in enumerate(file_entry.get("clips")):
            if KEY_START not in clip_entry:
                print(
                    f"Missing '{KEY_START}' timstamp of the form 'HH:MM:SS' for clip {idx} in entry:"
                )
                pprint(file_entry)
                print()
                return False

            if KEY_END not in clip_entry:
                print(
                    f"Missing '{KEY_END}' timstamp of the form 'HH:MM:SS' for clip {idx} in entry:"
                )
                pprint(file_entry)
                print()
                return False

            if not is_valid_time_format(clip_entry.get(KEY_START)):
                print(
                    f"Invalid '{KEY_START}' timestamp for clip {idx}. Should be of the form 'HH:MM:SS'"
                )
                pprint(file_entry)
                print()
                return False

            if not is_valid_time_format(clip_entry.get(KEY_END)):
                print(
                    f"Invalid '{KEY_END}' timestamp for clip {idx}. Should be of the form 'HH:MM:SS'"
                )
                pprint(file_entry)
                print()
                return False

    return True


def parse_manifest(
    manifest_json, input_dir: Path, output_dir: Path
) -> list[VideoClipInfo]:
    video_clips = []
    for file_entry in manifest_json:
        original_filename: str = file_entry.get(KEY_ORIGINAL_FILENAME)
        original_filepath = Path(input_dir / original_filename)
        for idx, clip_entry in enumerate(file_entry.get(KEY_CLIPS)):
            clip_filepath = (
                output_dir
                / f"{original_filepath.stem}_{idx}{original_filepath.suffix}"
            )

            start_timestamp: str = clip_entry.get(KEY_START)
            end_timestamp: str = clip_entry.get(KEY_END)
            sha256_checksum = clip_entry.get(KEY_SHA256_CHECKSUM)
            video_clips.append(
                VideoClipInfo(
                    original_filepath,
                    clip_filepath,
                    start_timestamp,
                    end_timestamp,
                    sha256_checksum,
                    clip_entry,
                )
            )

    return video_clips


def should_clip_video(clip: VideoClipInfo, overwrite: bool) -> bool:
    """Does a clip need to be overwritten and is it allowed?

    Called within tqdm iterator so use tqdm.write
    """

    if not clip.clip_path.exists():
        return True

    current_clip_hash = sha25_hash_of_file(clip.clip_path)
    if current_clip_hash == clip.sha256_checksum:
        return False

    tqdm.write(
        f"Hash mismatch for clip {clip.clip_path}. Expected {clip.sha256_checksum} Found {current_clip_hash}"
    )
    if overwrite:
        tqdm.write("Overwriting clip")
        return True
    else:
        tqdm.write("Will not overwrite clip as --overwrite is not set")
        return False


def clip_video(clip: VideoClipInfo):
    try:
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
        process = subprocess.run(
            cmd, capture_output=True, text=True, check=False
        )

        if process.returncode != 0:
            tqdm.write(
                f"Error creating clip {clip.clip_path}: {process.stderr}"
            )

    except subprocess.CalledProcessError as e:
        tqdm.write(f"Error creating clip: {e}")


def get_file_entry_clips(manifest, filename: str) -> list | None:
    for file_entry in manifest:
        original_filename: str = file_entry.get(KEY_ORIGINAL_FILENAME)
        if original_filename != filename:
            continue

        if "clips" not in file_entry:
            print(f"Error: Failed to find {KEY_CLIPS} in entry for {filename}")
            return None

        return file_entry.get(KEY_CLIPS)

    # If there is no file entry for this file
    new_entry = {KEY_ORIGINAL_FILENAME: filename, KEY_CLIPS: []}
    manifest.append(new_entry)

    return new_entry.get(KEY_CLIPS)


def add_command(args: argparse.Namespace) -> bool:
    try:
        with open(args.manifest) as f:
            manifest = json.load(f)
    except Exception as e:
        print(f"Error loading manifest file: {e}")
        return False

    if not is_valid_time_format(args.start):
        print(
            "Error: Invalid start timestamp. Should be of the form 'HH:MM:SS'"
        )
        return False

    if not is_valid_time_format(args.end):
        print("Error: Invalid end timestamp. Should be of the form 'HH:MM:SS'")
        return False

    if args.start >= args.end:
        print(f"Error: Start '{args.start}' comes after End '{args.end}'")
        return False

    # returned array always contained within manifest
    clips_array = get_file_entry_clips(manifest, args.filename)
    if clips_array is None:
        return False

    clips_array.append(
        {KEY_START: args.start, KEY_END: args.end, KEY_SHA256_CHECKSUM: "none"}
    )

    # Sort manifest by filename
    manifest = sorted(
        manifest, key=lambda file_entry: file_entry[KEY_ORIGINAL_FILENAME]
    )

    save_manifest(manifest, args.manifest, args.no_backup)

    return True


def clip_command(args: argparse.Namespace) -> bool:
    if not check_ffmpeg_installed():
        print("FFmpeg is not installed!")
        return False

    # Set up paths
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(exist_ok=True)

    if args.overwrite:
        print("Warning: Will overwrite existing clips")

    # Check if original dir
    if not input_dir.exists():
        print(f"Error: Originals dir not found at {input_dir}")
        return False

    if not input_dir.is_dir():
        print(f"Error: Input dir is not a directory {input_dir}")
        return False

    try:
        with open(args.manifest) as f:
            manifest = json.load(f)
    except Exception as e:
        print(f"Error loading manifest file: {e}")
        return False

    if not validate_manifest(manifest, input_dir):
        print("Failed to validate json manifest")
        return False

    clips = parse_manifest(manifest, input_dir, output_dir)

    if len(clips) == 0:
        print("Nothing to process!")

    for clip in tqdm(clips, desc="Processing clips"):
        if not should_clip_video(clip, args.overwrite):
            continue

        if args.dryrun:
            tqdm.write(
                f"Dryrun: would have clipped {clip.original_path} -> {clip.clip_path}"
            )
            continue
        clip_video(clip)

        clip.original_clip_json[KEY_SHA256_CHECKSUM] = sha25_hash_of_file(
            clip.clip_path
        )

    save_manifest(manifest, args.manifest, args.dryrun, args.dryrun)

    return True


def validate_command(args: argparse.Namespace) -> bool:
    # Set up paths
    input_dir: Path = args.input_dir
    output_dir: Path = args.output_dir

    try:
        with open(args.manifest) as f:
            manifest = json.load(f)
    except Exception as e:
        print(f"Error loading manifest file: {e}")
        return False

    if not validate_manifest(manifest, input_dir):
        print("Failed to validate json manifest")
        return False

    try:
        with open(args.manifest) as f:
            manifest = json.load(f)
    except Exception as e:
        print(f"Error loading manifest file: {e}")
        return False

    clips = parse_manifest(manifest, input_dir, output_dir)

    valid = True

    for clip in clips:
        current_hash = sha25_hash_of_file(clip.clip_path)
        if clip.sha256_checksum != current_hash:
            print(
                f"Mismatched checksum for clip {clip.clip_path}!\nExpected {clip.sha256_checksum} Got {current_hash}"
            )
            valid = False

    return valid


def main():
    parser = argparse.ArgumentParser(
        description="Create clips from multiple video files",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog=EXAMPLE_MANIFEST,
    )
    subparsers = parser.add_subparsers(dest="command")

    # Common flags
    base_subparser = argparse.ArgumentParser(add_help=False)
    base_subparser.add_argument(
        "--manifest",
        type=Path,
        required=True,
        help="JSON file containing clip timestamps",
    )

    ## Add Parser
    add_parser = subparsers.add_parser(
        "add",
        help="Add a clip definition to the manifest.json",
        parents=[base_subparser],
    )
    add_parser.add_argument(
        "--filename",
        type=str,
        required=True,
        help="Name of the file relative to your desired directory",
    )
    add_parser.add_argument(
        "--start", type=str, required=True, help="start timestamp HH:MM:SS"
    )
    add_parser.add_argument(
        "--end", type=str, required=True, help="end timestamp HH:MM:SS"
    )
    add_parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not save a *.backup of your manifest before editing/",
    )

    ## Clip Parser
    clip_parser = subparsers.add_parser(
        "clip",
        help="Clip videos based on the manifest.json",
        parents=[base_subparser],
    )
    clip_parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Path to original files' directory",
    )
    clip_parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Output directory for clips",
    )
    clip_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing file if the expected hash does not equal the existing file hash. Otherwise skip",
    )
    clip_parser.add_argument(
        "--dryrun",
        action="store_true",
        help="Only print, do not modify/create files",
    )
    clip_parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not save a *.backup of your manifest before editing/",
    )

    ## Validate Parser
    validate_parser = subparsers.add_parser(
        "validate",
        help="Validate your manifest.json",
        parents=[base_subparser],
    )
    validate_parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Path to original files' directory",
    )
    validate_parser.add_argument(
        "--output-dir",
        type=Path,
        default="clips",
        help="Output directory for clips. If provided, will hash files and compare against manifest",
    )

    args = parser.parse_args()

    if args.command == "add":
        if not add_command(args):
            sys.exit(1)
    elif args.command == "clip":
        if not clip_command(args):
            sys.exit(1)
    elif args.command == "validate":
        if not validate_command(args):
            sys.exit(1)
    else:
        print(f"Invalid command '{args.command}'!")
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
