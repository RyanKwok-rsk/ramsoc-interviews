import sys
import argparse
import pandas as pd
from datetime import datetime, timedelta, date
from pathlib import Path


DAY_ABBR_TO_OFFSET = {"Tue": 0, "Wed": 1, "Thu": 2, "Fri": 3, "Sat": 4}
DAY_ABBR_TO_FULL = {"Tue": "Tuesday", "Wed": "Wednesday", "Thu": "Thursday", "Fri": "Friday", "Sat": "Saturday"}


def parse_date(value: str) -> date:
    """Parse a date in either YYYY-MM-DD or DD/MM/YYYY format."""
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(f"Invalid date format: '{value}'. Use YYYY-MM-DD or DD/MM/YYYY.")


def next_tuesday(from_date: date | None = None) -> date:
    """Get the next upcoming Tuesday (or today if today is Tuesday)."""
    d = from_date or date.today()
    # Python: Monday=0, Tuesday=1
    days_ahead = (1 - d.weekday()) % 7
    return d + timedelta(days=days_ahead)


def hour_to_12h(hour: int) -> str:
    am_pm = "am" if hour < 12 else "pm"
    hr12 = hour if 1 <= hour <= 12 else ((hour - 1) % 12) + 1
    return f"{hr12}:00{am_pm}"


def build_formatter(tuesday_date: date):
    def format_slot(slot: str) -> str:
        if not isinstance(slot, str) or "-" not in slot:
            return ""
        day_abbr, hour_str = slot.split("-", 1)
        day_abbr = day_abbr.strip()
        if day_abbr not in DAY_ABBR_TO_OFFSET:
            return ""
        try:
            hour = int(hour_str)
        except ValueError:
            return ""
        day_dt = tuesday_date + timedelta(days=DAY_ABBR_TO_OFFSET[day_abbr])
        date_str = day_dt.strftime("%d/%m")
        day_full = DAY_ABBR_TO_FULL[day_abbr]
        time_str = hour_to_12h(hour)
        return f"{date_str} {day_full} {time_str}"

    return format_slot


def run(input_csv: str, output_csv: str, replace: bool, tue_date: date | None):
    input_path = Path(input_csv)
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_csv}")

    df = pd.read_csv(input_path)
    if "Time Slot" not in df.columns:
        raise ValueError("Input CSV must contain a 'Time Slot' column.")

    base_tue = tue_date or next_tuesday()
    fmt = build_formatter(base_tue)
    formatted = df["Time Slot"].apply(fmt)

    if replace:
        df["Time Slot"] = formatted
    else:
        # Use list.index to guarantee an int index even if there are duplicate labels
        time_col_pos = list(df.columns).index("Time Slot")
        df.insert(time_col_pos + 1, "Formatted Time", formatted)

    df.to_csv(output_csv, index=False)
    print(f"Wrote: {output_csv} (base Tuesday: {base_tue.isoformat()})")


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description="Format 'Time Slot' like 'Tue-10' into '21/10 Tuesday 10:00am'.")
    parser.add_argument("input", nargs="?", default="final_schedule.csv", help="Input CSV (default: final_schedule.csv)")
    parser.add_argument("output", nargs="?", default="final_schedule_formatted.csv", help="Output CSV (default: final_schedule_formatted.csv)")
    parser.add_argument("--tuesday", "-t", type=parse_date, help="Date for Tuesday (YYYY-MM-DD or DD/MM/YYYY). If omitted, uses next Tuesday from today.")
    parser.add_argument("--replace", action="store_true", help="Replace 'Time Slot' column instead of adding 'Formatted Time'.")
    args = parser.parse_args(argv)

    run(args.input, args.output, args.replace, args.tuesday)


if __name__ == "__main__":
    main()
