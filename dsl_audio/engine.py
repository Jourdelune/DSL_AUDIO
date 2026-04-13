"""Audio rendering engine.

Signal processing chain applied to every clip (in order):
    1. Clip boundaries  (trim_start / trim_end / end)
    2. Strip silence    (remove leading/trailing silence)
    3. Speed change     (resampling; also shifts pitch)
    4. Mono mix-down    (mono)
    5. High-pass filter (highpass)
    6. Low-pass filter  (lowpass)
    7. Compression      (compress)
    8. Volume gain      (vol)
    9. Normalization    (normalize / normalize_target_dbfs)
   10. Stereo pan       (pan)
   11. Reverse          (reverse)
   12. Fades            (fade_in / fade_out)  ← always last
"""
import math
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from pydub import AudioSegment
from pydub.effects import compress_dynamic_range, high_pass_filter, low_pass_filter, normalize
from pydub.silence import detect_leading_silence

from .media import load_audio_segment
from .models import TrackEvent


# ── Per-clip processing ───────────────────────────────────────────────────────

def _apply_event(event: TrackEvent) -> AudioSegment:
    """Load a file and run the full effect chain for one TrackEvent."""
    seg = load_audio_segment(event.filepath)

    # 1. Clip boundaries
    if event.trim_start_ms > 0:
        seg = seg[event.trim_start_ms:]
    if event.trim_end_ms is not None and event.trim_end_ms > 0:
        seg = seg[: len(seg) - event.trim_end_ms]
    if event.end_ms is not None:
        max_duration = event.end_ms - event.timestamp_ms
        if max_duration > 0:
            seg = seg[:max_duration]

    # 2. Strip leading/trailing silence
    if event.strip_silence:
        seg = _strip_silence(
            seg,
            silence_thresh=event.strip_silence_thresh_dbfs,
            min_silence_len=event.strip_silence_min_len_ms,
        )

    # 3. Speed change (resamples; shifts pitch proportionally)
    if event.speed is not None and event.speed != 1.0:
        seg = _change_speed(seg, event.speed)

    # 4. Mono mix-down
    if event.mono:
        seg = seg.set_channels(1)

    # 5. High-pass filter (removes rumble / low-frequency noise)
    if event.highpass_hz is not None:
        seg = high_pass_filter(seg, event.highpass_hz)

    # 6. Low-pass filter
    if event.lowpass_hz is not None:
        seg = low_pass_filter(seg, event.lowpass_hz)

    # 7. Dynamic range compression
    if event.compress:
        seg = compress_dynamic_range(
            seg,
            threshold=event.compress_threshold,
            ratio=event.compress_ratio,
            attack=event.compress_attack_ms,
            release=event.compress_release_ms,
        )

    # 8. Volume gain
    if event.vol != 1.0:
        db_change = -120.0 if event.vol <= 0 else 20 * math.log10(event.vol)
        seg = seg + db_change

    # 9. Normalization
    if event.normalize:
        if event.normalize_target_dbfs is None:
            # Peak normalization (headroom = 0.1 dB below 0 dBFS)
            seg = normalize(seg, headroom=0.1)
        else:
            # RMS normalization to target dBFS
            seg = _rms_normalize(seg, event.normalize_target_dbfs)

    # 10. Stereo pan
    if event.pan is not None:
        seg = seg.pan(event.pan)

    # 11. Reverse
    if event.reverse:
        seg = seg.reverse()

    # 12. Fades (always last so they shape the final envelope)
    if event.fade_in_ms > 0:
        seg = seg.fade_in(min(event.fade_in_ms, len(seg)))
    if event.fade_out_ms > 0:
        seg = seg.fade_out(min(event.fade_out_ms, len(seg)))

    return seg


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rms_normalize(seg: AudioSegment, target_dbfs: float) -> AudioSegment:
    """Normalize so the RMS level matches target_dbfs."""
    if seg.dBFS == float("-inf"):
        return seg  # silent clip, nothing to do
    change_db = target_dbfs - seg.dBFS
    return seg.apply_gain(change_db)


def _change_speed(seg: AudioSegment, speed: float) -> AudioSegment:
    """Change playback speed (and pitch) by resampling."""
    original_frame_rate = seg.frame_rate
    altered = seg._spawn(
        seg.raw_data,
        overrides={"frame_rate": int(original_frame_rate * speed)},
    )
    return altered.set_frame_rate(original_frame_rate)


def _strip_silence(
    seg: AudioSegment,
    silence_thresh: float = -40.0,
    min_silence_len: int = 500,
) -> AudioSegment:
    """Remove leading and trailing silence."""
    start_trim = detect_leading_silence(seg, silence_threshold=silence_thresh, chunk_size=10)
    end_trim = detect_leading_silence(seg.reverse(), silence_threshold=silence_thresh, chunk_size=10)
    duration = len(seg)
    trimmed_end = duration - end_trim
    if start_trim >= trimmed_end:
        return seg  # fully silent, return as-is
    return seg[start_trim:trimmed_end]


# ── Renderer ──────────────────────────────────────────────────────────────────

def render(
    events: List[TrackEvent],
    output_path: str | Path,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Tuple[AudioSegment, Dict[int, int]]:
    """Render all TrackEvents into a single mixed audio file.

    Args:
        events:            Sorted list of TrackEvents from the parser.
        output_path:       Destination file.  Format inferred from extension.
        progress_callback: Optional (current, total, description) callback.

    Returns:
        (final_segment, durations) where durations maps event index → clip duration ms.
    """
    if not events:
        raise ValueError("No events to render")

    output_path = Path(output_path)
    loaded: Dict[int, Tuple[TrackEvent, AudioSegment]] = {}
    durations: Dict[int, int] = {}

    for i, event in enumerate(events):
        if progress_callback:
            progress_callback(i, len(events), f"Loading  {Path(event.filepath).name}")
        seg = _apply_event(event)
        loaded[i] = (event, seg)
        durations[i] = len(seg)

    total_ms = max(event.timestamp_ms + durations[i] for i, (event, _) in loaded.items())
    result = AudioSegment.silent(duration=total_ms)

    for i, (event, seg) in loaded.items():
        if progress_callback:
            progress_callback(i, len(events), f"Mixing   {event.track_name}")
        result = result.overlay(seg, position=event.timestamp_ms)

    if progress_callback:
        progress_callback(len(events), len(events), "Exporting")

    fmt = output_path.suffix.lstrip(".").lower() or "mp3"
    result.export(str(output_path), format=fmt)

    return result, durations
