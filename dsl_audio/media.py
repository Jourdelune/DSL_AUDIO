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
    """Load audio from an audio file or from a video container."""
    path = Path(path)
    fmt = _VIDEO_FORMAT_BY_EXT.get(path.suffix.lower())
    if fmt:
        return AudioSegment.from_file(str(path), format=fmt)
    return AudioSegment.from_file(str(path))
