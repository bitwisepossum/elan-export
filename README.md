# ELAN Export Scripts

Helper scripts for exporting annotation data from [ELAN](https://archive.mpi.nl/tla/elan) `.eaf` files into readable RTF or Markdown format. Intended for qualitative research workflows where transcripts need to be reviewed or shared outside of ELAN.

---

## `elan_interview.py`

Export a **two-tier interview** (interviewer + participant) into a single formatted transcript. Consecutive turns by the same speaker are merged for readability.

```
python3 elan_interview.py interview.eaf
```

| Flag | Description |
|---|---|
| `eaf_file` | Path to the `.eaf` file |
| `-o FILE` | Output file path (default: same name as input) |
| `--int-tier NAME` | Tier ID for the interviewer (default: `INT_speech`) |
| `--participant-tier NAME` | Tier ID for the participant (default: `PARTICIPANT_speech`) |
| `--int-name NAME` | Display name for the interviewer (default: `Interviewer`) |
| `--participant-name NAME` | Display name for the participant (default: `Participant`) |
| `--markdown` / `-md` | Output Markdown instead of RTF |
| `--compact` | Speaker and text on the same line |
| `--no-timestamps` | Omit timestamps |
| `--no-merge` | Disable turn merging |
| `--max-gap SEC` | Max gap in seconds for merging turns (default: `5.0`) |
| `--spaces` | Join merged segments with spaces instead of line breaks |
| `--font-size PT` | RTF font size in points (default: `12`) |

---

## `elan_tier.py`

Export a **single tier** from any `.eaf` file. Useful when all speech is in one tier, optionally with embedded speaker markers.

```
python3 elan_tier.py recording.eaf --tier speech_tier
```

| Flag | Description |
|---|---|
| `eaf_file` | Path to the `.eaf` file |
| `-t / --tier NAME` | Tier ID to export |
| `--list-tiers` | List all tiers in the file and exit |
| `-s / --separator PREFIX` | Prefix used for speaker change markers (e.g. `P` matches `P1`, `P2`, …) |
| `-o FILE` | Output file path (default: same name as input) |
| `--markdown` / `-md` | Output Markdown instead of RTF |
| `--compact` | Speaker and text on the same line |
| `--no-timestamps` | Omit timestamps |
| `--no-merge` | Disable turn merging |
| `--max-gap SEC` | Max gap in seconds for merging turns (default: `5.0`) |
| `--spaces` | Join merged segments with spaces instead of line breaks |
| `--font-size PT` | RTF font size in points (default: `12`) |

---

## Citation

ELAN (Version 7.0) [Computer software]. (2025). Nijmegen: Max Planck Institute for Psycholinguistics, The Language Archive. Retrieved from https://archive.mpi.nl/tla/elan
