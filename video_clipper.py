import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tqdm import tqdm

KEY_VERSION = "version"
KEY_VIDEOS = "videos"
KEY_ORIGINAL_FILENAME = "original"
KEY_START = "start"
KEY_END = "end"
KEY_CLIPS = "clips"
KEY_SHA256_CHECKSUM = "sha256_checksum"

EXAMPLE_MANIFEST = """\
Example manifest file:
{
  "version": "1",
  "videos": {
    "videoA.mp4": {
      "clips": {
        "videoA_0.mp4": {
          "start": "00:00:27",
          "end": "00:34:35",
          "sha256_checksum": "d6513...."
        },
        ... more clips
      }
    },
    ... more videos
  }
}
"""


@dataclass
class VideoClip:
    filename: str  # relative to output-dir
    start_timestamp: str
    end_timestamp: str
    sha256_checksum: str  # `none` is used for an unknown hash

    @staticmethod
    def from_json(
        clip_name: str, clip_json: dict[str, str]
    ) -> "VideoClip | None":
        start_timestamp = clip_json.get(KEY_START)
        if start_timestamp is None:
            print(
                f"Missing '{KEY_START}' timestamp of the form 'HH:MM:SS' for clip {clip_name}"
            )
            return None

        end_timestamp = clip_json.get(KEY_END)
        if end_timestamp is None:
            print(
                f"Missing '{KEY_END}' timestamp of the form 'HH:MM:SS' for clip {clip_name}"
            )
            return None

        sha256_checksum = clip_json.get(KEY_SHA256_CHECKSUM, "none")
        clip = VideoClip(
            clip_name, start_timestamp, end_timestamp, sha256_checksum
        )

        return clip

    def to_json(self) -> dict[str, str]:
        return {
            KEY_START: self.start_timestamp,
            KEY_END: self.end_timestamp,
            KEY_SHA256_CHECKSUM: self.sha256_checksum,
        }

    def get_filepath(self, output_dir: Path) -> Path:
        return output_dir / self.filename


# TODO: rename to source
@dataclass
class VideoFile:
    filename: str  # relative to input-dir
    clips: dict[str, VideoClip]

    @staticmethod
    def from_json(video_name: str, video_json: dict) -> "VideoFile | None":
        video_file = VideoFile(video_name, {})

        if KEY_CLIPS not in video_json:
            print(f"Missing '{KEY_CLIPS}' in video entry {video_name}")
            return None

        for clip_name, clip_json in video_json[KEY_CLIPS].items():
            clip = VideoClip.from_json(clip_name, clip_json)
            if clip is None:
                return None
            video_file.clips[clip_name] = clip

        return video_file

    def to_json(self) -> dict:
        return {
            KEY_CLIPS: {
                clip.filename: clip.to_json() for clip in self.clips.values()
            }
        }

    def get_filepath(self, input_dir: Path) -> Path:
        return input_dir / self.filename

    def add_new_clip(self, begin: str, end: str) -> bool:
        """Insert a new clip into the VideoFile with a generated name"""
        for clip in self.clips.values():
            if clip.start_timestamp == begin and clip.end_timestamp == end:
                print(
                    f"Clip {clip.filename} already exists for video {self.filename} from {clip.start_timestamp} -> {clip.end_timestamp}"
                )
                return False

        # TODO: more intelligent naming based on timestamps instead of incrementing by one
        clip_idx = 0
        input_path = Path(self.filename)

        while True:
            candidate_clip_name = (
                f"{input_path.stem}_{clip_idx}{input_path.suffix}"
            )
            if candidate_clip_name not in self.clips:
                self.clips[candidate_clip_name] = VideoClip(
                    candidate_clip_name, begin, end, "none"
                )
                return True
            clip_idx += 1


