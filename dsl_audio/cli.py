"""CLI entry point for dsl-audio."""
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from .display import print_events_table, render_timeline
from .engine import render
from .models import ms_to_str
from .parser import parse_mix_file

app = typer.Typer(
    name="dsl-audio",
    help=(
        "Podcast mixer — compile a [bold].mix[/bold] file into a single audio file.\n\n"
        "[dim]Commands:[/dim]\n"
        "  [cyan]render[/cyan]   Compile a .mix file → audio\n"
        "  [cyan]get[/cyan]      Inspect one or more audio files\n\n"
        "[dim]Quick start:[/dim]\n"
        "  dsl-audio render podcast.mix -o output.mp3\n"
        "  dsl-audio get intro.mp3 background.mp3"
    ),
    rich_markup_mode="rich",
    add_completion=False,
)
console = Console()


# ── render ────────────────────────────────────────────────────────────────────

@app.command("render")
def cmd_render(
    mix_file: Path = typer.Argument(
        ...,
        help="Path to the [bold].mix[/bold] file to compile.",
        exists=True,
        readable=True,
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o",
        help="Output audio file. Defaults to [cyan]<mix_file>.mp3[/cyan].",
    ),
    preview: bool = typer.Option(
        False, "--preview", "-p",
        help="Show timeline and event table without rendering audio.",
    ),
    no_timeline: bool = typer.Option(
        False, "--no-timeline",
        help="Skip the timeline visualization after rendering.",
    ),
    width: Optional[int] = typer.Option(
        None, "--width", "-w",
        help="Override terminal width used for the timeline display.",
    ),
) -> None:
    """Compile a [bold].mix[/bold] file into a single mixed audio file.

    \b
    .MIX FILE SYNTAX
        One event per line:

            TIMESTAMP  TRACK_NAME  FILEPATH  [OPTIONS...]  [# comment]

    \b
    TIMESTAMP FORMATS
        SS          e.g.  45
        SS.mmm      e.g.  45.500
        MM:SS       e.g.  01:30
        MM:SS.mmm   e.g.  01:30.250
        HH:MM:SS    e.g.  01:02:03
        HH:MM:SS.mmm

    \b
    CLIP OPTIONS
        vol=0.8           Volume multiplier                (default: 1.0)
        fade_in=2s        Fade-in duration                 (e.g. 2s, 500ms)
        fade_out=3s       Fade-out duration
        trim_start=5s     Skip the first N seconds of the clip
        trim_end=10s      Cut the last N seconds of the clip
        end=01:30.000     Force-stop clip at this absolute timeline position

    \b
    EFFECT OPTIONS
        normalize         Peak-normalize the clip  (headroom 0.1 dB)
        normalize=-18     RMS-normalize to target dBFS  (e.g. -18, -23)
        compress          Compress dynamic range  (default: -20 dB / 4:1)
        compress=-20:4:5:50  Custom compress: threshold:ratio:attack_ms:release_ms
        highpass=80       High-pass filter cutoff in Hz  (removes rumble/noise)
        lowpass=8000      Low-pass filter cutoff in Hz
        pan=-0.5          Stereo pan  (-1.0 full left … 0 center … 1.0 full right)
        speed=1.05        Playback speed multiplier  (also shifts pitch)
        strip_silence     Remove leading/trailing silence
        strip_silence=-40:500  Custom: thresh_dBFS:min_silence_ms
        mono              Mix down to mono before processing
        reverse           Reverse the clip

    \b
    EXAMPLE
        # podcast.mix
        00:00.000  music   ./bg.mp3    vol=0.3  fade_in=2s  normalize=-18
        00:00.000  intro   ./intro.mp3 strip_silence  highpass=80
        00:08.000  host    ./voice.mp3 vol=1.0  compress  highpass=100  fade_out=3s
        01:30.000  guest   ./guest.mp3 vol=0.9  compress=-20:3:5:50  end=02:45
        02:45.000  outro   ./outro.mp3 fade_in=1s  normalize

    \b
    Multiple events at the same TIMESTAMP are overlaid (superimposed).
    Filepaths with spaces must be quoted: "./my file.mp3"
    """
    console.print(f"\n[bold cyan]dsl-audio render[/bold cyan] — [dim]{mix_file}[/dim]\n")

    try:
        events = parse_mix_file(mix_file)
    except (FileNotFoundError, ValueError) as exc:
        console.print(f"[bold red]Parse error:[/bold red] {exc}")
        raise typer.Exit(1)

    if not events:
        console.print("[yellow]No events found in mix file.[/yellow]")
        raise typer.Exit(0)

    console.print(f"[green]Parsed[/green] {len(events)} event(s)\n")
    print_events_table(events, console)

    if preview:
        if not no_timeline:
            _show_timeline_with_load(events, width)
        raise typer.Exit(0)

    if output is None:
        output = mix_file.with_suffix(".mp3")

    durations: dict[int, int] = {}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Initializing…", total=len(events) + 1)

        def on_progress(current: int, total: int, desc: str) -> None:
            progress.update(task, completed=current, description=desc)

        try:
            _, durations = render(events, output, progress_callback=on_progress)
        except FileNotFoundError as exc:
            console.print(f"\n[bold red]Audio file not found:[/bold red] {exc}")
            raise typer.Exit(1)
        except Exception as exc:
            console.print(f"\n[bold red]Render error:[/bold red] {exc}")
            raise typer.Exit(1)

    console.print(f"\n[bold green]Done![/bold green]  [cyan]{output}[/cyan]")

    if not no_timeline:
        render_timeline(events, durations, console=console, terminal_width=width)


