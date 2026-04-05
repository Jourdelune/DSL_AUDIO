import shlex
from pathlib import Path
from typing import List

from .models import TrackEvent, parse_duration, parse_time

# Options that act as boolean flags (no value required)
_BOOL_FLAGS = {"normalize", "compress", "strip_silence", "mono", "reverse"}


def parse_mix_file(filepath: str | Path) -> List[TrackEvent]:
    """Parse a .mix file and return a sorted list of TrackEvents.

    Syntax per line:
        TIMESTAMP  TRACK_NAME  FILEPATH  [OPTIONS...]  [# comment]

    Boolean flags (no value needed):
        normalize       strip_silence       mono        compress        reverse

    Key=value options:
        vol=0.8               Volume multiplier (default 1.0)
        fade_in=2s            Fade-in duration  (e.g. 2s, 500ms)
        fade_out=3s           Fade-out duration
        trim_start=5s         Skip start of clip
        trim_end=10s          Cut end of clip
        end=01:30.000         Force-stop at absolute timeline position
        normalize=-18         RMS-normalize to target dBFS (omit value = peak)
        compress=-20:4:5:50   Compress: threshold:ratio:attack_ms:release_ms
        highpass=80           High-pass filter cutoff in Hz
        lowpass=8000          Low-pass filter cutoff in Hz
        pan=-0.5              Stereo pan  (-1.0 left … 0 center … 1.0 right)
        speed=1.05            Playback speed multiplier (affects pitch)
        strip_silence=-40:500 Silence threshold dBFS:min silence length ms
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Mix file not found: {filepath}")

    base_dir = filepath.parent
    events: List[TrackEvent] = []

    with open(filepath, encoding="utf-8") as f:
        for lineno, raw_line in enumerate(f, 1):
            comment_pos = raw_line.find("#")
            line = raw_line[:comment_pos].strip() if comment_pos >= 0 else raw_line.strip()
            if not line:
                continue

            try:
                tokens = shlex.split(line)
            except ValueError as exc:
                raise ValueError(f"Line {lineno}: tokenization error — {exc}") from exc

            if len(tokens) < 3:
                raise ValueError(
                    f"Line {lineno}: expected 'TIMESTAMP TRACK_NAME FILEPATH [OPTIONS]',"
                    f" got: {raw_line.rstrip()!r}"
                )

            timestamp_str, track_name, filepath_str = tokens[0], tokens[1], tokens[2]
            option_tokens = tokens[3:]

            timestamp_ms = parse_time(timestamp_str)

            audio_path = Path(filepath_str)
            if not audio_path.is_absolute():
                audio_path = base_dir / audio_path

            # ── Defaults ─────────────────────────────────────────
            kw: dict = {}

            for opt in option_tokens:
                if "=" in opt:
                    key, val = opt.split("=", 1)
                    key = key.strip().lower()
                    val = val.strip()
                else:
                    key = opt.strip().lower()
                    val = None

                # Boolean flags
                if key in _BOOL_FLAGS:
                    if val is None or val.lower() in ("1", "true", "yes"):
                        kw[key] = True
                    elif val.lower() in ("0", "false", "no"):
                        kw[key] = False
                    elif key == "normalize":
                        # normalize=-18  →  RMS target
                        kw["normalize"] = True
                        kw["normalize_target_dbfs"] = float(val)
                    elif key == "compress":
                        # compress=-20:4:5:50
                        _parse_compress(val, kw, lineno)
                    elif key == "strip_silence":
                        # strip_silence=-40:500
                        _parse_strip_silence(val, kw, lineno)
                    else:
                        raise ValueError(f"Line {lineno}: unexpected value for flag {key!r}")
                    continue

                if val is None:
                    raise ValueError(f"Line {lineno}: option {key!r} requires a value (use {key}=…)")

                if key == "vol":
                    kw["vol"] = float(val)
                elif key == "fade_in":
                    kw["fade_in_ms"] = parse_duration(val)
                elif key == "fade_out":
                    kw["fade_out_ms"] = parse_duration(val)
                elif key == "trim_start":
                    kw["trim_start_ms"] = parse_duration(val)
                elif key == "trim_end":
                    kw["trim_end_ms"] = parse_duration(val)
                elif key == "end":
                    kw["end_ms"] = parse_time(val)
                elif key == "normalize":
                    kw["normalize"] = True
                    kw["normalize_target_dbfs"] = float(val)
                elif key == "compress":
                    kw["compress"] = True
                    _parse_compress(val, kw, lineno)
                elif key == "highpass":
                    kw["highpass_hz"] = int(float(val))
                elif key == "lowpass":
                    kw["lowpass_hz"] = int(float(val))
                elif key == "pan":
                    pan_val = float(val)
                    if not -1.0 <= pan_val <= 1.0:
                        raise ValueError(f"Line {lineno}: pan must be between -1.0 and 1.0")
                    kw["pan"] = pan_val
                elif key == "speed":
                    speed_val = float(val)
                    if speed_val <= 0:
                        raise ValueError(f"Line {lineno}: speed must be > 0")
                    kw["speed"] = speed_val
                elif key == "strip_silence":
                    kw["strip_silence"] = True
                    _parse_strip_silence(val, kw, lineno)
                else:
                    raise ValueError(f"Line {lineno}: unknown option {key!r}")

            events.append(
                TrackEvent(
                    timestamp_ms=timestamp_ms,
                    track_name=track_name,
                    filepath=str(audio_path),
                    **kw,
                )
            )

    return sorted(events, key=lambda e: e.timestamp_ms)


def _parse_compress(val: str, kw: dict, lineno: int) -> None:
    """Parse compress=threshold:ratio:attack:release into kw dict."""
    parts = val.split(":")
    if len(parts) != 4:
        raise ValueError(
            f"Line {lineno}: compress expects threshold:ratio:attack_ms:release_ms, got {val!r}"
        )
    kw["compress_threshold"] = float(parts[0])
    kw["compress_ratio"] = float(parts[1])
    kw["compress_attack_ms"] = float(parts[2])
    kw["compress_release_ms"] = float(parts[3])


def _parse_strip_silence(val: str, kw: dict, lineno: int) -> None:
    """Parse strip_silence=thresh:min_len into kw dict."""
    parts = val.split(":")
    if len(parts) != 2:
        raise ValueError(
            f"Line {lineno}: strip_silence expects thresh_dbfs:min_len_ms, got {val!r}"
        )
    kw["strip_silence_thresh_dbfs"] = float(parts[0])
    kw["strip_silence_min_len_ms"] = int(parts[1])
