"""Parser-level tests for the MM:SS time convention.

These tests only parse .mix files and time strings, so they need neither ffmpeg
nor any audio fixture. They lock in that every time value (timestamp, end,
trim_start, trim_end, fades) accepts the MM:SS clock format.
"""
from __future__ import annotations

from pathlib import Path

from dsl_audio.models import parse_duration, parse_time
from dsl_audio.parser import parse_mix_file


def test_parse_duration_accepts_mm_ss():
    assert parse_duration("00:02") == 2000
    assert parse_duration("01:45") == 105000
    assert parse_duration("12:07") == 727000


def test_parse_duration_backward_compatible():
    # Legacy suffix forms still work.
    assert parse_duration("2s") == 2000
    assert parse_duration("500ms") == 500
    assert parse_duration("1.5s") == 1500
    assert parse_duration("30") == 30000


def test_parse_time_mm_ss():
    assert parse_time("00:30") == 30000
    assert parse_time("01:45") == 105000


def test_mix_line_uses_mm_ss_everywhere(tmp_path: Path):
    mix = tmp_path / "clip.mix"
    mix.write_text(
        '01:45  clip  "speech.mp3"  trim_start=00:30  trim_end=00:05  '
        "fade_in=00:02  fade_out=00:02  end=02:23\n"
    )
    events = parse_mix_file(mix)
    assert len(events) == 1
    ev = events[0]
    assert ev.timestamp_ms == 105000   # 01:45
    assert ev.trim_start_ms == 30000   # 00:30
    assert ev.trim_end_ms == 5000      # 00:05
    assert ev.fade_in_ms == 2000       # 00:02
    assert ev.fade_out_ms == 2000      # 00:02
    assert ev.end_ms == 143000         # 02:23
