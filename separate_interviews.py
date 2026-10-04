import argparse
import csv
import sys
from pathlib import Path
from typing import Dict, List, Tuple


def parse_time_components(formatted_time: str) -> Tuple[int, int, int, int]:
    """
    Parse a string like "24/10 Friday 10:00am" into a sortable tuple (month, day, hour24, minute).
    This avoids relying on locale/weekday consistency. If parsing fails, return a tuple that sorts last.
    """
    try:
        # Expect tokens: ["DD/MM", "Weekday", "HH:MMam/pm"]
        parts = formatted_time.strip().split()
        if len(parts) < 3:
            raise ValueError("Unexpected formatted time format")

        date_part = parts[0]  # DD/MM
        time_part = parts[2]  # e.g., 10:00am

        day_str, month_str = date_part.split("/")
        dd = int(day_str)
        mm = int(month_str)

        # Parse time like 10:00am or 1:00pm
        t_num = time_part[:-2]  # remove am/pm
        ampm = time_part[-2:].lower()
        hour_str, minute_str = t_num.split(":")
        hh = int(hour_str)
        mi = int(minute_str)
        if ampm == "pm" and hh != 12:
            hh += 12
        if ampm == "am" and hh == 12:
            hh = 0

        return (mm, dd, hh, mi)
    except Exception:
        # Place unparseable times at the end
        return (99, 99, 99, 99)


def sort_interviews(rows: List[dict]) -> List[dict]:
    return sorted(rows, key=lambda r: (
        # Primary: parsed formatted time
        parse_time_components(r.get("Formatted Time", "")),
        # Fallback: use Time Slot ordering if needed
        r.get("Time Slot", "ZZ-99"),
    ))


def separate_interviews(
    input_csv: Path,
    singles_csv: Path,
    multis_csv: Path,
) -> Tuple[int, int, int]:
    """
    Process the input schedule CSV and produce two outputs.

    Returns: (num_applicants_total, num_single, num_multi)
    """
    with input_csv.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        # Create empty outputs with appropriate headers
        singles_csv.write_text("", encoding="utf-8")
        multis_csv.write_text("", encoding="utf-8")
        return (0, 0, 0)

    # Group by Email (unique identifier for applicants)
    by_email: Dict[str, List[dict]] = {}
    for r in rows:
        email = r.get("Email") or ""
        if not email:
            # Skip rows without an Email (cannot uniquely group)
            continue
        by_email.setdefault(email, []).append(r)

    # Prepare headers
    base_headers: List[str] = list(rows[0].keys())
    second_headers = [
        "Second Positions",
        "Second Interviewers",
        "Second Time Slot",
        "Second Formatted Time",
    ]
    # If Room is part of input, add Second Room to multis
    has_room = "Room" in base_headers
    if has_room:
        second_headers.append("Second Room")
    multi_headers = base_headers + second_headers

    singles: List[dict] = []
    multis: List[dict] = []

    for email, interviews in by_email.items():
        # Sort interviews chronologically (best-effort)
        s_interviews = sort_interviews(interviews)
        if len(s_interviews) == 1:
            singles.append(s_interviews[0])
        else:
            # Take the first two interviews; log if more than two
            if len(s_interviews) > 2:
                print(
                    f"[notice] Applicant {s_interviews[0].get('Applicant')} ({email}) has {len(s_interviews)} interviews; taking earliest two.",
                    file=sys.stderr,
                )
            first, second = s_interviews[0], s_interviews[1]
            combined = dict(first)  # start with first interview fields
            extra = {
                "Second Positions": second.get("Positions", ""),
                "Second Interviewers": second.get("Interviewers", ""),
                "Second Time Slot": second.get("Time Slot", ""),
                "Second Formatted Time": second.get("Formatted Time", ""),
            }
            if has_room:
                extra["Second Room"] = second.get("Room", "")
            combined.update(extra)
            multis.append(combined)

    # Write singles CSV with same columns as input
    singles_csv.parent.mkdir(parents=True, exist_ok=True)
    with singles_csv.open("w", newline="", encoding="utf-8") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=base_headers)
        writer.writeheader()
        writer.writerows(singles)

    # Write multis CSV with extra second interview columns
    multis_csv.parent.mkdir(parents=True, exist_ok=True)
    with multis_csv.open("w", newline="", encoding="utf-8") as f_out:
        writer = csv.DictWriter(f_out, fieldnames=multi_headers)
        writer.writeheader()
        writer.writerows(multis)

    return (len(by_email), len(singles), len(multis))


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Separate schedule CSV into two files: single-interview applicants and multi-interview applicants (with second interview details)."
        )
    )
    parser.add_argument(
        "--input",
        default="final_schedule_formatted.csv",
        help="Path to the input schedule CSV (default: final_schedule_formatted.csv)",
    )
    parser.add_argument(
        "--singles",
        default="single_interview_applicants.csv",
        help="Output CSV for applicants with exactly one interview (default: single_interview_applicants.csv)",
    )
    parser.add_argument(
        "--multis",
        default="multi_interview_applicants.csv",
        help=(
            "Output CSV for applicants with two or more interviews, including second interview details (default: multi_interview_applicants.csv)"
        ),
    )

    args = parser.parse_args(argv)

    input_csv = Path(args.input)
    singles_csv = Path(args.singles)
    multis_csv = Path(args.multis)

    if not input_csv.exists():
        print(f"Input file not found: {input_csv}", file=sys.stderr)
        return 2

    total, n_single, n_multi = separate_interviews(input_csv, singles_csv, multis_csv)
    print(
        f"Processed {total} applicants -> singles: {n_single}, multis: {n_multi}.\n"
        f"Outputs: {singles_csv} , {multis_csv}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
