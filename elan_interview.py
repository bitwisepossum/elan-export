#!/usr/bin/env python3
"""
elan_interview.py — Export two-tier interview data from ELAN .eaf files.
Outputs RTF or Markdown with one tier per speaker (e.g. interviewer + participant).
Merges consecutive turns by the same speaker for readability.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
import argparse
from datetime import timedelta
import sys
import time
import shutil


def format_timestamp(milliseconds):
    """Convert milliseconds to readable timestamp format (MM:SS.mmm)"""
    td = timedelta(milliseconds=milliseconds)
    total_seconds = td.total_seconds()
    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:06.3f}"


def parse_eaf_file(eaf_path, int_tier='INT_speech', participant_tier='PARTICIPANT_speech',
                   int_name='Interviewer', participant_name='Participant'):
    """Parse ELAN .eaf file and extract annotations from specified tiers"""
    tree = ET.parse(eaf_path)
    root = tree.getroot()

    # Build time slot dictionary
    time_slots = {}
    for ts in root.findall('.//TIME_SLOT'):
        ts_id = ts.get('TIME_SLOT_ID')
        ts_value = int(ts.get('TIME_VALUE', 0))
        time_slots[ts_id] = ts_value

    # Extract annotations from both tiers
    annotations = []

    tier_name_map = {int_tier: int_name, participant_tier: participant_name}

    for tier in root.findall('.//TIER'):
        tier_id = tier.get('TIER_ID')

        if tier_id in tier_name_map:
            speaker = tier_name_map[tier_id]

            for annotation in tier.findall('.//ALIGNABLE_ANNOTATION'):
                ts1 = annotation.get('TIME_SLOT_REF1')
                ts2 = annotation.get('TIME_SLOT_REF2')

                start_time = time_slots.get(ts1, 0)
                end_time = time_slots.get(ts2, 0)

                text_elem = annotation.find('ANNOTATION_VALUE')
                text = text_elem.text if text_elem is not None and text_elem.text else ''

                annotations.append({
                    'speaker': speaker,
                    'start': start_time,
                    'end': end_time,
                    'text': text.strip(),
                    'tier_id': tier_id
                })

    # Sort by start time
    annotations.sort(key=lambda x: x['start'])

    return annotations


def merge_consecutive_turns(annotations, max_gap_ms=5000, use_linebreaks=True):
    """
    Merge consecutive turns by the same speaker.

    Args:
        annotations: List of annotation dictionaries
        max_gap_ms: Maximum gap in milliseconds to merge (default 5 seconds)
        use_linebreaks: If True, join with line breaks; if False, join with spaces

    Returns:
        List of merged annotations
    """
    if not annotations:
        return []

    merged = []
    current = annotations[0].copy()
    current['segments'] = [current['text']] if current['text'] else []

    for ann in annotations[1:]:
        # Check if same speaker and within gap threshold
        if (ann['speaker'] == current['speaker'] and
            ann['start'] - current['end'] <= max_gap_ms):
            # Merge this annotation into current
            if ann['text']:
                current['segments'].append(ann['text'])
            current['end'] = ann['end']
        else:
            # Save current and start new one
            if use_linebreaks:
                current['text'] = '\n'.join(s for s in current['segments'] if s)
            else:
                current['text'] = ' '.join(s for s in current['segments'] if s)
            merged.append(current)

            current = ann.copy()
            current['segments'] = [current['text']] if current['text'] else []

    # Don't forget the last one
    if use_linebreaks:
        current['text'] = '\n'.join(s for s in current['segments'] if s)
    else:
        current['text'] = ' '.join(s for s in current['segments'] if s)
    merged.append(current)

    return merged


def escape_md(text):
    """Escape special characters for Markdown format"""
    if not text:
        return ''
    for ch in ('\\', '`', '*', '_', '[', ']', '#'):
        text = text.replace(ch, '\\' + ch)
    return text


def create_markdown(annotations, output_path, include_timestamps=True, compact=False,
                    original_count=0, eaf_filename='',
                    int_name='Interviewer', participant_name='Participant'):
    """Create Markdown file from annotations"""
    int_count = sum(1 for a in annotations if a['speaker'] == int_name)
    part_count = sum(1 for a in annotations if a['speaker'] == participant_name)
    duration_str = format_timestamp(annotations[-1]['end']) if annotations else '00:00.000'

    lines = ['# Interview Transcript', '']

    if eaf_filename:
        lines.append(f'**Source file:** {escape_md(eaf_filename)}  ')
    lines.append(f'**Total duration:** {duration_str}  ')
    lines.append(f'**{escape_md(int_name)} turns:** {int_count}  ')
    lines.append(f'**{escape_md(participant_name)} turns:** {part_count}  ')
    lines.append(f'**Total turns:** {len(annotations)}  ')
    if original_count > len(annotations):
        lines.append(f'**Original annotations:** {original_count} (merged)  ')
    lines += ['', '---', '']

    for ann in annotations:
        text = ann['text']
        if not text:
            continue
        speaker = ann['speaker']

        if include_timestamps:
            ts = format_timestamp(ann['start'])
            ts_str = f'`[{ts}]` '
        else:
            ts_str = ''

        if compact:
            lines.append(f'{ts_str}**{escape_md(speaker)}:** {escape_md(text)}')
            lines.append('')
        else:
            lines.append(f'{ts_str}**{escape_md(speaker)}:**')
            for seg in text.split('\n'):
                lines.append(f'> {escape_md(seg)}' if seg else '>')
            lines.append('')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def escape_rtf(text):
    """Escape special characters for RTF format"""
    if not text:
        return ''

    # Replace special RTF characters
    text = text.replace('\\', '\\\\')
    text = text.replace('{', '\\{')
    text = text.replace('}', '\\}')

    # Convert newlines to RTF line breaks
    text = text.replace('\n', '\\line\n')

    # Handle Unicode characters
    result = []
    for char in text:
        if ord(char) < 128:
            result.append(char)
        else:
            # Use Unicode escape for non-ASCII characters
            result.append(f'\\u{ord(char)}?')

    return ''.join(result)


def create_rtf(annotations, output_path, include_timestamps=True, compact=False,
               font_size=12, original_count=0, eaf_filename='',
               int_name='Interviewer', participant_name='Participant'):
    """
    Create RTF file from annotations

    Args:
        annotations: List of annotation dictionaries
        output_path: Path to output RTF file
        include_timestamps: Whether to include timestamps
        compact: Use compact format (speaker and text on same line)
        font_size: Main text font size in points (default: 12)
        original_count: Number of original annotations before merging
        eaf_filename: Name of source EAF file
        int_name: Display name for the interviewer tier
        participant_name: Display name for the participant tier
    """

    # Calculate RTF font sizes (RTF uses half-points)
    fs_main = font_size * 2
    fs_timestamp = max((font_size - 2) * 2, 16)  # Minimum 8pt
    fs_title = (font_size + 4) * 2
    fs_info = max((font_size - 1) * 2, 18)  # Slightly smaller for info

    # Calculate statistics
    int_count = sum(1 for a in annotations if a['speaker'] == int_name)
    part_count = sum(1 for a in annotations if a['speaker'] == participant_name)
    duration_str = format_timestamp(annotations[-1]['end']) if annotations else '00:00.000'

    # RTF header with font table and colors
    rtf_content = [
        r'{\rtf1\ansi\deff0',
        r'{\fonttbl{\f0\fswiss Arial;}{\f1\fmodern Courier New;}}',
        r'{\colortbl;\red0\green0\blue128;\red128\green0\blue0;\red100\green100\blue100;}',
        f'\\viewkind4\\uc1\\pard\\f0\\fs{fs_main}',
        r''
    ]

    # Title
    rtf_content.append(f'\\b\\fs{fs_title} Interview Transcript\\b0\\fs{fs_main}\\par')
    rtf_content.append(r'\par')

    # Statistics section
    rtf_content.append(f'\\fs{fs_info}\\cf3')

    if eaf_filename:
        rtf_content.append(f'Source file: {escape_rtf(eaf_filename)}\\par')

    rtf_content.append(f'Total duration: {duration_str}\\par')
    rtf_content.append(f'{escape_rtf(int_name)} turns: {int_count}\\par')
    rtf_content.append(f'{escape_rtf(participant_name)} turns: {part_count}\\par')
    rtf_content.append(f'Total turns: {len(annotations)}\\par')

    if original_count > len(annotations):
        rtf_content.append(f'Original annotations: {original_count} (merged)\\par')

    rtf_content.append(f'\\cf0\\fs{fs_main}\\par')
    rtf_content.append(r'\par')

    # Horizontal line separator
    rtf_content.append(r'\pard\brdrb\brdrs\brdrw10\brsp20\par')
    rtf_content.append(r'\pard\par')

    # Add annotations
    for ann in annotations:
        speaker = ann['speaker']
        text = escape_rtf(ann['text'])

        # Skip empty annotations
        if not text:
            continue

        # Speaker color: blue for interviewer, red for participant
        color = r'\cf1' if speaker == int_name else r'\cf2'

        # Format with speaker on separate line and indented text
        if include_timestamps:
            timestamp = format_timestamp(ann['start'])
            if compact:
                rtf_content.append(
                    f"\\f1\\fs{fs_timestamp}\\cf3 [{timestamp}]\\f0\\fs{fs_main}  "
                    f"{color}\\b {speaker}:\\b0\\cf0  {text}\\par\\par"
                )
            else:
                rtf_content.append(
                    f"\\f1\\fs{fs_timestamp}\\cf3 [{timestamp}]\\cf0\\f0\\fs{fs_main}\\par"
                )
                rtf_content.append(
                    f"{color}\\b {speaker}:\\b0\\cf0\\par"
                )
                rtf_content.append(
                    f"\\li360 {text}\\par"
                )
                rtf_content.append(r'\li0\par')
        else:
            if compact:
                rtf_content.append(
                    f"{color}\\b {speaker}:\\b0\\cf0  {text}\\par\\par"
                )
            else:
                rtf_content.append(
                    f"{color}\\b {speaker}:\\b0\\cf0\\par"
                )
                rtf_content.append(
                    f"\\li360 {text}\\par"
                )
                rtf_content.append(r'\li0\par')

    # Close RTF
    rtf_content.append(r'}')

    # Write to file
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(rtf_content))


def process_single_file(eaf_path, output_path, args, quiet=False):
    """Process one EAF file. Returns True on success, False on failure."""
    if not quiet:
        print(f"Reading ELAN file: {eaf_path}")

    try:
        annotations = parse_eaf_file(
            eaf_path,
            int_tier=args.int_tier,
            participant_tier=args.participant_tier,
            int_name=args.int_name,
            participant_name=args.participant_name,
        )

        if not annotations:
            print(f"Warning: No annotations found in '{args.int_tier}' or '{args.participant_tier}' tiers")
            return False

        original_count = len(annotations)
        if not quiet:
            print(f"Found {original_count} annotations")

        if not args.no_merge:
            max_gap_ms = int(args.max_gap * 1000)
            annotations = merge_consecutive_turns(
                annotations,
                max_gap_ms,
                use_linebreaks=not args.spaces
            )
            if not quiet:
                join_method = "spaces" if args.spaces else "line breaks"
                print(f"Merged into {len(annotations)} turns (gap: {args.max_gap}s, joined with {join_method})")

        if args.markdown:
            create_markdown(
                annotations,
                output_path,
                include_timestamps=not args.no_timestamps,
                compact=args.compact,
                original_count=original_count,
                eaf_filename=eaf_path.name,
                int_name=args.int_name,
                participant_name=args.participant_name,
            )
        else:
            create_rtf(
                annotations,
                output_path,
                include_timestamps=not args.no_timestamps,
                compact=args.compact,
                font_size=args.font_size,
                original_count=original_count,
                eaf_filename=eaf_path.name,
                int_name=args.int_name,
                participant_name=args.participant_name,
            )

        if not quiet:
            print(f"Successfully exported to: {output_path}")
            if not args.markdown:
                print(f"Font size: {args.font_size}pt")
            print(f"\nStatistics:")
            print(f"  Original annotations: {original_count}")
            print(f"  Final turns: {len(annotations)}")
            int_count = sum(1 for a in annotations if a['speaker'] == args.int_name)
            part_count = sum(1 for a in annotations if a['speaker'] == args.participant_name)
            print(f"  {args.int_name} turns: {int_count}")
            print(f"  {args.participant_name} turns: {part_count}")
            if annotations:
                print(f"  Total duration: {format_timestamp(annotations[-1]['end'])}")

        return True

    except ET.ParseError as e:
        print(f"Error parsing EAF file: {e}")
        return False
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def resolve_batch_files(input_arg):
    """Return a sorted list of .eaf Paths from a directory or glob pattern."""
    p = Path(input_arg)
    if p.is_dir():
        return sorted(p.glob('*.eaf'))
    return sorted(f for f in Path('.').glob(input_arg) if f.suffix.lower() == '.eaf')


class BatchProgress:
    """Tracks and displays progress for batch EAF processing."""

    def __init__(self, total):
        self.total = total
        self.completed = 0
        self.succeeded = 0
        self.failed = []
        self.start_time = time.monotonic()
        self._width = len(str(total))

    def update(self, eaf_path, success):
        self.completed += 1
        if success:
            self.succeeded += 1
        else:
            self.failed.append(eaf_path)
        self._print_line(eaf_path, success)

    def _fmt_time(self, seconds):
        s = int(seconds)
        if s < 3600:
            return f"{s // 60}:{s % 60:02d}"
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"

    def _print_line(self, eaf_path, success):
        elapsed = time.monotonic() - self.start_time
        pct = self.completed / self.total * 100
        status = "OK  " if success else "FAIL"

        if self.completed > 0 and self.completed < self.total:
            eta = elapsed / self.completed * (self.total - self.completed)
            eta_str = self._fmt_time(eta)
        else:
            eta_str = "0:00"

        try:
            term_width = shutil.get_terminal_size().columns
        except Exception:
            term_width = 80

        bar_width = min(20, max(8, term_width - 55))
        filled = int(bar_width * self.completed / self.total)
        if self.completed == self.total:
            bar = '=' * bar_width
        else:
            bar = '=' * filled + '>' + ' ' * (bar_width - filled - 1)

        prefix = f"  [{self.completed:>{self._width}}/{self.total}] [{bar}] {pct:5.1f}%  {self._fmt_time(elapsed)}<{eta_str}  "
        max_name = max(8, term_width - len(prefix) - 6)
        name = eaf_path.name
        if len(name) > max_name:
            name = name[:max_name - 3] + '...'

        print(f"{prefix}{name} {status}")

    def print_summary(self):
        elapsed = self._fmt_time(time.monotonic() - self.start_time)
        sep = '=' * 40
        print(f"\n{sep}")
        print(f"  Batch complete: {self.succeeded}/{self.total} succeeded in {elapsed}")
        if self.failed:
            print(f"  Failed ({len(self.failed)}):")
            for f in self.failed:
                print(f"    {f}")
        print(sep)


def run_batch(files, output_dir, args, fail_fast):
    """Process a list of EAF files, report progress and summary. Returns 0/1."""
    suffix = '.md' if args.markdown else '.rtf'
    progress = BatchProgress(len(files))

    for eaf_path in files:
        if output_dir is not None:
            out_path = output_dir / eaf_path.with_suffix(suffix).name
        else:
            out_path = eaf_path.with_suffix(suffix)

        success = process_single_file(eaf_path, out_path, args, quiet=True)
        progress.update(eaf_path, success)

        if not success and fail_fast:
            print("  --fail-fast: aborting after first failure.")
            break

    progress.print_summary()
    return 0 if not progress.failed else 1


def main():
    parser = argparse.ArgumentParser(
        description='Export ELAN .eaf file to readable RTF format'
    )
    parser.add_argument(
        'eaf_file',
        type=str,
        help='Path to ELAN .eaf file, or a directory/glob pattern when using --batch'
    )
    parser.add_argument(
        '-o', '--output',
        type=str,
        help='Output file path (default: same name as input with .rtf/.md extension)'
    )
    parser.add_argument(
        '--batch',
        action='store_true',
        help='Process all .eaf files at eaf_file (directory or glob pattern)'
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default=None,
        metavar='DIR',
        help='Batch mode: write all outputs to DIR (default: alongside each input)'
    )
    parser.add_argument(
        '--fail-fast',
        action='store_true',
        help='Batch mode: stop after the first failure'
    )
    parser.add_argument(
        '--no-timestamps',
        action='store_true',
        help='Exclude timestamps from output'
    )
    parser.add_argument(
        '--no-merge',
        action='store_true',
        help='Do not merge consecutive turns by same speaker'
    )
    parser.add_argument(
        '--max-gap',
        type=float,
        default=5.0,
        help='Maximum gap in seconds to merge turns (default: 5.0)'
    )
    parser.add_argument(
        '--spaces',
        action='store_true',
        help='Join segments with spaces instead of line breaks'
    )
    parser.add_argument(
        '--compact',
        action='store_true',
        help='Use compact format (speaker and text on same line)'
    )
    parser.add_argument(
        '--font-size',
        type=int,
        default=12,
        help='Main text font size in points (default: 12)'
    )
    parser.add_argument(
        '--int-tier',
        type=str,
        default='INT_speech',
        help='Tier ID for the interviewer (default: INT_speech)'
    )
    parser.add_argument(
        '--participant-tier',
        type=str,
        default='PARTICIPANT_speech',
        help='Tier ID for the participant (default: PARTICIPANT_speech)'
    )
    parser.add_argument(
        '--int-name',
        type=str,
        default='Interviewer',
        help='Display name for the interviewer (default: Interviewer)'
    )
    parser.add_argument(
        '--participant-name',
        type=str,
        default='Participant',
        help='Display name for the participant (default: Participant)'
    )
    parser.add_argument(
        '-md', '--markdown',
        action='store_true',
        help='Output Markdown (.md) instead of RTF'
    )

    args = parser.parse_args()

    # Validate font size (only relevant for RTF)
    if not args.markdown and (args.font_size < 6 or args.font_size > 72):
        print(f"Error: Font size must be between 6 and 72 points")
        return 1

    # Batch mode
    if args.batch:
        if args.output:
            print("Error: --output cannot be used with --batch; use --output-dir instead")
            return 1

        output_dir = None
        if args.output_dir:
            output_dir = Path(args.output_dir)
            if not output_dir.is_dir():
                print(f"Error: --output-dir does not exist: {output_dir}")
                return 1

        files = resolve_batch_files(args.eaf_file)
        if not files:
            print(f"Error: No .eaf files found at: {args.eaf_file}")
            return 1

        return run_batch(files, output_dir, args, args.fail_fast)

    # Single-file mode
    eaf_path = Path(args.eaf_file)
    if not eaf_path.exists():
        print(f"Error: File not found: {eaf_path}")
        return 1

    if not eaf_path.suffix.lower() == '.eaf':
        print(f"Warning: File does not have .eaf extension: {eaf_path}")

    if args.output:
        output_path = Path(args.output)
    else:
        suffix = '.md' if args.markdown else '.rtf'
        output_path = eaf_path.with_suffix(suffix)

    return 0 if process_single_file(eaf_path, output_path, args) else 1


if __name__ == '__main__':
    exit(main())
