---
name: podcast-builder
description: Build an immersive, professionally produced podcast episode with voice cloning, background music, sound effects, and audio montage using ffmpeg-python. Use this skill when you need to produce a rich, immersive audio experience.
---


## What this tool does

`dsl-audio` compiles a plain-text `.mix` file into a single mixed audio file (podcast, soundscape, etc.). It overlays multiple audio clips on a shared timeline, applies per-clip effects, and exports the result.

---

## Installation

```bash
pip install git+https://github.com/Jourdelune/DSL_AUDIO.git
```

Requires `ffmpeg` on PATH.

---

## CLI commands

### Render a mix

```bash
dsl-audio render <mixfile.mix> [--output <out.mp3>] [--preview] [--no-timeline] [--width N]
```

- `--preview` / `-p` — show timeline + table, skip rendering (fast sanity check)
- `--output` / `-o` — default is `<mixfile>.mp3`

### Inspect audio files

```bash
dsl-audio get file1.mp3 [file2.wav ...]
```

Returns: filename, duration (MM:SS.mmm), format, channels, sample rate, bit depth, file size.

---

## .mix file format

### Grammar (EBNF)

```
mix_file   ::= (line NEWLINE)*
line       ::= comment | blank | event
comment    ::= '#' <rest of line>
blank      ::= <whitespace only>
event      ::= timestamp SPACE track_name SPACE filepath (SPACE option)* (SPACE '#' <comment>)?
timestamp  ::= HH ':' MM ':' SS ['.' mmm]
             | MM ':' SS ['.' mmm]
             | SS ['.' mmm]
track_name ::= <identifier, no spaces>
filepath   ::= <unquoted path> | '"' <path with spaces> '"'
option     ::= flag | key '=' value
flag       ::= 'normalize' | 'compress' | 'strip_silence' | 'mono' | 'reverse'
key        ::= <option name below>
value      ::= <string>
```

### Complete options table

| Option | Type | Default | Description |
|---|---|---|---|
| `vol` | float | `1.0` | Volume multiplier. Linear: `0.5`=−6 dB, `2.0`=+6 dB |
| `fade_in` | duration | `0` | Fade-in length. Format: `2s` or `500ms` |
| `fade_out` | duration | `0` | Fade-out length |
| `trim_start` | duration | `0` | Skip first N ms/s of the clip |
| `trim_end` | duration | `0` | Cut last N ms/s of the clip |
| `end` | timestamp | — | Stop clip at absolute timeline position |
| `normalize` | flag | off | Peak-normalize to −0.1 dBFS |
| `normalize` | float | — | `normalize=-16` → RMS-normalize to target dBFS |
| `compress` | flag | off | Compress: threshold −20, ratio 4:1, attack 5 ms, release 50 ms |
| `compress` | `T:R:A:Rel` | — | Custom compress: `threshold_dBFS:ratio:attack_ms:release_ms` |
| `highpass` | int (Hz) | — | High-pass filter cutoff |
| `lowpass` | int (Hz) | — | Low-pass filter cutoff |
| `pan` | float [−1, 1] | — | Stereo pan: −1.0=left, 0=center, 1.0=right |
| `speed` | float | — | Speed multiplier (also shifts pitch) |
| `strip_silence` | flag | off | Remove leading/trailing silence (−40 dBFS, 500 ms) |
| `strip_silence` | `T:L` | — | Custom: `threshold_dBFS:min_silence_ms` |
| `mono` | flag | off | Mix down to mono before effects |
| `reverse` | flag | off | Reverse the clip |

### Signal processing chain (fixed order)

```
1.  trim_start / trim_end / end    (clip boundaries)
2.  strip_silence                  (cleanup)
3.  speed                          (resampling)
4.  mono                           (channel reduction)
5.  highpass                       (EQ low cut)
6.  lowpass                        (EQ high cut)
7.  compress                       (dynamics)
8.  vol                            (gain)
9.  normalize                      (leveling)
10. pan                            (spatial)
11. reverse                        (creative)
12. fade_in / fade_out             (always last)
```

