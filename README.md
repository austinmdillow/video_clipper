# Video Clipper

A simple wrapper around `ffmpeg -ss HH:MM:SS -to HH:MM:S` inspired by [ErikThiart/VideoClipper](https://github.com/ErikThiart/VideoClipper).


## Requirements

- [ffmpeg](https://ffmpeg.org/)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
  - or just `pip install tdqm`


## Manifest

This tool uses a manifest file to describe what videos should be clipped. Paths are relative to `--input-dir`.

```json
[
    {
        "original": "videoA.mp4",
        "clips": [
            {
                "start": "00:05:00",
                "end": "00:06:20",
                "sha256_checksum": "0d3af98334b796efd7f66c152a87c534430d686e024be01509fe50fecc3f9ecf"
            }
        ]
    },
    {
        "original": "subfolder/videoB.mp4",
        "clips": [
            {
                "start": "00:00:00",
                "end": "00:01:00",
                "sha256_checksum": "9878fadb8d31ff8e8f10fdb796fd8182b6d35a34c6b7e2fed8a45c7c60cb407f"
            },
            {
                "start": "00:00:55",
                "end": "00:02:30",
                "sha256_checksum": "56ae1efbdc393b166e23d9b3df8b01673484b2d6b9b84ae766b59dc933afbef5"
            }
        ]
    }
]
```

Results of above manifest

```
$ uv run video_clipper.py clip --manifest example_manifest.json --input-dir ~/Downloads/videos/ --output-dir ~/Downloads/clips/
```

```
/home/user/Downloads/
├── clips
│   ├── videoA_0.mp4
│   ├── videoB_0.mp4
│   └── videoB_1.mp4
└── videos
    ├── subfolder
    │   └── videoB.mp4
    └── videoA.mp4
```

## CLI

### `add`

Manually editing the manifest can be tedious. Do this instead.

```bash
$ uv run video_clipper.py add --manifest trim_manifest.json --filename videoA.mp4 --start 00:00:06 --end 00:11:28
```

### `clip`

By default, existing clips will not be overwritten.
```bash
$ uv run video_clipper.py clip --manifest manifest.json --input-dir myvideos/ --output-dir my_clips/
```

Check sha256sum of existing files and overwrite if they do not match the manifest.
```bash
$ uv run video_clipper.py clip --manifest manifest.json --input-dir myvideos/ --output-dir my_clips/ --overwrite
```

### `validate`

Include the `--output-dir` to check the sha256sum of the clips.
```bash
$ uv run video_clipper.py validate --manifest manifest.json --input-dir myvideos/ --output-dir my_clips/
```