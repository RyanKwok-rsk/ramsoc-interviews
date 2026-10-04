import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple


def load_rooms(rooms_csv: Path) -> Dict[str, List[str]]:
    """
    Read a CSV with columns: Day, room 1, room 2 and return
    a mapping like { 'Tue': ['Room A', 'Room B'], ... }.

    Header matching for room columns is case-insensitive and tolerates 'Room 1' vs 'room 1'.
    """
    with rooms_csv.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        # Normalize header keys to lower for robust access
        field_map = {name.lower(): name for name in reader.fieldnames or []}

        # Required columns
        day_key = field_map.get("day")
        r1_key = field_map.get("room 1") or field_map.get("room1")
        r2_key = field_map.get("room 2") or field_map.get("room2")
        if not (day_key and r1_key and r2_key):
            raise ValueError(
                "Rooms CSV must have headers: Day, room 1, room 2 (case-insensitive)."
            )

        rooms_by_day: Dict[str, List[str]] = {}
        for row in reader:
            day_raw = (row.get(day_key) or "").strip()
            if not day_raw:
                continue
            day = day_raw[:3]  # normalize to 3-letter abbrev e.g., Tue, Wed, Thu, Fri, Sat
            rooms_by_day[day] = [
                (row.get(r1_key) or "").strip(),
                (row.get(r2_key) or "").strip(),
            ]

    return rooms_by_day


def extract_day_and_slot(row: dict) -> Tuple[str, str]:
    """
    Prefer deriving day from 'Time Slot' like 'Tue-10' -> ('Tue', '10').
    If not available, fall back to 'Formatted Time', extracting the weekday name and hour.
    Returns (day_abbrev, slot_key) where slot_key groups concurrent interviews (e.g., '10').
    """
    ts = (row.get("Time Slot") or "").strip()
    if ts and "-" in ts:
        day, slot = ts.split("-", 1)
        return day, slot

    # Fallback to Formatted Time e.g., "21/10 Tuesday 10:00am"
    ft = (row.get("Formatted Time") or "").strip()
    parts = ft.split()
    if len(parts) >= 3:
        weekday = parts[1]
        time_part = parts[2]
        day = weekday[:3]
        # Use hour portion as slot key
        slot = time_part.split(":", 1)[0]
        return day, slot

    # Last resort
    return "", ""


def assign_rooms(
    schedule_csv: Path,
    rooms_csv: Path,
    output_csv: Path,
) -> Tuple[int, int]:
    """
    Assign rooms to each interview. Rooms are assigned per (day, timeslot) in round-robin order
    across the two rooms provided for that day. The input scheduling order is preserved.

    Returns: (num_rows, num_days_configured)
    """
    rooms_by_day = load_rooms(rooms_csv)

    with schedule_csv.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        headers = list(reader.fieldnames or [])

    if not rows:
        # Make an empty output with header including Room if we can
        base_headers = headers or []
        out_headers = base_headers + (["Room"] if "Room" not in base_headers else [])
        with output_csv.open("w", newline="", encoding="utf-8") as f_out:
            writer = csv.DictWriter(f_out, fieldnames=out_headers)
            writer.writeheader()
        return 0, len(rooms_by_day)

    # Prepare output headers (append Room if not present)
    out_headers = list(headers)
    if "Room" not in out_headers:
        out_headers.append("Room")

    # Counters per (day, slot), but capped at 2 to prefer Room 1 then Room 2
    counters: Dict[Tuple[str, str], int] = defaultdict(int)

    assigned_rows: List[dict] = []
    for row in rows:
        day, slot_key = extract_day_and_slot(row)
        if not day:
            raise ValueError(
                f"Unable to determine day/slot for row with Applicant={row.get('Applicant')}"
            )
        if day not in rooms_by_day:
            raise ValueError(
                f"No room configuration found for day '{day}'. Check rooms CSV."
            )

        rooms = rooms_by_day[day]
        if len(rooms) < 2 or not rooms[0] or not rooms[1]:
            raise ValueError(
                f"Day '{day}' must have two room names configured (room 1, room 2)."
            )

        idx = counters[(day, slot_key)]
        if idx >= 2:
            # Enforce the assumption: no more than 2 interviews per time slot
            raise ValueError(
                f"Found more than two interviews for {day}-{slot_key}. Scheduling assumption violated."
            )
        room_name = rooms[idx]  # 0 -> Room 1, 1 -> Room 2
        counters[(day, slot_key)] = idx + 1

        new_row = dict(row)
        new_row["Room"] = room_name
        assigned_rows.append(new_row)

    # Write output
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    with output_csv.open("w", newline="", encoding="utf-8") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=out_headers)
        writer.writeheader()
        writer.writerows(assigned_rows)

    return len(assigned_rows), len(rooms_by_day)


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Assign rooms to interviews based on a rooms-per-day CSV (Day, room 1, room 2)."
        )
    )
    parser.add_argument(
        "--input",
        default="final_schedule_formatted.csv",
        help="Path to the input schedule CSV (default: final_schedule_formatted.csv)",
    )
    parser.add_argument(
        "--rooms",
        default="rooms.csv",
        help="Path to the rooms CSV with columns: Day, room 1, room 2 (default: rooms.csv)",
    )
    parser.add_argument(
        "--output",
        default="final_schedule_with_rooms.csv",
        help="Path to the output CSV with Room column added (default: final_schedule_with_rooms.csv)",
    )

    args = parser.parse_args(argv)

    schedule_csv = Path(args.input)
    rooms_csv = Path(args.rooms)
    output_csv = Path(args.output)

    if not schedule_csv.exists():
        print(f"Input schedule file not found: {schedule_csv}", file=sys.stderr)
        return 2
    if not rooms_csv.exists():
        print(f"Rooms file not found: {rooms_csv}", file=sys.stderr)
        return 2

    n_rows, n_days = assign_rooms(schedule_csv, rooms_csv, output_csv)
    print(
        f"Assigned rooms for {n_rows} interviews across {n_days} configured days.\n"
        f"Output written to: {output_csv}"
    )
    return 0


if __name__ == "__main__":
    import sys as _sys

    raise SystemExit(main(_sys.argv[1:]))
