#!/usr/bin/env python3
"""
elan_tier.py — Export a single tier from ELAN .eaf files.
Outputs RTF or Markdown. Optionally separates multiple speakers using an
in-annotation separator prefix (e.g. "P" matches P1, P2, P3 …).
"""

import xml.etree.ElementTree as ET
import re
from pathlib import Path
import argparse
from datetime import timedelta


# Colour palette for up to 8 distinct speakers (RTF \colortbl entries)
SPEAKER_COLORS_RTF = [
    (0, 0, 128),     # navy blue
    (128, 0, 0),     # dark red
    (0, 100, 0),     # dark green
    (100, 0, 100),   # purple
    (139, 90, 0),    # brown/orange
    (0, 100, 100),   # teal
    (60, 60, 60),    # dark grey
    (160, 80, 0),    # dark orange
]


def format_timestamp(milliseconds):
    """Convert milliseconds to readable timestamp format (MM:SS.mmm)"""
    td = timedelta(milliseconds=milliseconds)
    total_seconds = td.total_seconds()
    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:06.3f}"


def build_separator_pattern(prefix):
    """
    Given a separator prefix (e.g. "P" or "INT"),
    return a compiled regex that matches that prefix followed by one or more digits,
    optionally with surrounding whitespace (the whole annotation text).
    """
    escaped = re.escape(prefix.strip())
    return re.compile(r'^\s*' + escaped + r'(\d+)\s*$')


def parse_eaf_single_tier(eaf_path, tier_id, separator_prefix=None):
    """
    Parse ELAN .eaf file and extract annotations from a single tier.

    If separator_prefix is given, annotation values matching <prefix><number>
    are treated as speaker-change markers rather than speech content.
    All annotations between two markers belong to the speaker named by the marker.

    Returns a list of dicts:
        {speaker, start, end, text}
    """
    tree = ET.parse(eaf_path)
    root = tree.getroot()

    # Build time slot dictionary
    time_slots = {}
    for ts in root.findall('.//TIME_SLOT'):
        ts_id = ts.get('TIME_SLOT_ID')
        ts_value = int(ts.get('TIME_VALUE', 0))
        time_slots[ts_id] = ts_value

    # Find the requested tier
    target_tier = None
    for tier in root.findall('.//TIER'):
        if tier.get('TIER_ID') == tier_id:
            target_tier = tier
            break

    if target_tier is None:
        available = [t.get('TIER_ID') for t in root.findall('.//TIER')]
        raise ValueError(
            f"Tier '{tier_id}' not found in EAF file.\n"
            f"Available tiers: {available}"
        )

    # Collect raw annotations sorted by start time
    raw = []
    for annotation in target_tier.findall('.//ALIGNABLE_ANNOTATION'):
        ts1 = annotation.get('TIME_SLOT_REF1')
        ts2 = annotation.get('TIME_SLOT_REF2')
        start_time = time_slots.get(ts1, 0)
        end_time = time_slots.get(ts2, 0)
        text_elem = annotation.find('ANNOTATION_VALUE')
        text = text_elem.text if text_elem is not None and text_elem.text else ''
        raw.append({
            'start': start_time,
            'end': end_time,
            'text': text.strip(),
        })

    raw.sort(key=lambda x: x['start'])

    if not separator_prefix:
        # No speaker separation — everything belongs to a single "Speaker" label
        return [
            {**r, 'speaker': 'Speaker'}
            for r in raw
            if r['text']
        ]

    # Separator mode: walk through annotations and assign speakers
    sep_pattern = build_separator_pattern(separator_prefix)
    annotations = []
    current_speaker = None

    for r in raw:
        m = sep_pattern.match(r['text'])
        if m:
            # This annotation is a speaker marker, not speech content
            current_speaker = f"{separator_prefix.strip()}{m.group(1)}"
        else:
            if not r['text']:
                continue
            speaker_label = current_speaker if current_speaker else 'Unknown'
            annotations.append({
                'speaker': speaker_label,
                'start': r['start'],
                'end': r['end'],
                'text': r['text'],
            })

    return annotations


def list_tiers(eaf_path):
    """Return all tier IDs present in the EAF file."""
    tree = ET.parse(eaf_path)
    root = tree.getroot()
    return [tier.get('TIER_ID') for tier in root.findall('.//TIER')]


