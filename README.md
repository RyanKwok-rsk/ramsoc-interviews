# ramsoc-interviews

This repository generates interview schedules and produces:

- `final_schedule_with_rooms.csv` (final output with room assignments)

## Prerequisites

- Python 3.10+ (tested with Python 3)
- Install dependencies:

```bash
pip install pandas ortools
```

## Required input files

These files are read by the workflow:

- `interviewers.csv`
- `positions.csv`
- `applicants.csv`
- `rooms.csv`

## Generate `final_schedule_with_rooms.csv`

Run from the repository root:

```bash
python schedule_generator_v5.py
python format_timeslots.py --tuesday 21/10/2025
python assign_rooms.py --input final_schedule_formatted.csv --rooms rooms.csv --output final_schedule_with_rooms.csv
```

After this, `final_schedule_with_rooms.csv` will be created/updated.

## Optional follow-up output

To split applicants into single-interview vs multi-interview files:

```bash
python separate_interviews.py --input final_schedule_with_rooms.csv --singles single_interview_applicants.csv --multis multi_interview_applicants.csv
```

## Notes

- `schedule_generator_v5.py` writes `final_schedule.csv`.
- `format_timeslots.py` adds a `Formatted Time` column and writes `final_schedule_formatted.csv`.
- `assign_rooms.py` adds a `Room` column and writes `final_schedule_with_rooms.csv`.
