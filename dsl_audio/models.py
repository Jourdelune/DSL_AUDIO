from dataclasses import dataclass, field
from typing import Optional


def parse_time(s: str) -> int:
    """Parse time string (HH:MM:SS.mmm, MM:SS.mmm, MM:SS, SS.mmm) to milliseconds."""
    s = s.strip()
    parts = s.split(":")
    if len(parts) == 3:
        h, m, sec = int(parts[0]), int(parts[1]), float(parts[2])
    elif len(parts) == 2:
        h, m, sec = 0, int(parts[0]), float(parts[1])
    else:
        h, m, sec = 0, 0, float(parts[0])
    return int((h * 3600 + m * 60 + sec) * 1000)


def parse_duration(s: str) -> int:
    """Parse duration string ('2s', '500ms', '1.5s') to milliseconds."""
    s = s.strip()
    if s.endswith("ms"):
        return int(float(s[:-2]))
    elif s.endswith("s"):
        return int(float(s[:-1]) * 1000)
    return int(float(s) * 1000)


def ms_to_str(ms: int) -> str:
    """Convert milliseconds to MM:SS.mmm display string."""
    total_sec = ms / 1000
    minutes = int(total_sec // 60)
    seconds = total_sec % 60
    return f"{minutes:02d}:{seconds:06.3f}"


@dataclass
class TrackEvent:
    # ── Placement ────────────────────────────────────────────────
    timestamp_ms: int
    track_name: str
    filepath: str

    # ── Clip boundaries ──────────────────────────────────────────
    trim_start_ms: int = 0
    trim_end_ms: Optional[int] = None     # ms to cut from the end of the clip
    end_ms: Optional[int] = None          # absolute timeline position to stop

    # ── Dynamics & gain ──────────────────────────────────────────
    vol: float = 1.0
    normalize: bool = False               # True = peak normalize
    normalize_target_dbfs: Optional[float] = None  # None=peak, float=RMS target dBFS
    compress: bool = False
    compress_threshold: float = -20.0    # dBFS
    compress_ratio: float = 4.0
    compress_attack_ms: float = 5.0
    compress_release_ms: float = 50.0

    # ── EQ / filtering ───────────────────────────────────────────
    highpass_hz: Optional[int] = None
    lowpass_hz: Optional[int] = None

    # ── Spatial & time ───────────────────────────────────────────
    pan: Optional[float] = None           # -1.0 (L) … 0 (C) … 1.0 (R)
    speed: Optional[float] = None         # multiplier; also changes pitch
    reverse: bool = False

    # ── Cleanup ──────────────────────────────────────────────────
    strip_silence: bool = False
    strip_silence_thresh_dbfs: float = -40.0
    strip_silence_min_len_ms: int = 500
    mono: bool = False                    # mix down to mono before effects

    # ── Fades (always applied last) ───────────────────────────────
    fade_in_ms: int = 0
    fade_out_ms: int = 0

    @property
    def timestamp_str(self) -> str:
        return ms_to_str(self.timestamp_ms)