@dataclass
class VideoClipperManifest:
    version: str
    video_files: dict[str, VideoFile]

    @staticmethod
    def from_json_file(manifest_path: Path) -> "VideoClipperManifest | None":
        try:
            with open(manifest_path) as f:
                manifest_json = json.load(f)
        except Exception as e:
            print(f"Error loading manifest file {manifest_path}: {e}")
            return None

        manifest = VideoClipperManifest.from_json(manifest_json)
        if manifest is None:
            print(f"Failed to parse manifest {manifest_path}")
            return None

        return manifest

    @staticmethod
    def from_json(
        manifest_json: dict[str, Any],
    ) -> "VideoClipperManifest | None":
        if KEY_VERSION not in manifest_json:
            print(f"Missing '{KEY_VERSION}' in manifest")
            return None

        manifest = VideoClipperManifest(
            version=manifest_json[KEY_VERSION], video_files={}
        )

        if KEY_VIDEOS not in manifest_json:
            print(f"Missing '{KEY_VIDEOS}' in manifest")
            return None

        for video_name, video_json in manifest_json[KEY_VIDEOS].items():
            video_file = VideoFile.from_json(video_name, video_json)

            if video_file is None:
                return None
            manifest.video_files[video_name] = video_file

        return manifest

    def to_json(self) -> dict:
        return {
            KEY_VERSION: self.version,
            KEY_VIDEOS: {
                video.filename: video.to_json()
                for video in self.video_files.values()
            },
        }

    def sort(self) -> None:
        self.video_files = dict(sorted(self.video_files.items()))

    def add_new_clip(self, input_filename: str, begin: str, end: str) -> bool:
        """Insert a new clip into the manifest. A new VideoFile will be created if needed."""

        file_entry = self.video_files.get(input_filename)

        if file_entry is None:
            file_entry = VideoFile(input_filename, {})
            self.video_files[input_filename] = file_entry
        return file_entry.add_new_clip(begin, end)

    def validate_input_files(self, input_dir: Path) -> bool:
        """Check that the input data in the manifest is valid.
        Does not check clips that have or have not been made
        """

        for video_file in self.video_files.values():
            video_filepath = video_file.get_filepath(input_dir)

            if not video_filepath.is_file():
                print(
                    f"Could not locate original file {video_file.filename} at path {video_filepath}"
                )
                return False

            for clip in video_file.clips.values():
                if not is_valid_time_format(clip.start_timestamp):
                    print(
                        f"Invalid '{KEY_START}' timestamp for clip {clip.start_timestamp}. Should be of the form 'HH:MM:SS'"
                    )
                    return False

                if not is_valid_time_format(clip.end_timestamp):
                    print(
                        f"Invalid '{KEY_END}' timestamp for clip {clip.end_timestamp}. Should be of the form 'HH:MM:SS'"
                    )
                    return False

        return True


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
    manifest: VideoClipperManifest,
    manifest_path: Path,
    no_backup=False,
    dryrun=False,
):
    # TODO: sort the manifest by filename order. Maybe clip name or clip start time order as well?
    if dryrun:
        # Nothing should be modified in dryrun mode, so there is nothing to save
        return

    if not no_backup:
        shutil.copy2(manifest_path, f"{manifest_path}.backup")

    with open(manifest_path, "w") as json_file:
        json.dump(manifest.to_json(), json_file, indent=4, sort_keys=False)


def is_valid_time_format(timestamp: str) -> bool:
    if not re.match(r"^\d{2}:\d{2}:\d{2}$", timestamp):
        return False
    hours, minutes, seconds = map(int, timestamp.split(":"))
    return 0 <= hours <= 24 and 0 <= minutes <= 60 and 0 <= seconds <= 60


def should_clip_video(
    clip: VideoClip, output_path: Path, overwrite: bool
) -> bool:
    """Does a clip need to be overwritten and is it allowed?

    Called within tqdm iterator so use tqdm.write
    """

    if not clip.get_filepath(output_path).exists():
        return True

    if not overwrite:
        # Could still check the hash and report, but if you really want that, just use `validate`
        return False

    current_clip_hash = sha25_hash_of_file(clip.get_filepath(output_path))
    if current_clip_hash == clip.sha256_checksum:
        return False

    tqdm.write(
        f"Hash mismatch for clip {clip.get_filepath(output_path)}. Expected {clip.sha256_checksum} Found {current_clip_hash}"
    )

    return True


def clip_video(
    video: VideoFile, clip: VideoClip, input_path: Path, output_path: Path
):
    try:
        cmd = [
            "ffmpeg",
            "-ss",
            clip.start_timestamp,
            "-to",
            clip.end_timestamp,
            "-i",
            str(video.get_filepath(input_path)),
            "-c",
            "copy",
            str(clip.get_filepath(output_path)),
            "-y",
        ]

        tqdm.write(f"Creating clip {clip.get_filepath(output_path)}")
        process = subprocess.run(
            cmd, capture_output=True, text=True, check=False
        )

        if process.returncode != 0:
            tqdm.write(
                f"Error creating clip {clip.get_filepath(output_path)}: {process.stderr}"
            )

    except subprocess.CalledProcessError as e:
        tqdm.write(f"Error creating clip: {e}")


def add_command(args: argparse.Namespace) -> bool:
    manifest = VideoClipperManifest.from_json_file(args.manifest)
    if manifest is None:
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

    manifest.add_new_clip(args.filename, args.start, args.end)

    save_manifest(manifest, args.manifest, no_backup=args.no_backup)

    return True


