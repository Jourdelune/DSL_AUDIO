"""Media loading helpers."""
from pathlib import Path

from pydub import AudioSegment

_VIDEO_FORMAT_BY_EXT = {
    ".mp4": "mp4",
    ".m4v": "mp4",
    ".mov": "mov",
    ".mkv": "matroska",
    ".webm": "webm",
}


def load_audio_segment(path: str | Path) -> AudioSegment:
    """Load media audio from `path`.

    Supported video containers are detected by extension:
    .mp4, .m4v, .mov, .mkv, .webm.
    For these formats, `pydub` is called with an explicit ffmpeg format so the
    audio track is decoded reliably.

    For any other suffix (or no suffix), it falls back to pydub's default
    auto-detection behavior.
    """
    path = Path(path)
    # Files without extension produce an empty suffix (""), which safely
    # resolves to None in the mapping and triggers the default loader.
    fmt = _VIDEO_FORMAT_BY_EXT.get(path.suffix.lower())
    if fmt:
        return AudioSegment.from_file(str(path), format=fmt)
    return AudioSegment.from_file(str(path))