def merge_consecutive_turns(annotations, max_gap_ms=5000, use_linebreaks=True):
    """Merge consecutive turns by the same speaker within a time gap."""
    if not annotations:
        return []

    merged = []
    current = annotations[0].copy()
    current['segments'] = [current['text']] if current['text'] else []

    for ann in annotations[1:]:
        if (ann['speaker'] == current['speaker'] and
                ann['start'] - current['end'] <= max_gap_ms):
            if ann['text']:
                current['segments'].append(ann['text'])
            current['end'] = ann['end']
        else:
            sep = '\n' if use_linebreaks else ' '
            current['text'] = sep.join(s for s in current['segments'] if s)
            merged.append(current)
            current = ann.copy()
            current['segments'] = [current['text']] if current['text'] else []

    sep = '\n' if use_linebreaks else ' '
    current['text'] = sep.join(s for s in current['segments'] if s)
    merged.append(current)

    return merged


def escape_rtf(text):
    """Escape special characters for RTF format."""
    if not text:
        return ''
    text = text.replace('\\', '\\\\')
    text = text.replace('{', '\\{')
    text = text.replace('}', '\\}')
    text = text.replace('\n', '\\line\n')

    result = []
    for char in text:
        if ord(char) < 128:
            result.append(char)
        else:
            result.append(f'\\u{ord(char)}?')
    return ''.join(result)


def escape_md(text):
    """Escape special characters for Markdown format."""
    if not text:
        return ''
    for ch in ('\\', '`', '*', '_', '[', ']', '#'):
        text = text.replace(ch, '\\' + ch)
    return text


def create_markdown(annotations, output_path, include_timestamps=True, compact=False,
                    original_count=0, eaf_filename='', tier_id=''):
    """Write a Markdown transcript from a list of annotation dicts."""
    unique_speakers = sorted(set(a['speaker'] for a in annotations))
    speaker_counts = {}
    for a in annotations:
        speaker_counts[a['speaker']] = speaker_counts.get(a['speaker'], 0) + 1
    duration_str = format_timestamp(annotations[-1]['end']) if annotations else '00:00.000'

    lines = ['# Transcript', '']

    if eaf_filename:
        lines.append(f'**Source file:** {escape_md(eaf_filename)}  ')
    if tier_id:
        lines.append(f'**Tier:** {escape_md(tier_id)}  ')
    lines.append(f'**Total duration:** {duration_str}  ')
    for spk in unique_speakers:
        lines.append(f'**{escape_md(spk)} turns:** {speaker_counts.get(spk, 0)}  ')
    lines.append(f'**Total turns:** {len(annotations)}  ')
    if original_count > len(annotations):
        lines.append(f'**Original annotations:** {original_count} (merged)  ')
    lines += ['', '---', '']

    for ann in annotations:
        text = ann['text']
        if not text:
            continue
        spk = ann['speaker']

        if include_timestamps:
            ts = format_timestamp(ann['start'])
            ts_str = f'`[{ts}]` '
        else:
            ts_str = ''

        if compact:
            lines.append(f'{ts_str}**{escape_md(spk)}:** {escape_md(text)}')
            lines.append('')
        else:
            lines.append(f'{ts_str}**{escape_md(spk)}:**')
            for seg in text.split('\n'):
                lines.append(f'> {escape_md(seg)}' if seg else '>')
            lines.append('')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def build_color_map(speakers):
    """Map each unique speaker name to a 1-based RTF colour index."""
    unique = sorted(set(speakers))
    return {spk: (i + 1) for i, spk in enumerate(unique)}