def clip_command(args: argparse.Namespace) -> bool:
    if not check_ffmpeg_installed():
        print("FFmpeg is not installed!")
        return False

    # For type hinting only
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    if args.overwrite:
        print("Warning: Will overwrite existing clips if hashes do not match")

    # Check if original dir
    if not input_dir.exists() or not input_dir.is_dir():
        print("Error: input-dir must be an already existing directory")
        return False

    if not output_dir.exists() or not output_dir.is_dir():
        print("Error: output-dir must be an already existing directory")
        return False

    manifest = VideoClipperManifest.from_json_file(args.manifest)
    if manifest is None:
        return False

    if not manifest.validate_input_files(input_dir):
        print(f"Failed to validate manifest {args.manifest}")
        return False

    if len(manifest.video_files) == 0:
        print("Nothing to process!")
        return False

    all_clips_with_file = [
        (video, clip)
        for video in manifest.video_files.values()
        for clip in video.clips.values()
    ]

    for video, clip in tqdm(all_clips_with_file, desc="Processing clips"):
        if not should_clip_video(clip, output_dir, args.overwrite):
            continue

        if args.dryrun:
            tqdm.write(
                f"Dryrun: would have clipped {video.get_filepath(input_dir)} -> {clip.get_filepath(output_dir)}"
            )
            continue
        clip_video(video, clip, input_dir, output_dir)

        clip.sha256_checksum = sha25_hash_of_file(
            clip.get_filepath(output_dir)
        )

    save_manifest(
        manifest, args.manifest, no_backup=args.no_backup, dryrun=args.dryrun
    )

    return True


def validate_command(args: argparse.Namespace) -> bool:
    # for intellisense
    input_dir: Path = args.input_dir
    output_dir: Path | None = args.output_dir

    manifest = VideoClipperManifest.from_json_file(args.manifest)
    if manifest is None:
        return False

    if not manifest.validate_input_files(input_dir):
        print("Failed to validate json manifest")
        return False

    valid = True

    if args.checksum:
        if output_dir is None:
            print(
                "Error: Must provide --output-dir if you want to check --checksum"
            )
            return False

        all_clips = [
            clip
            for video_file in manifest.video_files.values()
            for clip in video_file.clips.values()
        ]

        for clip in tqdm(all_clips, desc="Hashing clips"):
            current_hash = sha25_hash_of_file(clip.get_filepath(output_dir))
            if clip.sha256_checksum != current_hash:
                tqdm.write(
                    f"Mismatched checksum for clip {clip.get_filepath(output_dir)}!\nExpected {clip.sha256_checksum} Got {current_hash}"
                )
                valid = False
    else:
        print("Skipping checksum validation")

    if valid:
        print("OK")

    return valid


def prune_command(args: argparse.Namespace) -> bool:
    # for intellisense
    output_dir: Path = args.output_dir

    manifest = VideoClipperManifest.from_json_file(args.manifest)
    if manifest is None:
        return False

    known_clip_names = {
        clip_name
        for video in manifest.video_files.values()
        for clip_name in video.clips
    }

    matching_filepaths: set[Path] = set()
    for video_name in manifest.video_files:
        video_as_path = Path(video_name)
        # clips looks like "{video_name}_{idx}.{video_extension}"
        # TODO: not exactly right, but close enough
        glob_result = output_dir.glob(
            f"{video_as_path.stem}_[0-9]*{video_as_path.suffix}"
        )

        for match in glob_result:
            if match.name in known_clip_names:
                continue
            if not match.is_file():
                continue
            matching_filepaths.add(match)

    if len(matching_filepaths) == 0:
        print(
            "Found no files that look like a clip and are not in the manifest"
        )
        return True

    print("=== WILL DELETE THE BELOW FILES ===")
    for path_to_delete in matching_filepaths:
        print(path_to_delete)
    print("=== WILL DELETE THE ABOVE FILES ===")

    if input("Permanently delete the above files? [y/n]: ") != "y":
        print("Skipping. Will not delete")
        return True

    for path_to_delete in matching_filepaths:
        print(f"Deleting: {path_to_delete}")
        path_to_delete.unlink()

    return True


def format_command(args: argparse.Namespace) -> bool:
    # for intellisense

    manifest = VideoClipperManifest.from_json_file(args.manifest)
    if manifest is None:
        return False

    manifest.sort()

    save_manifest(manifest, args.manifest)

    return True


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
        "-m",
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
        help="Do not save a *.backup of your manifest before editing",
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
        help="Overwrite existing file if the expected hash does not "
        "equal the existing file hash. Otherwise skip",
    )
    clip_parser.add_argument(
        "--dryrun",
        action="store_true",
        help="Only print, do not modify/create files",
    )
    clip_parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not save a *.backup of your manifest before editing",
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
        help="Output directory for clips. Required if you want to check checksums",
    )
    validate_parser.add_argument(
        "--checksum",
        action="store_true",
        help="Compare the clip checksum with the actual sha256 hash of the clip",
    )

    ## Prune command
    prune_parser = subparsers.add_parser(
        "prune",
        help="Remove all clip that could have been generated from your manifest "
        "but are not in the manifest. A clip must match the pattern video_name_idx.video_extension",
        parents=[base_subparser],
    )
    prune_parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory to prune",
    )

    ## Format command
    format_parser = subparsers.add_parser(
        "format",
        help="Format your manifest file",
        parents=[base_subparser],
    )
    format_parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not save a *.backup of your manifest before formatting",
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
    elif args.command == "prune":
        if not prune_command(args):
            sys.exit(1)
    elif args.command == "format":
        if not format_command(args):
            sys.exit(1)
    else:
        print(f"Invalid command '{args.command}'!")
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
