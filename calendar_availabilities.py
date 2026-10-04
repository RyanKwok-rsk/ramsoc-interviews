import sys
from pathlib import Path
import pandas as pd


def build_calendar(days, hours):
	cols = ["Time"] + days
	rows = []
	for h in hours:
		label = f"{h}:00"
		row = {"Time": label}
		for d in days:
			row[d] = ""
		rows.append(row)
	return pd.DataFrame(rows, columns=cols)


def parse_slots(available_slots):
	if not isinstance(available_slots, str) or not available_slots.strip():
		return []
	return [s.strip() for s in available_slots.split(",") if s.strip()]


def to_calendar_availabilities(
	interviewers_csv: str = "interviewers.csv",
	out_csv: str = "calendar_availabilities.csv",
	out_xlsx: str = "calendar_availabilities.xlsx",
):
	days = ["Tue", "Wed", "Thu", "Fri", "Sat"]
	hours = list(range(9, 19))

	path = Path(interviewers_csv)
	if not path.exists():
		print(f"Input not found: {interviewers_csv}")
		return

	df = pd.read_csv(path)
	req = {"interviewer", "available_slots"}
	missing = req - set(df.columns)
	if missing:
		raise ValueError(f"Missing required column(s) in {interviewers_csv}: {', '.join(sorted(missing))}")

	# Build empty calendar and index by Time
	cal = build_calendar(days, hours)
	cal.set_index("Time", inplace=True)

	# Build mapping day-hour to list of interviewers
	grid = {d: {h: [] for h in hours} for d in days}

	for _, row in df.iterrows():
		name = str(row.get("interviewer", "")).strip()
		slots = parse_slots(row.get("available_slots", ""))
		for slot in slots:
			if "-" not in slot:
				continue
			day, hour_str = slot.split("-", 1)
			day = day.strip()
			try:
				hour = int(hour_str)
			except ValueError:
				continue
			if day in grid and hour in grid[day]:
				grid[day][hour].append(name)

	# Fill calendar with sorted unique names
	for d in days:
		for h in hours:
			names = sorted(set(grid[d][h]))
			label = f"{h}:00"
			cal.at[label, d] = ", ".join(names)

	# Write outputs
	cal = cal.reset_index()
	cal.to_csv(out_csv, index=False)
	print(f"📄 Wrote availability calendar CSV: {out_csv}")
	try:
		with pd.ExcelWriter(out_xlsx, engine="xlsxwriter") as writer:
			cal.to_excel(writer, sheet_name="Availabilities", index=False)
			ws = writer.sheets["Availabilities"]
			ws.set_column(0, 0, 8)
			ws.set_column(1, len(days), 50)
		print(f"📊 Wrote availability calendar Excel: {out_xlsx}")
	except Exception as e:
		print(f"Note: could not write XLSX ({e}). CSV was created successfully.")


if __name__ == "__main__":
	args = sys.argv[1:]
	if not args:
		to_calendar_availabilities()
	elif len(args) == 1:
		to_calendar_availabilities(interviewers_csv=args[0])
	elif len(args) == 2:
		to_calendar_availabilities(interviewers_csv=args[0], out_csv=args[1])
	else:
		to_calendar_availabilities(interviewers_csv=args[0], out_csv=args[1], out_xlsx=args[2])