def create_rtf(annotations, output_path, include_timestamps=True, compact=False,
               font_size=12, original_count=0, eaf_filename='', tier_id=''):
    """Write an RTF transcript from a list of annotation dicts."""

    fs_main = font_size * 2
    fs_timestamp = max((font_size - 2) * 2, 16)
    fs_title = (font_size + 4) * 2
    fs_info = max((font_size - 1) * 2, 18)

    unique_speakers = sorted(set(a['speaker'] for a in annotations))
    color_map = build_color_map(unique_speakers)

    # Build colortbl: grey (index 1) for timestamps/meta, then speaker colours
    grey = (100, 100, 100)
    colortbl_entries = [f'\\red{grey[0]}\\green{grey[1]}\\blue{grey[2]}']  # cf1 = grey
    for spk in unique_speakers:
        idx = (color_map[spk] - 1) % len(SPEAKER_COLORS_RTF)
        r, g, b = SPEAKER_COLORS_RTF[idx]
        colortbl_entries.append(f'\\red{r}\\green{g}\\blue{b}')

    # speaker colour ref in RTF is offset by 1 because cf1 is grey
    def speaker_cf(spk):
        return color_map[spk] + 1  # cf2 onwards

    colortbl_str = ''.join(f'{{{e}}}' for e in colortbl_entries)

    duration_str = format_timestamp(annotations[-1]['end']) if annotations else '00:00.000'
    speaker_counts = {}
    for a in annotations:
        speaker_counts[a['speaker']] = speaker_counts.get(a['speaker'], 0) + 1

    rtf_content = [
        r'{\rtf1\ansi\deff0',
        r'{\fonttbl{\f0\fswiss Arial;}{\f1\fmodern Courier New;}}',
        '{\\colortbl;' + colortbl_str + '}',
        f'\\viewkind4\\uc1\\pard\\f0\\fs{fs_main}',
        r'',
    ]

    # Title
    rtf_content.append(f'\\b\\fs{fs_title} Transcript\\b0\\fs{fs_main}\\par')
    rtf_content.append(r'\par')

    # Info block
    rtf_content.append(f'\\fs{fs_info}\\cf1')
    if eaf_filename:
        rtf_content.append(f'Source file: {escape_rtf(eaf_filename)}\\par')
    if tier_id:
        rtf_content.append(f'Tier: {escape_rtf(tier_id)}\\par')
    rtf_content.append(f'Total duration: {duration_str}\\par')
    for spk in unique_speakers:
        rtf_content.append(f'{escape_rtf(spk)} turns: {speaker_counts.get(spk, 0)}\\par')
    rtf_content.append(f'Total turns: {len(annotations)}\\par')
    if original_count > len(annotations):
        rtf_content.append(f'Original annotations: {original_count} (merged)\\par')
    rtf_content.append(f'\\cf0\\fs{fs_main}\\par')
    rtf_content.append(r'\par')

    # Horizontal rule
    rtf_content.append(r'\pard\brdrb\brdrs\brdrw10\brsp20\par')
    rtf_content.append(r'\pard\par')

    # Annotations
    for ann in annotations:
        text = escape_rtf(ann['text'])
        if not text:
            continue
        spk = ann['speaker']
        cf = f'\\cf{speaker_cf(spk)}'

        if include_timestamps:
            ts = format_timestamp(ann['start'])
            if compact:
                rtf_content.append(
                    f"\\f1\\fs{fs_timestamp}\\cf1 [{ts}]\\f0\\fs{fs_main}  "
                    f"{cf}\\b {escape_rtf(spk)}:\\b0\\cf0  {text}\\par\\par"
                )
            else:
                rtf_content.append(
                    f"\\f1\\fs{fs_timestamp}\\cf1 [{ts}]\\cf0\\f0\\fs{fs_main}\\par"
                )
                rtf_content.append(f"{cf}\\b {escape_rtf(spk)}:\\b0\\cf0\\par")
                rtf_content.append(f"\\li360 {text}\\par")
                rtf_content.append(r'\li0\par')
        else:
            if compact:
                rtf_content.append(
                    f"{cf}\\b {escape_rtf(spk)}:\\b0\\cf0  {text}\\par\\par"
                )
            else:
                rtf_content.append(f"{cf}\\b {escape_rtf(spk)}:\\b0\\cf0\\par")
                rtf_content.append(f"\\li360 {text}\\par")
                rtf_content.append(r'\li0\par')

    rtf_content.append(r'}')

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(rtf_content))