---

## Podcast voice preset (recommended defaults)

Apply to every voice/speech clip:

```
mono  strip_silence  highpass=100  compress  normalize=-16
```

Apply to every music bed:

```
normalize=-18  fade_in=2s  fade_out=3s
```

---

## Examples

### Minimal overlay

```
00:00.000  music  background.mp3  vol=0.3
00:05.000  voice  take01.mp3
```

### Full podcast episode structure

```
# INTRO
00:00.000  jingle  jingle.mp3             vol=0.9  fade_out=3s
00:00.000  music   bg.mp3                 vol=0.2  fade_in=2s  normalize=-18

# SEGMENT 1 — host speaks over ducked music
00:08.000  host    host_intro.mp3         mono  strip_silence  highpass=100  compress  normalize=-16
00:08.000  music   bg.mp3                 vol=0.07

# SEGMENT 2 — two guests, stereo image
02:00.000  guest1  guest_alice.mp3        mono  strip_silence  highpass=80  compress  normalize=-16  pan=-0.2
02:00.000  guest2  guest_bob.mp3          mono  strip_silence  highpass=80  compress  normalize=-16  pan=0.2
02:00.000  music   bg.mp3                 vol=0.04

# OUTRO
15:00.000  host    host_outro.mp3         mono  strip_silence  highpass=100  compress  normalize=-16  fade_out=2s
15:00.000  music   bg.mp3                 vol=0.2  fade_in=3s  fade_out=8s
15:20.000  jingle  jingle.mp3             vol=0.9  fade_in=2s
```

### SFX with trimming

```
# Play a sound effect, skip its first 2 s, stop it after 5 s of playtime
01:10.000  sfx  applause.mp3  trim_start=2s  end=01:15.000  vol=0.6  fade_in=200ms  fade_out=500ms
```

### Telephone voice effect

```
00:05.000  caller  phone_take.mp3  highpass=300  lowpass=3400  compress  normalize=-16  mono
```

---

## Output file formats

Inferred from the `-o` extension. Supported: `mp3`, `wav`, `ogg`, `flac`, `m4a`, `aac` (requires matching ffmpeg codec).

---

## Programmatic API

```python
from dsl_audio import parse_mix_file, render

events = parse_mix_file("podcast.mix")
segment, durations = render(events, "output.mp3")
```

### TrackEvent fields

```python
@dataclass
class TrackEvent:
    timestamp_ms: int
    track_name: str
    filepath: str
    trim_start_ms: int = 0
    trim_end_ms: Optional[int] = None
    end_ms: Optional[int] = None
    vol: float = 1.0
    normalize: bool = False
    normalize_target_dbfs: Optional[float] = None
    compress: bool = False
    compress_threshold: float = -20.0
    compress_ratio: float = 4.0
    compress_attack_ms: float = 5.0
    compress_release_ms: float = 50.0
    highpass_hz: Optional[int] = None
    lowpass_hz: Optional[int] = None
    pan: Optional[float] = None
    speed: Optional[float] = None
    reverse: bool = False
    strip_silence: bool = False
    strip_silence_thresh_dbfs: float = -40.0
    strip_silence_min_len_ms: int = 500
    mono: bool = False
    fade_in_ms: int = 0
    fade_out_ms: int = 0
```

---

## Common mistakes

| Mistake | Fix |
|---|---|
| Path with spaces, unquoted | Wrap in double quotes: `"./my file.mp3"` |
| `normalize` on a very quiet clip before `compress` | Apply `compress` first (chain order is fixed) |
| `vol=0` silences a track instead of removing it | Just delete the line |
| `pan` on a mono source with no stereo output | Add `pan` without `mono`; `mono` converts before pan |
| `end=` shorter than `trim_start` offset | The clip plays 0 ms — no output |
| `speed=0` | Error: speed must be > 0 |

---

## Metadata

- **Package:** `dsl-audio`
- **Entry point:** `dsl-audio`
- **Python:** ≥ 3.12
- **Key dependencies:** `pydub`, `rich`, `typer`
- **License:** MIT
