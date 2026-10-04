import sys
import pandas as pd
from pathlib import Path
import csv


def build_calendar_df(days, hours):
	# Build columns like Tue-Room-1, Tue-Room-2 for each day
	cols = ["Time"]
	for d in days:
		cols.append(f"{d}-Room-1")
		cols.append(f"{d}-Room-2")
	rows = []
	for h in hours:
		label = f"{h}:00"
		row = {"Time": label}
		for d in days:
			row[f"{d}-Room-1"] = ""
			row[f"{d}-Room-2"] = ""
		rows.append(row)
	return pd.DataFrame(rows, columns=cols)


def load_rooms_mapping(rooms_csv_path: Path):
	"""
	If rooms.csv exists, build a mapping: day_abbrev -> {room_name: index(1 or 2)}
	Used to ensure the correct room name maps to Room-1/Room-2 per day.
	If not available, return empty dict to derive from data order.
	"""
	mapping = {}
	if not rooms_csv_path.exists():
		return mapping
	with rooms_csv_path.open(newline="", encoding="utf-8-sig") as f:
		reader = csv.DictReader(f)
		# Normalize headers lower
		fields = {k.lower(): k for k in (reader.fieldnames or [])}
		day_key = fields.get("day")
		r1_key = fields.get("room 1") or fields.get("room1")
		r2_key = fields.get("room 2") or fields.get("room2")
		if not (day_key and r1_key and r2_key):
			return mapping
		for row in reader:
			day_raw = (row.get(day_key) or "").strip()
			if not day_raw:
				continue
			day = day_raw[:3]
			r1_name = (row.get(r1_key) or "").strip()
			r2_name = (row.get(r2_key) or "").strip()
			if r1_name and r2_name:
				mapping[day] = {r1_name: 1, r2_name: 2}
	return mapping


def to_calendar(schedule_csv="final_schedule_with_rooms.csv", out_csv="calendar_schedule.csv", out_xlsx="calendar_schedule.xlsx"):
	days_order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
	hours = list(range(9, 19))  # 9..18 inclusive

	schedule_path = Path(schedule_csv)
	if not schedule_path.exists():
		print(f"Input schedule not found: {schedule_csv}")
		return

	df = pd.read_csv(schedule_path)
	required_cols = {"Applicant", "Email", "Positions", "Interviewers", "Time Slot", "Room"}
	missing = required_cols - set(df.columns)
	if missing:
		raise ValueError(f"Missing required column(s) in {schedule_csv}: {', '.join(sorted(missing))}")

	# Determine which days are present from the data (use order Mon..Sun when available)
	present_days = []
	for ts in df["Time Slot"].dropna().astype(str):
		if "-" in ts:
			day = ts.split("-", 1)[0].strip()
			abbr = day[:3]
			if abbr not in present_days:
				present_days.append(abbr)
	days = [d for d in days_order if d in present_days]
	if not days:
		# fallback to Tue..Sat if nothing parsed
		days = ["Tue", "Wed", "Thu", "Fri", "Sat"]

	# Load rooms mapping if available (rooms.csv)
	rooms_map = load_rooms_mapping(Path("rooms.csv"))

	cal_df = build_calendar_df(days, hours)
	cal_df.set_index("Time", inplace=True)

	# For days without explicit rooms map, derive by order of appearance per day
	derived_map = {}

	# Fill calendar cells
	for _, row in df.iterrows():
		time_slot = str(row["Time Slot"]) if pd.notna(row["Time Slot"]) else ""
		if "-" not in time_slot:
			continue
		day_raw, hour_str = time_slot.split("-", 1)
		day = day_raw.strip()[:3]
		try:
			hour = int(hour_str)
		except ValueError:
			continue

		if day not in days:
			continue
		if hour not in hours:
			continue

		time_label = f"{hour}:00"
		# Compose cell content
		applicant = str(row.get("Applicant", "")).strip()
		positions = str(row.get("Positions", "")).strip()
		interviewers = str(row.get("Interviewers", "")).strip()
		room_name = str(row.get("Room", "")).strip()

		entry = f"{applicant} - {positions} ({interviewers})"

		# Resolve room index 1/2 for this day
		day_map = rooms_map.get(day)
		if not day_map:
			# derive
			day_map = derived_map.setdefault(day, {})
			if room_name and room_name not in day_map and len(day_map) < 2:
				day_map[room_name] = len(day_map) + 1
		# Fallback if still unknown or room name missing
		idx = day_map.get(room_name)
		if idx not in (1, 2):
			# Default to Room-1 when ambiguous
			idx = 1

		col = f"{day}-Room-{idx}"
		existing = cal_df.at[time_label, col]
		if pd.isna(existing) or existing == "":
			cal_df.at[time_label, col] = entry
		else:
			# Shouldn't happen if constraints enforce one per room per slot; still append to be safe
			cal_df.at[time_label, col] = f"{existing} | {entry}"

	# Reset index to write Time as first column
	cal_df = cal_df.reset_index()

	# Save CSV
	cal_df.to_csv(out_csv, index=False)
	print(f"📄 Wrote calendar CSV: {out_csv}")

	# Save XLSX for nicer spreadsheet viewing
	try:
		with pd.ExcelWriter(out_xlsx, engine="xlsxwriter") as writer:
			cal_df.to_excel(writer, sheet_name="Calendar", index=False)
			# Optional: set column widths for readability
			ws = writer.sheets["Calendar"]
			ws.set_column(0, 0, 8)   # Time
			ws.set_column(1, len(cal_df.columns)-1, 50)
		print(f"📊 Wrote calendar Excel: {out_xlsx}")
	except Exception as e:
		print(f"Note: could not write XLSX ({e}). CSV was created successfully.")


if __name__ == "__main__":
	# Optional CLI: python convert_to_calendar.py [input_csv] [out_csv] [out_xlsx]
	args = sys.argv[1:]
	if len(args) == 0:
		to_calendar()
	elif len(args) == 1:
		to_calendar(schedule_csv=args[0])
	elif len(args) == 2:
		to_calendar(schedule_csv=args[0], out_csv=args[1])
	else:
		to_calendar(schedule_csv=args[0], out_csv=args[1], out_xlsx=args[2])

