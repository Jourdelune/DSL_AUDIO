"""Pytest suite for all DSL Audio effects.

Per-effect unit tests call ``_apply_event`` directly so each test is isolated
from the parser and ffmpeg mixer.  Mix-file integration tests exercise the full
``parse_mix_file → render`` pipeline.

Test audio: test.mp3 (20 s, stereo, 48 kHz) located at the repo root.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydub import AudioSegment

from dsl_audio import parse_mix_file, render
from dsl_audio.engine import _apply_event
from dsl_audio.models import TrackEvent

TEST_AUDIO = Path(__file__).parent.parent / "test.mp3"


# ── Shared helpers ────────────────────────────────────────────────────────────

def _e(**kwargs: Any) -> TrackEvent:
    """Return a TrackEvent pointing at TEST_AUDIO with keyword overrides."""
    base: dict[str, Any] = dict(timestamp_ms=0, track_name="test", filepath=str(TEST_AUDIO))
    base.update(kwargs)
    return TrackEvent(**base)


def _chunk_dbfs(seg: AudioSegment, n: int = 10) -> list[float]:
    """Split *seg* into *n* equal-duration windows and return dBFS for each."""
    chunk_ms = len(seg) // n
    return [seg[i * chunk_ms : (i + 1) * chunk_ms].dBFS for i in range(n)]


def _spectral_energy_fraction(seg: AudioSegment, lo_hz: int, hi_hz: int) -> float:
    """Fraction of total FFT power in [lo_hz, hi_hz) using the left (or only) channel."""
    samples = np.array(seg.get_array_of_samples(), dtype=np.float64)
    if seg.channels == 2:
        samples = samples[::2]
    power = np.abs(np.fft.rfft(samples)) ** 2
    freqs = np.fft.rfftfreq(len(samples), d=1.0 / seg.frame_rate)
    mask = (freqs >= lo_hz) & (freqs < hi_hz)
    total = power.sum()
    return float(power[mask].sum() / total) if total > 0 else 0.0


# ── Volume ────────────────────────────────────────────────────────────────────

class TestVolume:
    def test_low_vol_is_quieter(self):
        ref = _apply_event(_e())
        quiet = _apply_event(_e(vol=0.25))
        assert quiet.dBFS < ref.dBFS - 6

    def test_high_vol_is_louder(self):
        ref = _apply_event(_e())
        loud = _apply_event(_e(vol=2.0))
        assert loud.dBFS > ref.dBFS + 4

    def test_vol_zero_produces_silence(self):
        seg = _apply_event(_e(vol=0.0))
        assert seg.dBFS == float("-inf") or seg.dBFS < -80


# ── Fade-in ───────────────────────────────────────────────────────────────────

class TestFadeIn:
    def test_volume_rises_from_start_to_end(self):
        seg = _apply_event(_e(fade_in_ms=4000))
        chunks = _chunk_dbfs(seg, 10)
        early, late = chunks[0], chunks[8]
        assert early < late - 10 or early == float("-inf")

    def test_very_beginning_is_near_silence(self):
        seg = _apply_event(_e(fade_in_ms=5000))
        assert seg[:50].dBFS < -30

    def test_after_fade_region_is_at_normal_level(self):
        ref = _apply_event(_e())
        seg = _apply_event(_e(fade_in_ms=2000))
        # After the 2 s fade, levels should be close to the reference
        ref_mid = ref[5000:8000].dBFS
        seg_mid = seg[5000:8000].dBFS
        assert abs(seg_mid - ref_mid) < 3


# ── Fade-out ──────────────────────────────────────────────────────────────────

class TestFadeOut:
    def test_volume_drops_toward_end(self):
        seg = _apply_event(_e(fade_out_ms=4000))
        chunks = _chunk_dbfs(seg, 10)
        early = chunks[1]
        late_valid = [c for c in chunks[-3:] if c > float("-inf")]
        if late_valid:
            assert early > late_valid[-1] + 10

    def test_very_end_is_near_silence(self):
        seg = _apply_event(_e(fade_out_ms=5000))
        assert seg[-50:].dBFS < -30

    def test_before_fade_region_is_at_normal_level(self):
        ref = _apply_event(_e())
        seg = _apply_event(_e(fade_out_ms=2000))
        ref_mid = ref[3000:6000].dBFS
        seg_mid = seg[3000:6000].dBFS
        assert abs(seg_mid - ref_mid) < 3


# ── Highpass filter ───────────────────────────────────────────────────────────

class TestHighpass:
    def test_reduces_low_frequency_energy(self):
        ref = _apply_event(_e())
        filtered = _apply_event(_e(highpass_hz=2000))
        ref_low = _spectral_energy_fraction(ref, 20, 2000)
        flt_low = _spectral_energy_fraction(filtered, 20, 2000)
        assert flt_low < ref_low * 0.7

    def test_preserves_high_frequency_energy(self):
        ref = _apply_event(_e())
        filtered = _apply_event(_e(highpass_hz=200))
        ref_hi = _spectral_energy_fraction(ref, 3000, 12000)
        flt_hi = _spectral_energy_fraction(filtered, 3000, 12000)
        assert flt_hi > ref_hi * 0.5


# ── Lowpass filter ────────────────────────────────────────────────────────────

class TestLowpass:
    def test_reduces_high_frequency_energy(self):
        ref = _apply_event(_e())
        filtered = _apply_event(_e(lowpass_hz=500))
        ref_hi = _spectral_energy_fraction(ref, 500, 10000)
        flt_hi = _spectral_energy_fraction(filtered, 500, 10000)
        assert flt_hi < ref_hi * 0.7

    def test_preserves_low_frequency_energy(self):
        ref = _apply_event(_e())
        filtered = _apply_event(_e(lowpass_hz=4000))
        ref_lo = _spectral_energy_fraction(ref, 20, 500)
        flt_lo = _spectral_energy_fraction(filtered, 20, 500)
        assert flt_lo > ref_lo * 0.5


# ── Normalization ─────────────────────────────────────────────────────────────

class TestNormalize:
    def test_peak_normalize_pushes_peak_near_zero_dbfs(self):
        seg = _apply_event(_e(normalize=True))
        assert seg.max_dBFS >= -1.0

    def test_rms_normalize_hits_target_dbfs(self):
        target = -18.0
        seg = _apply_event(_e(normalize=True, normalize_target_dbfs=target))
        assert abs(seg.dBFS - target) < 2.0

    def test_rms_normalize_different_targets_produce_different_levels(self):
        loud = _apply_event(_e(normalize=True, normalize_target_dbfs=-12.0))
        quiet = _apply_event(_e(normalize=True, normalize_target_dbfs=-24.0))
        assert loud.dBFS > quiet.dBFS + 8


# ── Compression ───────────────────────────────────────────────────────────────

class TestCompression:
    def test_reduces_dynamic_range(self):
        def _range(seg: AudioSegment) -> float:
            vals = [v for v in _chunk_dbfs(seg, 20) if v > float("-inf")]
            return max(vals) - min(vals) if len(vals) > 1 else 0.0

        ref = _apply_event(_e())
        compressed = _apply_event(_e(compress=True))
        assert _range(compressed) < _range(ref)

    def test_custom_params_accepted(self):
        seg = _apply_event(
            _e(compress=True, compress_threshold=-30.0, compress_ratio=8.0,
               compress_attack_ms=10.0, compress_release_ms=100.0)
        )
        assert len(seg) > 0


# ── Speed ─────────────────────────────────────────────────────────────────────

class TestSpeed:
    def test_double_speed_halves_duration(self):
        ref = _apply_event(_e())
        fast = _apply_event(_e(speed=2.0))
        assert 0.4 < len(fast) / len(ref) < 0.6

    def test_half_speed_doubles_duration(self):
        ref = _apply_event(_e())
        slow = _apply_event(_e(speed=0.5))
        assert 1.8 < len(slow) / len(ref) < 2.2

    def test_speed_one_is_unchanged(self):
        ref = _apply_event(_e())
        same = _apply_event(_e(speed=1.0))
        assert len(ref) == len(same)


# ── Reverse ───────────────────────────────────────────────────────────────────

class TestReverse:
    def test_same_duration_as_original(self):
        ref = _apply_event(_e())
        rev = _apply_event(_e(reverse=True))
        assert abs(len(ref) - len(rev)) < 50

    def test_waveform_is_time_mirrored(self):
        ref = _apply_event(_e()).set_channels(1)
        rev = _apply_event(_e(reverse=True)).set_channels(1)
        orig = np.array(ref.get_array_of_samples())
        mirrored = np.array(rev.get_array_of_samples())
        n = min(1000, len(orig), len(mirrored))
        np.testing.assert_allclose(mirrored[:n], orig[-n:][::-1], atol=5)

    def test_double_reverse_restores_original(self):
        ref = _apply_event(_e())
        double = _apply_event(_e(reverse=True)).reverse()
        orig = np.array(ref.set_channels(1).get_array_of_samples())
        back = np.array(double.set_channels(1).get_array_of_samples())
        n = min(len(orig), len(back))
        np.testing.assert_allclose(orig[:n], back[:n], atol=5)


# ── Mono ──────────────────────────────────────────────────────────────────────

class TestMono:
    def test_mono_produces_one_channel(self):
        seg = _apply_event(_e(mono=True))
        assert seg.channels == 1

    def test_without_mono_stereo_stays_stereo(self):
        seg = _apply_event(_e())
        assert seg.channels == 2  # test.mp3 is stereo


# ── Pan ───────────────────────────────────────────────────────────────────────

class TestPan:
    def test_full_left_pan_louder_on_left_channel(self):
        seg = _apply_event(_e(pan=-1.0))
        if seg.channels != 2:
            pytest.skip("mono source — pan test requires stereo")
        left, right = seg.split_to_mono()
        assert left.dBFS > right.dBFS + 15

    def test_full_right_pan_louder_on_right_channel(self):
        seg = _apply_event(_e(pan=1.0))
        if seg.channels != 2:
            pytest.skip("mono source — pan test requires stereo")
        left, right = seg.split_to_mono()
        assert right.dBFS > left.dBFS + 15

    def test_center_pan_balanced(self):
        seg = _apply_event(_e(pan=0.0))
        if seg.channels != 2:
            pytest.skip("mono source — pan test requires stereo")
        left, right = seg.split_to_mono()
        assert abs(left.dBFS - right.dBFS) < 3


# ── Trim ──────────────────────────────────────────────────────────────────────

class TestTrim:
    def test_trim_start_shortens_clip(self):
        ref = _apply_event(_e())
        trimmed = _apply_event(_e(trim_start_ms=3000))
        assert abs(len(trimmed) - (len(ref) - 3000)) < 100

    def test_trim_end_shortens_clip(self):
        ref = _apply_event(_e())
        trimmed = _apply_event(_e(trim_end_ms=3000))
        assert abs(len(trimmed) - (len(ref) - 3000)) < 100

    def test_trim_both_ends(self):
        ref = _apply_event(_e())
        trimmed = _apply_event(_e(trim_start_ms=2000, trim_end_ms=2000))
        assert abs(len(trimmed) - (len(ref) - 4000)) < 100

    def test_trim_start_removes_audio_from_beginning(self):
        ref = _apply_event(_e())
        trimmed = _apply_event(_e(trim_start_ms=3000))
        # The beginning of trimmed should match position 3s in the original
        orig_at_3s = np.array(ref[3000:3050].set_channels(1).get_array_of_samples())
        trim_start = np.array(trimmed[:50].set_channels(1).get_array_of_samples())
        n = min(len(orig_at_3s), len(trim_start))
        np.testing.assert_allclose(orig_at_3s[:n], trim_start[:n], atol=10)


# ── End boundary ──────────────────────────────────────────────────────────────

class TestEndBoundary:
    def test_end_ms_clips_duration(self):
        # start=0, end=5000ms → clip should be ≤5s
        seg = _apply_event(_e(end_ms=5000))
        assert len(seg) <= 5100

    def test_end_ms_shorter_than_original(self):
        ref = _apply_event(_e())
        clipped = _apply_event(_e(end_ms=5000))
        assert len(clipped) < len(ref) - 5000  # original is 20s, so much shorter


# ── Strip silence ─────────────────────────────────────────────────────────────

class TestStripSilence:
    def test_removes_leading_and_trailing_silence(self, tmp_path):
        original = _apply_event(_e())
        padded = AudioSegment.silent(2000) + original + AudioSegment.silent(2000)
        padded_path = str(tmp_path / "padded.wav")
        padded.export(padded_path, format="wav")

        stripped = _apply_event(_e(filepath=padded_path, strip_silence=True))
        assert len(stripped) < len(padded) - 3000

    def test_custom_threshold_params(self, tmp_path):
        original = _apply_event(_e())
        padded = AudioSegment.silent(1000) + original + AudioSegment.silent(1000)
        padded_path = str(tmp_path / "padded.wav")
        padded.export(padded_path, format="wav")

        stripped = _apply_event(
            _e(filepath=padded_path, strip_silence=True,
               strip_silence_thresh_dbfs=-35.0, strip_silence_min_len_ms=300)
        )
        assert len(stripped) < len(padded) - 1500


# ── Mix-file integration tests ────────────────────────────────────────────────

class TestMixFileRender:
    """Full pipeline: .mix content → parse_mix_file → render → AudioSegment."""

    @staticmethod
    def _render(mix_content: str, subdir: Path) -> AudioSegment:
        subdir.mkdir(parents=True, exist_ok=True)
        mix_file = subdir / "test.mix"
        mix_file.write_text(mix_content)
        out = subdir / "out.wav"
        events = parse_mix_file(str(mix_file))
        seg, _ = render(events, str(out), load_result=True)
        return seg

    def test_single_clip_renders(self, tmp_path):
        seg = self._render(f"00:00.000 t {TEST_AUDIO}\n", tmp_path)
        assert len(seg) > 0

    def test_fade_in_via_mix_file(self, tmp_path):
        seg = self._render(f"00:00.000 t {TEST_AUDIO} fade_in=4s\n", tmp_path)
        chunks = _chunk_dbfs(seg, 10)
        assert chunks[0] < chunks[7] - 10 or chunks[0] == float("-inf")

    def test_fade_out_via_mix_file(self, tmp_path):
        seg = self._render(f"00:00.000 t {TEST_AUDIO} fade_out=4s\n", tmp_path)
        chunks = _chunk_dbfs(seg, 10)
        late = [c for c in chunks[-3:] if c > float("-inf")]
        if late:
            assert chunks[1] > late[-1] + 8

    def test_vol_via_mix_file(self, tmp_path):
        loud = self._render(f"00:00.000 t {TEST_AUDIO} vol=2.0\n", tmp_path / "loud")
        quiet = self._render(f"00:00.000 t {TEST_AUDIO} vol=0.25\n", tmp_path / "quiet")
        assert loud.dBFS > quiet.dBFS + 10

    def test_normalize_rms_via_mix_file(self, tmp_path):
        seg = self._render(f"00:00.000 t {TEST_AUDIO} normalize=-16\n", tmp_path)
        assert abs(seg.dBFS - (-16)) < 3.0

    def test_mono_via_mix_file(self, tmp_path):
        seg = self._render(f"00:00.000 t {TEST_AUDIO} mono\n", tmp_path)
        assert seg.channels == 1

    def test_highpass_via_mix_file(self, tmp_path):
        ref = self._render(f"00:00.000 t {TEST_AUDIO}\n", tmp_path / "ref")
        flt = self._render(f"00:00.000 t {TEST_AUDIO} highpass=2000\n", tmp_path / "hp")
        assert _spectral_energy_fraction(flt, 20, 2000) < _spectral_energy_fraction(ref, 20, 2000) * 0.7

    def test_lowpass_via_mix_file(self, tmp_path):
        ref = self._render(f"00:00.000 t {TEST_AUDIO}\n", tmp_path / "ref")
        flt = self._render(f"00:00.000 t {TEST_AUDIO} lowpass=500\n", tmp_path / "lp")
        assert _spectral_energy_fraction(flt, 500, 10000) < _spectral_energy_fraction(ref, 500, 10000) * 0.7

    def test_speed_via_mix_file(self, tmp_path):
        ref = self._render(f"00:00.000 t {TEST_AUDIO}\n", tmp_path / "ref")
        fast = self._render(f"00:00.000 t {TEST_AUDIO} speed=2.0\n", tmp_path / "fast")
        assert len(fast) < len(ref) * 0.6

    def test_reverse_via_mix_file(self, tmp_path):
        ref = self._render(f"00:00.000 t {TEST_AUDIO}\n", tmp_path / "ref")
        rev = self._render(f"00:00.000 t {TEST_AUDIO} reverse\n", tmp_path / "rev")
        assert abs(len(ref) - len(rev)) < 200

    def test_trim_start_via_mix_file(self, tmp_path):
        ref = self._render(f"00:00.000 t {TEST_AUDIO}\n", tmp_path / "ref")
        trimmed = self._render(f"00:00.000 t {TEST_AUDIO} trim_start=3s\n", tmp_path / "trim")
        assert len(trimmed) < len(ref) - 2800

    def test_compress_via_mix_file(self, tmp_path):
        seg = self._render(f"00:00.000 t {TEST_AUDIO} compress\n", tmp_path)
        assert len(seg) > 0

    def test_pan_left_via_mix_file(self, tmp_path):
        seg = self._render(f"00:00.000 t {TEST_AUDIO} pan=-1.0\n", tmp_path)
        if seg.channels == 2:
            left, right = seg.split_to_mono()
            assert left.dBFS > right.dBFS + 10

    def test_two_tracks_staggered_in_time(self, tmp_path):
        content = (
            f"00:00.000 t1 {TEST_AUDIO} vol=0.5\n"
            f"00:05.000 t2 {TEST_AUDIO} vol=0.5\n"
        )
        seg = self._render(content, tmp_path)
        ref = self._render(f"00:00.000 t {TEST_AUDIO} vol=0.5\n", tmp_path / "ref")
        # Second track delayed by 5s → output should be ~5s longer
        assert len(seg) > len(ref) + 4500

    def test_combined_effects_voice_preset(self, tmp_path):
        content = f"00:00.000 voice {TEST_AUDIO} mono strip_silence highpass=100 compress normalize=-16\n"
        seg = self._render(content, tmp_path)
        assert seg.channels == 1
        assert abs(seg.dBFS - (-16)) < 3.0

    def test_combined_effects_telephone_preset(self, tmp_path):
        content = f"00:00.000 tel {TEST_AUDIO} highpass=300 lowpass=3400 compress normalize=-16 mono\n"
        seg = self._render(content, tmp_path)
        assert seg.channels == 1
        # Most energy should be in the 300–3400 Hz telephone band
        band = _spectral_energy_fraction(seg, 300, 3400)
        assert band > 0.5

    def test_combined_fade_and_vol(self, tmp_path):
        seg = self._render(
            f"00:00.000 t {TEST_AUDIO} vol=0.5 fade_in=2s fade_out=2s\n", tmp_path
        )
        chunks = _chunk_dbfs(seg, 10)
        # start and end should be quieter than the middle
        assert chunks[0] < chunks[4] - 5 or chunks[0] == float("-inf")
        late = [c for c in chunks[-2:] if c > float("-inf")]
        if late:
            assert chunks[4] > late[-1] + 3
