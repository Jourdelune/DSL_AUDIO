"""Audio rendering engine.

Signal processing chain applied to every clip (in order):
    1. Clip boundaries  (trim_start / trim_end / end)
    2. Strip silence    (remove leading/trailing silence)
    3. Speed change     (resampling; also shifts pitch)
    4. Mono mix-down    (mono)
    5. High-pass filter (highpass)
    6. Low-pass filter  (lowpass)
    7. Compression      (compress)
    8. Normalization    (normalize / normalize_target_dbfs)
    9. Volume gain      (vol)
   10. Stereo pan       (pan)
   11. Reverse          (reverse)
   12. Fades            (fade_in / fade_out)  ← always last
"""
import math
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from pydub import AudioSegment
from pydub.effects import compress_dynamic_range, high_pass_filter, low_pass_filter, normalize
from pydub.silence import detect_leading_silence

from .media import load_audio_segment
from .models import TrackEvent

MAX_FFMPEG_AMIX_INPUTS = 1024
MAX_FFMPEG_ADELAY_MS = 90_000_000  # ffmpeg adelay practical limit (~25h)


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

    # 8. Normalization
    if event.normalize:
        if event.normalize_target_dbfs is None:
            # Peak normalization (headroom = 0.1 dB below 0 dBFS)
            seg = normalize(seg, headroom=0.1)
        else:
            # RMS normalization to target dBFS
            seg = _rms_normalize(seg, event.normalize_target_dbfs)

    # 9. Volume gain
    if event.vol != 1.0:
        db_change = -120.0 if event.vol <= 0 else 20 * math.log10(event.vol)
        seg = seg + db_change

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
    load_result: bool = True,
) -> Tuple[AudioSegment, Dict[int, int]]:
    """Render all TrackEvents into a single mixed audio file.

    Args:
        events:            Sorted list of TrackEvents from the parser.
        output_path:       Destination file.  Format inferred from extension.
        progress_callback: Optional (current, total, description) callback.
        load_result:       If True, reload output file and return it as AudioSegment.

    Returns:
        (final_segment, durations) where durations maps event index → clip duration ms.
        If load_result=False, final_segment is AudioSegment.empty() to avoid loading
        potentially very large output files in memory.
    """
    if not events:
        raise ValueError("No events to render")

    output_path = Path(output_path)
    durations: Dict[int, int] = {}
    total_steps = len(events) + 1

    with tempfile.TemporaryDirectory(prefix="dsl-audio-") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        prepared: List[Tuple[TrackEvent, Path]] = []

        for i, event in enumerate(events):
            if progress_callback:
                progress_callback(i, total_steps, f"Loading  {Path(event.filepath).name}")
            seg = _apply_event(event)
            durations[i] = len(seg)

            clip_path = temp_dir / f"clip_{i:05d}.wav"
            seg.export(str(clip_path), format="wav")
            prepared.append((event, clip_path))

        if progress_callback:
            progress_callback(len(events), total_steps, "Mixing / Exporting")
        _mix_with_ffmpeg(prepared, output_path)

    if progress_callback:
        progress_callback(total_steps, total_steps, "Done")

    if load_result:
        return load_audio_segment(output_path), durations
    return AudioSegment.empty(), durations


def _mix_with_ffmpeg(prepared: List[Tuple[TrackEvent, Path]], output_path: Path) -> None:
    """Mix pre-processed clips with ffmpeg using timestamp delays.

    Args:
        prepared: List of (event, temporary_wav_path) pairs.
        output_path: Final output media path.

    Raises:
        ValueError: If no clips are provided or ffmpeg filter limits are exceeded.
        RuntimeError: If ffmpeg is unavailable or the mix/export command fails.
    """
    if not prepared:
        raise ValueError("No prepared clips to mix")
    if len(prepared) > MAX_FFMPEG_AMIX_INPUTS:
        raise ValueError(
            f"Too many clips for ffmpeg amix (max {MAX_FFMPEG_AMIX_INPUTS} inputs). "
            "Please split your mix into smaller chunks."
        )

    cmd: List[str] = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for _, clip_path in prepared:
        cmd.extend(["-i", str(clip_path)])

    delayed_labels: List[str] = []
    filter_parts: List[str] = []
    for i, (event, _) in enumerate(prepared):
        if event.timestamp_ms > MAX_FFMPEG_ADELAY_MS:
            raise ValueError(
                f"Event at index {i} starts too late for ffmpeg adelay: "
                f"{event.timestamp_ms}ms (max {MAX_FFMPEG_ADELAY_MS}ms / 25h)."
            )
        out_label = f"a{i}"
        filter_parts.append(f"[{i}:a]adelay={event.timestamp_ms}:all=1[{out_label}]")
        delayed_labels.append(f"[{out_label}]")

    filter_parts.append(
        # normalize=0 keeps source levels unchanged; dropout_transition=0 avoids
        # extra crossfade-like smoothing when inputs start/stop over time.
        f"{''.join(delayed_labels)}amix=inputs={len(delayed_labels)}:normalize=0:dropout_transition=0[mix]"
    )
    filter_complex = ";".join(filter_parts)

    cmd.extend(["-filter_complex", filter_complex, "-map", "[mix]", str(output_path)])

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is required but was not found in PATH.") from exc
    except subprocess.CalledProcessError as exc:
        details = exc.stderr.strip() if exc.stderr else str(exc)
        raise RuntimeError(f"ffmpeg mix/export failed: {details}") from exc
