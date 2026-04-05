"""Rich timeline display for dsl-audio.

Shows a Gantt-style visualization with exactly N rows,
where N = maximum number of simultaneously playing tracks.
Each row shows [track_name────] blocks with ░ for silence,
with timestamps below.
"""
from pathlib import Path
from typing import Dict, List, Tuple

from rich.console import Console
from rich.style import Style
from rich.text import Text

from .models import TrackEvent, ms_to_str

_COLORS = [
    "cyan",
    "green",
    "yellow",
    "magenta",
    "blue",
    "red",
    "bright_cyan",
    "bright_green",
    "bright_yellow",
    "bright_magenta",
]


def _assign_lanes(
    events: List[TrackEvent],
    durations: Dict[int, int],
) -> Tuple[List[List[Tuple[int, int, str]]], int]:
    """Pack events into non-overlapping lanes (greedy interval coloring)."""
    intervals = [
        (e.timestamp_ms, e.timestamp_ms + durations[i], e.track_name)
        for i, e in enumerate(events)
    ]
    lanes: List[List[Tuple[int, int, str]]] = []

    for start, end, name in intervals:
        placed = False
        for lane in lanes:
            if all(end <= s or start >= e for s, e, _ in lane):
                lane.append((start, end, name))
                placed = True
                break
        if not placed:
            lanes.append([(start, end, name)])

    total_ms = max(end for _, end, _ in intervals) if intervals else 0
    return lanes, total_ms


def _make_block(name: str, width: int) -> str:
    """Build a fixed-width block like '[name────────]'."""
    if width <= 0:
        return ""
    if width == 1:
        return "─"
    if width == 2:
        return "[]"
    # interior = width - 2 (for [ and ])
    inner_w = width - 2
    label = name[:inner_w]
    fill = "─" * (inner_w - len(label))
    return f"[{label}{fill}]"


def render_timeline(
    events: List[TrackEvent],
    durations: Dict[int, int],
    console: Console | None = None,
    terminal_width: int | None = None,
) -> None:
    """Print a timeline visualization to the console."""
    if console is None:
        console = Console()

    if not events:
        console.print("[yellow]No events to display.[/yellow]")
        return

    width = terminal_width or console.width or 100
    bar_width = max(20, width - 2)

    lanes, total_ms = _assign_lanes(events, durations)
    n_lanes = len(lanes)

    track_names = list(dict.fromkeys(e.track_name for e in events))
    color_map = {name: _COLORS[i % len(_COLORS)] for i, name in enumerate(track_names)}

    console.print()
    console.rule(
        f"[bold]Timeline[/bold]  [dim]{n_lanes} track{'s' if n_lanes != 1 else ''} max simultanés[/dim]"
    )
    console.print()

    for lane in lanes:
        # Sort segments by start so we can fill gaps left-to-right
        segments = sorted(lane, key=lambda x: x[0])

        line = Text()
        cursor = 0  # current bar position (in chars)

        for start, end, name in segments:
            color = color_map.get(name, "white")
            start_pos = int(start / total_ms * bar_width) if total_ms else 0
            end_pos = int(end / total_ms * bar_width) if total_ms else bar_width
            end_pos = min(end_pos, bar_width)
            seg_len = max(end_pos - start_pos, 1)

            # Fill gap before this segment with ░
            gap = start_pos - cursor
            if gap > 0:
                line.append("░" * gap, style="dim")

            # Render block
            block = _make_block(name, seg_len)
            line.append(block, style=Style(color=color, bold=True))
            cursor = start_pos + seg_len

        # Fill trailing silence
        trailing = bar_width - cursor
        if trailing > 0:
            line.append("░" * trailing, style="dim")

        console.print(line)

    # ── Timestamp ruler ──────────────────────────────────────────
    console.print()
    num_marks = min(6, bar_width // 12)
    ruler = Text()
    prev_end = 0
    for i in range(num_marks + 1):
        pos = int(bar_width * i / num_marks) if num_marks else 0
        mark = ms_to_str(int(total_ms * i / num_marks)) if num_marks else ms_to_str(0)
        gap = pos - prev_end
        if gap > 0:
            ruler.append(" " * gap, style="dim")
        ruler.append(mark, style="dim")
        prev_end = pos + len(mark)

    console.print(ruler)
    console.print()


def _effects_summary(e: TrackEvent) -> str:
    """Build a short human-readable summary of active effects for a TrackEvent."""
    parts = []
    if e.highpass_hz:
        parts.append(f"hp:{e.highpass_hz}Hz")
    if e.lowpass_hz:
        parts.append(f"lp:{e.lowpass_hz}Hz")
    if e.compress:
        parts.append(f"comp({e.compress_threshold:.0f}dB:{e.compress_ratio:.1f}x)")
    if e.normalize:
        if e.normalize_target_dbfs is not None:
            parts.append(f"norm→{e.normalize_target_dbfs:.0f}dBFS")
        else:
            parts.append("norm:peak")
    if e.pan is not None:
        parts.append(f"pan:{e.pan:+.2f}")
    if e.speed is not None:
        parts.append(f"speed:{e.speed:.2f}x")
    if e.strip_silence:
        parts.append("strip_sil")
    if e.mono:
        parts.append("mono")
    if e.reverse:
        parts.append("reverse")
    return "  ".join(parts) if parts else "—"


def print_events_table(events: List[TrackEvent], console: Console | None = None) -> None:
    """Print a table listing all parsed events."""
    from rich.table import Table

    if console is None:
        console = Console()

    table = Table(title="Mix Events", show_lines=True)
    table.add_column("Timestamp", style="cyan", no_wrap=True)
    table.add_column("Track", style="bold green", no_wrap=True)
    table.add_column("File", style="white")
    table.add_column("Vol", justify="right", no_wrap=True)
    table.add_column("Fade in/out", justify="right", no_wrap=True)
    table.add_column("Trim / End", justify="right", no_wrap=True)
    table.add_column("Effects", style="dim")

    for e in events:
        fade = "—"
        if e.fade_in_ms and e.fade_out_ms:
            fade = f"↑{e.fade_in_ms}ms ↓{e.fade_out_ms}ms"
        elif e.fade_in_ms:
            fade = f"↑{e.fade_in_ms}ms"
        elif e.fade_out_ms:
            fade = f"↓{e.fade_out_ms}ms"

        trim = "—"
        parts = []
        if e.trim_start_ms:
            parts.append(f"+{e.trim_start_ms}ms")
        if e.trim_end_ms:
            parts.append(f"-{e.trim_end_ms}ms")
        if e.end_ms is not None:
            parts.append(f"end@{ms_to_str(e.end_ms)}")
        if parts:
            trim = "  ".join(parts)

        table.add_row(
            e.timestamp_str,
            e.track_name,
            Path(e.filepath).name,
            f"{e.vol:.2f}",
            fade,
            trim,
            _effects_summary(e),
        )

    console.print(table)