def main():
    parser = argparse.ArgumentParser(
        description=(
            'Export a single ELAN .eaf tier to RTF format.\n'
            'Use --separator to split multiple speakers embedded in one tier.\n'
            'Example: --separator P  will treat annotations "P1", "P2", etc. as\n'
            'speaker change markers; all speech between markers belongs to that speaker.'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        'eaf_file',
        type=str,
        help='Path to ELAN .eaf file',
    )
    parser.add_argument(
        '-t', '--tier',
        type=str,
        default=None,
        help='Tier ID to export (required unless --list-tiers is used)',
    )
    parser.add_argument(
        '--list-tiers',
        action='store_true',
        help='List all tiers in the EAF file and exit',
    )
    parser.add_argument(
        '-s', '--separator',
        type=str,
        default=None,
        metavar='PREFIX',
        help=(
            'Character prefix used to mark speaker changes inside the tier. '
            'Any annotation whose entire text matches <PREFIX><number> (e.g. "P1", "P2") '
            'is treated as a speaker marker, not speech. '
            'Example: --separator P  or  --separator INT'
        ),
    )
    parser.add_argument(
        '-o', '--output',
        type=str,
        help='Output RTF file path (default: <input>.rtf)',
    )
    parser.add_argument(
        '--no-timestamps',
        action='store_true',
        help='Exclude timestamps from output',
    )
    parser.add_argument(
        '--no-merge',
        action='store_true',
        help='Do not merge consecutive turns by the same speaker',
    )
    parser.add_argument(
        '--max-gap',
        type=float,
        default=5.0,
        help='Maximum gap in seconds to merge turns (default: 5.0)',
    )
    parser.add_argument(
        '--spaces',
        action='store_true',
        help='Join merged segments with spaces instead of line breaks',
    )
    parser.add_argument(
        '--compact',
        action='store_true',
        help='Use compact format (speaker and text on same line)',
    )
    parser.add_argument(
        '--font-size',
        type=int,
        default=12,
        help='Main text font size in points (default: 12)',
    )
    parser.add_argument(
        '-md', '--markdown',
        action='store_true',
        help='Output Markdown (.md) instead of RTF',
    )

    args = parser.parse_args()

    eaf_path = Path(args.eaf_file)
    if not eaf_path.exists():
        print(f"Error: File not found: {eaf_path}")
        return 1
    if eaf_path.suffix.lower() != '.eaf':
        print(f"Warning: File does not have .eaf extension: {eaf_path}")

    # --list-tiers mode
    if args.list_tiers:
        try:
            tiers = list_tiers(eaf_path)
            print(f"Tiers in {eaf_path.name}:")
            for t in tiers:
                print(f"  {t}")
        except ET.ParseError as e:
            print(f"Error parsing EAF file: {e}")
            return 1
        return 0

    if not args.tier:
        print("Error: --tier is required (use --list-tiers to see available tiers)")
        return 1

    if not args.markdown and (args.font_size < 6 or args.font_size > 72):
        print("Error: Font size must be between 6 and 72 points")
        return 1

    suffix = '.md' if args.markdown else '.rtf'
    output_path = Path(args.output) if args.output else eaf_path.with_suffix(suffix)

    print(f"Reading ELAN file: {eaf_path}")
    print(f"Tier: {args.tier}")
    if args.separator:
        print(f"Separator prefix: '{args.separator}' (matches {args.separator}1, {args.separator}2, …)")

    try:
        annotations = parse_eaf_single_tier(eaf_path, args.tier, args.separator)

        if not annotations:
            print("Warning: No speech annotations found in tier")
            return 1

        original_count = len(annotations)
        print(f"Found {original_count} annotations")

        if not args.no_merge:
            max_gap_ms = int(args.max_gap * 1000)
            annotations = merge_consecutive_turns(
                annotations,
                max_gap_ms,
                use_linebreaks=not args.spaces,
            )
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
                tier_id=args.tier,
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
                tier_id=args.tier,
            )

        print(f"Successfully exported to: {output_path}")
        print(f"\nStatistics:")
        print(f"  Original annotations: {original_count}")
        print(f"  Final turns: {len(annotations)}")

        speaker_counts = {}
        for a in annotations:
            speaker_counts[a['speaker']] = speaker_counts.get(a['speaker'], 0) + 1
        for spk, count in sorted(speaker_counts.items()):
            print(f"  {spk} turns: {count}")

        if annotations:
            print(f"  Total duration: {format_timestamp(annotations[-1]['end'])}")

        return 0

    except ValueError as e:
        print(f"Error: {e}")
        return 1
    except ET.ParseError as e:
        print(f"Error parsing EAF file: {e}")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    exit(main())
