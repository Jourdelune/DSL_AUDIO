# dsl-audio

A text-based podcast mixer. Write a `.mix` file that describes *when* each audio clip plays, apply effects, and compile everything into a single output file.

```
pip install git+https://github.com/Jourdelune/DSL_AUDIO.git
```

> **System requirement:** `ffmpeg` must be installed and on your PATH for audio decoding/encoding.
> Install on Linux: `sudo apt install ffmpeg` — macOS: `brew install ffmpeg`

---

## Quick start

```bash
# 1. Inspect your clips
dsl-audio get intro.mp3 background.mp3 voice.mp3

# 2. Write a mix file (see syntax below)
# 3. Preview the timeline without rendering
dsl-audio render podcast.mix --preview

# 4. Render to a single file
dsl-audio render podcast.mix -o episode01.mp3
```

---

## .mix file syntax

Each non-blank, non-comment line is one **track event**:

```
TIMESTAMP  TRACK_NAME  FILEPATH  [OPTIONS...]  [# comment]
```

- **TIMESTAMP** — when the clip starts on the timeline
- **TRACK_NAME** — an identifier (used in the timeline display)
- **FILEPATH** — path to the audio file, relative to the `.mix` file; quote paths that contain spaces
- **OPTIONS** — zero or more `key=value` pairs or boolean flags

Lines starting with `#` are comments. Multiple events at the **same timestamp** are overlaid (superimposed).

### Timestamp formats

| Format | Example |
|---|---|
| `SS` | `45` |
| `SS.mmm` | `45.500` |
| `MM:SS` | `01:30` |
| `MM:SS.mmm` | `01:30.250` |
| `HH:MM:SS` | `01:02:03` |
| `HH:MM:SS.mmm` | `01:02:03.500` |

---

## Options reference

### Clip options

| Option | Type | Default | Description |
|---|---|---|---|
| `vol=0.8` | float | `1.0` | Volume multiplier. `0.5` = −6 dB, `2.0` = +6 dB |
| `fade_in=2s` | duration | `0` | Fade-in length. Accepts `2s`, `500ms` |
| `fade_out=3s` | duration | `0` | Fade-out length |
| `trim_start=5s` | duration | `0` | Skip the first N seconds of the clip |
| `trim_end=10s` | duration | `0` | Cut the last N seconds of the clip |
| `end=01:30.000` | timestamp | — | Force-stop at this absolute timeline position |

### Effect options

All effects are applied **before** fades, in the order listed below.

#### Volume normalization

| Option | Description |
|---|---|
| `normalize` | Peak-normalize: raises the loudest sample to −0.1 dBFS |
| `normalize=-18` | RMS-normalize to target dBFS. Common values: `−18` (music), `−16` (voice), `−23` (broadcast / EBU R128 proxy) |

**When to use:**
- Use `normalize=-16` on voice tracks so every speaker sounds equally loud regardless of recording level.
- Use `normalize=-18` on music beds so they sit consistently under speech.
- Avoid `normalize` (peak) on music — it does not help with dynamic range.

#### Dynamic range compression

| Option | Description |
|---|---|
| `compress` | Compress with defaults: threshold −20 dBFS, ratio 4:1, attack 5 ms, release 50 ms |
| `compress=-20:4:5:50` | Custom: `threshold_dBFS:ratio:attack_ms:release_ms` |

**When to use:**
- Always apply `compress` to voice tracks to even out loud/quiet passages.
- Use a gentler ratio (`2:1`) for music beds: `compress=-24:2:10:100`
- Stack with `normalize` for broadcast-ready levels: `compress  normalize=-16`

#### EQ / filtering

| Option | Description |
|---|---|
| `highpass=80` | High-pass filter — removes everything below the cutoff Hz |
| `lowpass=8000` | Low-pass filter — removes everything above the cutoff Hz |

**Common cutoffs:**

| Use case | Setting |
|---|---|
| Remove mic rumble / handling noise | `highpass=80` |
| Clean voice (remove low-end body) | `highpass=100` |
| Remove electrical hum (60 Hz grid) | `highpass=70` |
| Telephone / vintage radio effect | `highpass=300  lowpass=3400` |
| Remove high-frequency hiss | `lowpass=12000` |

#### Stereo & spatial

| Option | Description |
|---|---|
| `pan=-0.5` | Stereo pan. `-1.0` = full left, `0` = center, `1.0` = full right |
| `mono` | Mix down to mono before applying other effects |

