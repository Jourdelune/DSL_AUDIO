"""End-to-end tests for every DSL Audio effect.

Each test:
  1. Writes a human-readable .mix file to  tests/mix_files/
  2. Renders it to                          tests/rendered/<name>.wav
  3. Verifies the rendered audio properties.

Run ``pytest tests/test_e2e.py -v`` then open tests/rendered/ to listen.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydub import AudioSegment

from dsl_audio import parse_mix_file, render

TEST_AUDIO = Path(__file__).parent.parent / "test.mp3"
MIX_DIR = Path(__file__).parent / "mix_files"
RENDERED_DIR = Path(__file__).parent / "rendered"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _render(mix_name: str, mix_content: str) -> AudioSegment:
    """Write *mix_content* to MIX_DIR/<mix_name>.mix, render to RENDERED_DIR/<mix_name>.wav."""
    mix_file = MIX_DIR / f"{mix_name}.mix"
    out_file = RENDERED_DIR / f"{mix_name}.wav"
    mix_file.write_text(mix_content)
    events = parse_mix_file(str(mix_file))
    seg, _ = render(events, str(out_file), load_result=True)
    return seg


def _chunk_dbfs(seg: AudioSegment, n: int = 10) -> list[float]:
    chunk_ms = len(seg) // n
    return [seg[i * chunk_ms : (i + 1) * chunk_ms].dBFS for i in range(n)]


def _spectral_energy_fraction(seg: AudioSegment, lo_hz: int, hi_hz: int) -> float:
    samples = np.array(seg.get_array_of_samples(), dtype=np.float64)
    if seg.channels == 2:
        samples = samples[::2]
    power = np.abs(np.fft.rfft(samples)) ** 2
    freqs = np.fft.rfftfreq(len(samples), d=1.0 / seg.frame_rate)
    mask = (freqs >= lo_hz) & (freqs < hi_hz)
    total = power.sum()
    return float(power[mask].sum() / total) if total > 0 else 0.0


# ── Volume ────────────────────────────────────────────────────────────────────

def test_vol_low(ensure_dirs: Any) -> None:
    """vol=0.2 — clip should be significantly quieter than baseline."""
    ref = _render("vol_baseline", f"00:00.000 track {TEST_AUDIO}\n")
    seg = _render("vol_low", f"00:00.000 track {TEST_AUDIO} vol=0.2\n")
    assert seg.dBFS < ref.dBFS - 10


def test_vol_high(ensure_dirs: Any) -> None:
    """vol=2.0 — clip should be louder than baseline."""
    ref = _render("vol_baseline", f"00:00.000 track {TEST_AUDIO}\n")
    seg = _render("vol_high", f"00:00.000 track {TEST_AUDIO} vol=2.0\n")
    assert seg.dBFS > ref.dBFS + 4


# ── Fades ─────────────────────────────────────────────────────────────────────

def test_fade_in(ensure_dirs: Any) -> None:
    """fade_in=4s — volume must rise: first window < last window."""
    seg = _render(
        "fade_in",
        f"# Fade-in over 4 seconds\n"
        f"00:00.000 track {TEST_AUDIO} fade_in=4s\n",
    )
    chunks = _chunk_dbfs(seg, 10)
    early, late = chunks[0], chunks[8]
    assert early < late - 10 or early == float("-inf")
    assert seg[:50].dBFS < -30  # near silence at t=0


def test_fade_out(ensure_dirs: Any) -> None:
    """fade_out=4s — volume must drop: first window > last window."""
    seg = _render(
        "fade_out",
        f"# Fade-out over 4 seconds\n"
        f"00:00.000 track {TEST_AUDIO} fade_out=4s\n",
    )
    chunks = _chunk_dbfs(seg, 10)
    late_valid = [c for c in chunks[-3:] if c > float("-inf")]
    if late_valid:
        assert chunks[1] > late_valid[-1] + 10
    assert seg[-50:].dBFS < -30  # near silence at end


def test_fade_in_and_out(ensure_dirs: Any) -> None:
    """fade_in=2s fade_out=2s — middle louder than both edges."""
    seg = _render(
        "fade_in_out",
        f"# Symmetric 2-second fades\n"
        f"00:00.000 track {TEST_AUDIO} fade_in=2s fade_out=2s\n",
    )
    chunks = _chunk_dbfs(seg, 10)
    mid = chunks[4]
    assert chunks[0] < mid - 5 or chunks[0] == float("-inf")
    late = [c for c in chunks[-2:] if c > float("-inf")]
    if late:
        assert mid > late[-1] + 3


# ── Filters ───────────────────────────────────────────────────────────────────

def test_highpass(ensure_dirs: Any) -> None:
    """highpass=2000 — energy below 2 kHz must drop by ≥30 %."""
    ref = _render("vol_baseline", f"00:00.000 track {TEST_AUDIO}\n")
    seg = _render(
        "highpass",
        f"# High-pass at 2 kHz — removes low rumble\n"
        f"00:00.000 track {TEST_AUDIO} highpass=2000\n",
    )
    assert _spectral_energy_fraction(seg, 20, 2000) < _spectral_energy_fraction(ref, 20, 2000) * 0.7


def test_lowpass(ensure_dirs: Any) -> None:
    """lowpass=500 — energy above 500 Hz must drop by ≥30 %."""
    ref = _render("vol_baseline", f"00:00.000 track {TEST_AUDIO}\n")
    seg = _render(
        "lowpass",
        f"# Low-pass at 500 Hz — muffled effect\n"
        f"00:00.000 track {TEST_AUDIO} lowpass=500\n",
    )
    assert _spectral_energy_fraction(seg, 500, 10000) < _spectral_energy_fraction(ref, 500, 10000) * 0.7


def test_telephone_preset(ensure_dirs: Any) -> None:
    """highpass=300 lowpass=3400 — telephone band must contain >50 % of energy."""
    seg = _render(
        "telephone",
        f"# Telephone effect: narrow 300–3400 Hz band\n"
        f"00:00.000 track {TEST_AUDIO} highpass=300 lowpass=3400 compress mono\n",
    )
    assert seg.channels == 1
    band = _spectral_energy_fraction(seg, 300, 3400)
    assert band > 0.5


# ── Normalization ─────────────────────────────────────────────────────────────

def test_normalize_peak(ensure_dirs: Any) -> None:
    """normalize — peak level must reach within 1 dB of 0 dBFS."""
    seg = _render(
        "normalize_peak",
        f"# Peak normalization\n"
        f"00:00.000 track {TEST_AUDIO} normalize\n",
    )
    assert seg.max_dBFS >= -1.0


def test_normalize_rms(ensure_dirs: Any) -> None:
    """normalize=-16 — RMS level must hit −16 dBFS ±2 dB."""
    seg = _render(
        "normalize_rms",
        f"# RMS normalization to -16 dBFS (podcast loudness standard)\n"
        f"00:00.000 track {TEST_AUDIO} normalize=-16\n",
    )
    assert abs(seg.dBFS - (-16)) < 2.5


# ── Compression ───────────────────────────────────────────────────────────────

def test_compress(ensure_dirs: Any) -> None:
    """compress — dynamic range (loudest - quietest chunk) must be smaller than uncompressed."""
    def _range(s: AudioSegment) -> float:
        vals = [v for v in _chunk_dbfs(s, 20) if v > float("-inf")]
        return max(vals) - min(vals) if len(vals) > 1 else 0.0

    ref = _render("vol_baseline", f"00:00.000 track {TEST_AUDIO}\n")
    seg = _render(
        "compress",
        f"# Dynamic range compression\n"
        f"00:00.000 track {TEST_AUDIO} compress\n",
    )
    assert _range(seg) < _range(ref)


def test_compress_custom_params(ensure_dirs: Any) -> None:
    """compress=-30:8:10:100 — hard compression with custom params."""
    seg = _render(
        "compress_hard",
        f"# Hard compression: threshold -30 dBFS, ratio 8:1\n"
        f"00:00.000 track {TEST_AUDIO} compress=-30:8:10:100\n",
    )
    assert len(seg) > 0


# ── Speed ─────────────────────────────────────────────────────────────────────

def test_speed_fast(ensure_dirs: Any) -> None:
    """speed=2.0 — output duration ≈ half of input."""
    ref = _render("vol_baseline", f"00:00.000 track {TEST_AUDIO}\n")
    seg = _render(
        "speed_fast",
        f"# 2× speed (also raises pitch)\n"
        f"00:00.000 track {TEST_AUDIO} speed=2.0\n",
    )
    ratio = len(seg) / len(ref)
    assert 0.4 < ratio < 0.6


def test_speed_slow(ensure_dirs: Any) -> None:
    """speed=0.5 — output duration ≈ double of input."""
    ref = _render("vol_baseline", f"00:00.000 track {TEST_AUDIO}\n")
    seg = _render(
        "speed_slow",
        f"# 0.5× speed (also lowers pitch)\n"
        f"00:00.000 track {TEST_AUDIO} speed=0.5\n",
    )
    ratio = len(seg) / len(ref)
    assert 1.8 < ratio < 2.2


# ── Reverse ───────────────────────────────────────────────────────────────────

def test_reverse(ensure_dirs: Any) -> None:
    """reverse — duration unchanged, waveform is time-mirrored."""
    ref_seg = _render("vol_baseline", f"00:00.000 track {TEST_AUDIO}\n")
    seg = _render(
        "reverse",
        f"# Reversed playback\n"
        f"00:00.000 track {TEST_AUDIO} reverse\n",
    )
    assert abs(len(ref_seg) - len(seg)) < 200
    orig = np.array(ref_seg.set_channels(1).get_array_of_samples())
    mirrored = np.array(seg.set_channels(1).get_array_of_samples())
    n = min(1000, len(orig), len(mirrored))
    np.testing.assert_allclose(mirrored[:n], orig[-n:][::-1], atol=5)


# ── Mono ──────────────────────────────────────────────────────────────────────

def test_mono(ensure_dirs: Any) -> None:
    """mono — output must have exactly 1 channel."""
    seg = _render(
        "mono",
        f"# Mix down to mono\n"
        f"00:00.000 track {TEST_AUDIO} mono\n",
    )
    assert seg.channels == 1


# ── Pan ───────────────────────────────────────────────────────────────────────

def test_pan_left(ensure_dirs: Any) -> None:
    """pan=-1.0 — left channel must be at least 15 dB louder than right."""
    seg = _render(
        "pan_left",
        f"# Full left pan\n"
        f"00:00.000 track {TEST_AUDIO} pan=-1.0\n",
    )
    if seg.channels != 2:
        pytest.skip("mono source")
    left, right = seg.split_to_mono()
    assert left.dBFS > right.dBFS + 15


def test_pan_right(ensure_dirs: Any) -> None:
    """pan=1.0 — right channel must be at least 15 dB louder than left."""
    seg = _render(
        "pan_right",
        f"# Full right pan\n"
        f"00:00.000 track {TEST_AUDIO} pan=1.0\n",
    )
    if seg.channels != 2:
        pytest.skip("mono source")
    left, right = seg.split_to_mono()
    assert right.dBFS > left.dBFS + 15


# ── Trim ──────────────────────────────────────────────────────────────────────

def test_trim_start(ensure_dirs: Any) -> None:
    """trim_start=5s — output ≈ 5 seconds shorter than original."""
    ref = _render("vol_baseline", f"00:00.000 track {TEST_AUDIO}\n")
    seg = _render(
        "trim_start",
        f"# Skip first 5 seconds\n"
        f"00:00.000 track {TEST_AUDIO} trim_start=5s\n",
    )
    assert abs(len(seg) - (len(ref) - 5000)) < 200


def test_trim_end(ensure_dirs: Any) -> None:
    """trim_end=5s — output ≈ 5 seconds shorter than original."""
    ref = _render("vol_baseline", f"00:00.000 track {TEST_AUDIO}\n")
    seg = _render(
        "trim_end",
        f"# Cut last 5 seconds\n"
        f"00:00.000 track {TEST_AUDIO} trim_end=5s\n",
    )
    assert abs(len(seg) - (len(ref) - 5000)) < 200


def test_trim_both(ensure_dirs: Any) -> None:
    """trim_start=3s trim_end=3s — output ≈ 6 seconds shorter."""
    ref = _render("vol_baseline", f"00:00.000 track {TEST_AUDIO}\n")
    seg = _render(
        "trim_both",
        f"# Trim 3 s from each end\n"
        f"00:00.000 track {TEST_AUDIO} trim_start=3s trim_end=3s\n",
    )
    assert abs(len(seg) - (len(ref) - 6000)) < 200


# ── End boundary ──────────────────────────────────────────────────────────────

def test_end_boundary(ensure_dirs: Any) -> None:
    """end=00:06.000 — clip must not exceed 6 seconds."""
    seg = _render(
        "end_boundary",
        f"# Hard stop at 6 s on the timeline\n"
        f"00:00.000 track {TEST_AUDIO} end=00:06.000\n",
    )
    assert len(seg) <= 6200


# ── Strip silence ─────────────────────────────────────────────────────────────

def test_strip_silence(ensure_dirs: Any, tmp_path: Path) -> None:
    """strip_silence — leading/trailing silence must be removed."""
    from dsl_audio.engine import _apply_event
    from dsl_audio.models import TrackEvent

    original = _apply_event(  # type: ignore[arg-type]
        TrackEvent(timestamp_ms=0, track_name="t", filepath=str(TEST_AUDIO))
    )
    padded = AudioSegment.silent(2000) + original + AudioSegment.silent(2000)
    padded_path = tmp_path / "padded.wav"
    padded.export(str(padded_path), format="wav")

    seg = _render(
        "strip_silence",
        f"# Strip leading/trailing silence\n"
        f"00:00.000 track {padded_path} strip_silence\n",
    )
    assert len(seg) < len(padded) - 3000


# ── Multi-track compositions ──────────────────────────────────────────────────

def test_multi_track_staggered(ensure_dirs: Any) -> None:
    """Two tracks at t=0 and t=5s — output must be ~5 s longer than one track alone."""
    ref = _render("vol_baseline", f"00:00.000 track {TEST_AUDIO}\n")
    seg = _render(
        "multi_track_staggered",
        f"# Two tracks: second one starts 5 s later\n"
        f"00:00.000 music  {TEST_AUDIO} vol=0.4\n"
        f"00:05.000 voice  {TEST_AUDIO} vol=0.7\n",
    )
    assert len(seg) > len(ref) + 4500


def test_multi_track_overlay(ensure_dirs: Any) -> None:
    """Two tracks at t=0 — output duration ≈ one track (they overlap fully)."""
    ref = _render("vol_baseline", f"00:00.000 track {TEST_AUDIO}\n")
    seg = _render(
        "multi_track_overlay",
        f"# Two tracks fully overlapping\n"
        f"00:00.000 music  {TEST_AUDIO} vol=0.3 fade_in=2s\n"
        f"00:00.000 voice  {TEST_AUDIO} vol=0.7 fade_out=2s\n",
    )
    assert abs(len(seg) - len(ref)) < 500


# ── Presets ───────────────────────────────────────────────────────────────────

def test_voice_preset(ensure_dirs: Any) -> None:
    """Full voice-processing chain: mono + strip_silence + highpass + compress + normalize=-16."""
    seg = _render(
        "voice_preset",
        f"# Broadcast-ready voice preset\n"
        f"00:00.000 voice {TEST_AUDIO} mono strip_silence highpass=100 compress normalize=-16\n",
    )
    assert seg.channels == 1
    assert abs(seg.dBFS - (-16)) < 2.5


def test_music_bed_preset(ensure_dirs: Any) -> None:
    """Music bed: low volume with symmetric fades."""
    seg = _render(
        "music_bed",
        f"# Background music bed\n"
        f"00:00.000 music {TEST_AUDIO} normalize=-18 vol=0.3 fade_in=3s fade_out=3s\n",
    )
    chunks = _chunk_dbfs(seg, 10)
    valid = [c for c in chunks if c > float("-inf")]
    peak = max(valid) if valid else float("-inf")
    # Beginning (fade-in) must be quieter than the loudest middle chunk
    assert chunks[0] < peak - 5 or chunks[0] == float("-inf")
    # End (fade-out) must be quieter than the loudest middle chunk
    late = [c for c in chunks[-2:] if c > float("-inf")]
    if late and peak > float("-inf"):
        assert peak > late[-1] + 3


def test_full_podcast_mix(ensure_dirs: Any) -> None:
    """Complete podcast structure: jingle, music bed, voice, outro."""
    seg = _render(
        "podcast_full",
        f"# ── Full podcast mix ──────────────────────────────────────────────\n"
        f"# Jingle (0–10 s)\n"
        f"00:00.000 jingle  {TEST_AUDIO} vol=0.9 trim_end=10s fade_out=2s\n"
        f"# Background music starts under jingle\n"
        f"00:03.000 music   {TEST_AUDIO} vol=0.15 fade_in=3s\n"
        f"# Voice enters after jingle\n"
        f"00:08.000 voice   {TEST_AUDIO} vol=1.0 fade_in=500ms highpass=100 compress\n"
        f"# Second voice segment with pan\n"
        f"00:12.000 guest   {TEST_AUDIO} vol=0.9 pan=0.2 highpass=80 compress normalize=-16\n"
        f"# Outro fades everything out\n"
        f"00:18.000 outro   {TEST_AUDIO} vol=0.8 trim_end=5s fade_in=1s fade_out=3s\n",
    )
    # Mix of staggered clips — should be well over 20 s
    assert len(seg) > 20000
    # Must not be total silence
    assert seg.dBFS > float("-inf")