# ── get ───────────────────────────────────────────────────────────────────────

@app.command("get")
def cmd_get(
    audio_files: List[Path] = typer.Argument(
        ...,
        help="One or more audio files to inspect.",
    ),
) -> None:
    """Inspect one or more audio files and display their metadata.

    \b
    EXAMPLE
        dsl-audio get intro.mp3
        dsl-audio get intro.mp3 background.mp3 voice.wav
    """
    from pydub import AudioSegment

    console.print()

    table = Table(title="Audio File Info", show_lines=True)
    table.add_column("File", style="cyan", no_wrap=True)
    table.add_column("Duration", justify="right", style="bold green", no_wrap=True)
    table.add_column("Format", justify="center", no_wrap=True)
    table.add_column("Channels", justify="center", no_wrap=True)
    table.add_column("Sample rate", justify="right", no_wrap=True)
    table.add_column("Bit depth", justify="right", no_wrap=True)
    table.add_column("Size", justify="right", style="dim", no_wrap=True)

    errors: list[tuple[str, str]] = []

    for path in audio_files:
        if not path.exists():
            errors.append((str(path), "File not found"))
            continue

        try:
            seg = AudioSegment.from_file(str(path))
        except Exception as exc:
            errors.append((path.name, str(exc)))
            continue

        duration_ms = len(seg)
        duration_str = ms_to_str(duration_ms)

        channels = seg.channels
        ch_label = {1: "Mono", 2: "Stereo"}.get(channels, f"{channels}ch")

        sample_rate = seg.frame_rate
        bit_depth = seg.sample_width * 8

        size_bytes = path.stat().st_size
        if size_bytes >= 1_048_576:
            size_str = f"{size_bytes / 1_048_576:.1f} MB"
        elif size_bytes >= 1024:
            size_str = f"{size_bytes / 1024:.1f} KB"
        else:
            size_str = f"{size_bytes} B"

        fmt = path.suffix.lstrip(".").upper() or "?"

        table.add_row(
            path.name,
            duration_str,
            fmt,
            ch_label,
            f"{sample_rate} Hz",
            f"{bit_depth}-bit",
            size_str,
        )

    console.print(table)

    if errors:
        console.print()
        for name, msg in errors:
            console.print(f"[bold red]Error[/bold red] [cyan]{name}[/cyan]: {msg}")

    console.print()


# ── helpers ───────────────────────────────────────────────────────────────────

def _show_timeline_with_load(events, width: Optional[int]) -> None:
    from pydub import AudioSegment

    durations: dict[int, int] = {}
    with console.status("[dim]Loading audio files for timeline preview…[/dim]"):
        for i, event in enumerate(events):
            try:
                seg = AudioSegment.from_file(event.filepath)
                if event.trim_start_ms > 0:
                    seg = seg[event.trim_start_ms :]
                if event.trim_end_ms is not None and event.trim_end_ms > 0:
                    seg = seg[: len(seg) - event.trim_end_ms]
                if event.end_ms is not None:
                    max_dur = event.end_ms - event.timestamp_ms
                    if max_dur > 0:
                        seg = seg[:max_dur]
                durations[i] = len(seg)
            except Exception:
                durations[i] = 30_000  # fallback estimate

    render_timeline(events, durations, console=console, terminal_width=width)


def run() -> None:
    app()