**When to use:**
- Use `mono` on all voice tracks — speech recordings are effectively mono; stereo doubles the file size for no benefit.
- Light panning (`pan=0.2`, `pan=-0.2`) on two simultaneous guests gives a subtle stereo image.

#### Time & creative

| Option | Description |
|---|---|
| `speed=1.05` | Playback speed multiplier. Also shifts pitch proportionally. |
| `reverse` | Reverse the clip |

#### Silence trimming

| Option | Description |
|---|---|
| `strip_silence` | Remove leading and trailing silence (threshold −40 dBFS, min 500 ms) |
| `strip_silence=-40:500` | Custom: `threshold_dBFS:min_silence_ms` |

**When to use:**
- Apply to every voice recording before placing it on the timeline to remove dead air at the start and end of takes.

---

## Signal processing chain

Effects are applied in this fixed order, regardless of how they appear in the line:

```
clip boundaries  →  strip_silence  →  speed  →  mono  →  highpass
  →  lowpass  →  compress  →  vol  →  normalize  →  pan  →  reverse
  →  fade_in / fade_out
```

---

## Podcast template

```
# podcast.mix — full episode template

# ── Intro ────────────────────────────────────────────────────────
00:00.000  jingle   ./assets/jingle.mp3       vol=0.9  fade_out=3s
00:00.000  music    ./assets/background.mp3   vol=0.2  fade_in=2s  normalize=-18

# ── Host intro (voice over music) ────────────────────────────────
00:06.000  host     ./takes/host_intro.mp3    mono  strip_silence  highpass=100  compress  normalize=-16  fade_out=1s
00:06.000  music    ./assets/background.mp3   vol=0.08

# ── Guest interview ───────────────────────────────────────────────
01:30.000  host     ./takes/host_q1.mp3       mono  strip_silence  highpass=100  compress  normalize=-16
01:30.000  music    ./assets/background.mp3   vol=0.05

02:10.000  guest    ./takes/guest_a1.mp3      mono  strip_silence  highpass=80   compress=-18:3:5:80  normalize=-16  pan=0.15
02:10.000  music    ./assets/background.mp3   vol=0.04

# ── Outro ─────────────────────────────────────────────────────────
14:00.000  host     ./takes/host_outro.mp3    mono  strip_silence  highpass=100  compress  normalize=-16  fade_out=2s
14:00.000  music    ./assets/background.mp3   vol=0.2  fade_in=3s  fade_out=8s  normalize=-18

14:20.000  jingle   ./assets/jingle.mp3       vol=0.9  fade_in=2s
```

---

## CLI reference

### `dsl-audio render`

```
dsl-audio render MIXFILE [OPTIONS]
```

| Flag | Description |
|---|---|
| `-o / --output PATH` | Output file (default: `<mixfile>.mp3`). Format inferred from extension. |
| `-p / --preview` | Show timeline + event table without rendering. |
| `--no-timeline` | Skip timeline after rendering. |
| `-w / --width N` | Override terminal width for the timeline display. |

### `dsl-audio get`

```
dsl-audio get FILE [FILE ...]
```

Displays duration, format, channels, sample rate, bit depth, and file size for each audio file.

```bash
dsl-audio get intro.mp3 background.mp3 voice.wav
```

---

## Timeline visualization

After rendering (or with `--preview`), dsl-audio shows a Gantt-style timeline:

```
──────────────────────── Timeline  3 tracks max simultanés ────────────────────
[music────────────────────────────────────────────────────────────────────────]
[jingle────────][░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░]
[░░░░░░░░░░░░░░][host──────────────────────────────][guest────────────────────]

00:00.000    00:02.500    00:05.000    00:07.500    00:10.000
```

- Each row is one **lane** (N rows = maximum simultaneous tracks at any point)
- `[name────]` blocks are color-coded per unique track name
- `░` represents silence in that lane

---

## Supported output formats

Any format supported by your `ffmpeg` installation. Pass the desired extension to `-o`:

```bash
dsl-audio render podcast.mix -o episode.mp3    # MP3
dsl-audio render podcast.mix -o episode.wav    # WAV (lossless)
dsl-audio render podcast.mix -o episode.ogg    # OGG Vorbis
dsl-audio render podcast.mix -o episode.flac   # FLAC (lossless)
```

---

## Development install

```bash
git clone https://github.com/Jourdelune/DSL_AUDIO.git
cd DSL_AUDIO
pip install -e .
```
