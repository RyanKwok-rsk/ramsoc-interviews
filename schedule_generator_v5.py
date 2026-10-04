import pandas as pd
from itertools import combinations
from collections import defaultdict
from ortools.sat.python import cp_model

# =========================
#  LOAD INPUT DATA
# =========================
interviewers_df = pd.read_csv("interviewers.csv")
positions_df = pd.read_csv("positions.csv")
applicants_df = pd.read_csv("applicants.csv")

# Parse interviewer availability
availability = {
    row["interviewer"]: [slot.strip() for slot in row["available_slots"].split(",")]
    for _, row in interviewers_df.iterrows()
}

# Parse positions (multiple eligible interviewers); normalize position names by stripping whitespace
positions = {}
for _, row in positions_df.iterrows():
    pos_name_raw = row["position"]
    if not isinstance(pos_name_raw, str):
        continue
    pos_name = pos_name_raw.strip()
    if not pos_name:
        continue
    elig = [i.strip() for i in row["eligible_interviewers"].split(";") if i.strip()]
    positions[pos_name] = elig

# Parse applicants: allow multiple positions per row (comma-separated) and per-applicant availability
interview_requests = []  # list of (applicant, position) tuples
applicant_availability = {}
applicant_email = {}
declined = []  # list of (applicant, email)
# Track positions requested per applicant to allow custom constraints later
positions_by_applicant = {}
for _, row in applicants_df.iterrows():
    applicant_name_cell = row.get("applicant", "")
    if not isinstance(applicant_name_cell, str):
        continue
    applicant_name = applicant_name_cell.strip()
    if not applicant_name:
        continue
    email_val = row.get("email", "")
    email = email_val.strip() if isinstance(email_val, str) else ""
    applicant_email[applicant_name] = email
    # Raw position cell (may be NaN -> float)
    pos_cell = row.get("position", "")
    if isinstance(pos_cell, str):
        raw_positions = pos_cell
    else:
        # Treat NaN/None as empty string
        raw_positions = "" if pd.isna(pos_cell) else str(pos_cell)
    raw_positions_stripped = raw_positions.strip()
    if not raw_positions_stripped or raw_positions_stripped.lower() in {"nan", "na", "none"}:
        declined.append((applicant_name, email))
        continue
    position_list = [p.strip() for p in raw_positions_stripped.split(",") if p.strip()]
    # Deduplicate while preserving order
    seen = set()
    dedup_positions = []
    for p in position_list:
        if p not in seen:
            seen.add(p)
            dedup_positions.append(p)
    for pos in dedup_positions:
        if pos not in positions:
            # Skip silently; positions are expected to be defined, but we avoid KeyError
            continue
        interview_requests.append((applicant_name, pos))
    # record how many positions this applicant asked for
    positions_by_applicant[applicant_name] = dedup_positions
    # Availability (optional). Reuse same availability across all positions for this applicant
    if "available_slots" in row and isinstance(row["available_slots"], str) and row["available_slots"].strip():
        applicant_availability[applicant_name] = [s.strip() for s in row["available_slots"].split(",") if s.strip()]
    else:
        applicant_availability[applicant_name] = None  # None => treated as fully flexible later

# Gather all unique slots
all_slots = sorted(set(slot for slots in availability.values() for slot in slots))
all_days = sorted({slot.split('-')[0] for slot in all_slots})

# =========================
#  BUILD OPTIMIZATION MODEL
# =========================
model = cp_model.CpModel()

## =========================
##  MEETING-BASED VARIABLES
## =========================
# S[(applicant, position)] = 1 if that position is covered by some meeting
S = { (a,p): model.NewBoolVar(f"sched_{a}_{p}") for a,p in interview_requests }

# Build interviewer pair availability per slot (pairs available if both interviewers have the slot)
slot_interviewer_pairs = defaultdict(list)
for slot in all_slots:
    present = [i for i, slots in availability.items() if slot in slots]
    for i1, i2 in combinations(sorted(present), 2):
        slot_interviewer_pairs[slot].append((i1, i2))

# Y[(applicant, slot, i1, i2)] = meeting variable (pair (i1,i2) meets applicant at slot)
Y = {}
for applicant in {a for a,_ in interview_requests}:
    a_slots_list = applicant_availability.get(applicant)
    a_slot_set = set(a_slots_list) if a_slots_list else set(all_slots)
    for slot in all_slots:
        if slot not in a_slot_set:
            continue
        for (i1,i2) in slot_interviewer_pairs[slot]:
            Y[(applicant, slot, i1, i2)] = model.NewBoolVar(f"meet_{applicant}_{slot}_{i1}_{i2}")

# Precompute which meetings (applicant,slot,i1,i2) can cover each position (XOR eligible)
position_cover_meetings = defaultdict(list)
# Also build reverse mapping: for each meeting key, which positions it could cover
positions_from_meeting = defaultdict(list)
for (applicant, position) in interview_requests:
    elig = set(positions[position])
    a_slots_list = applicant_availability.get(applicant)
    a_slot_set = set(a_slots_list) if a_slots_list else set(all_slots)
    for slot in a_slot_set:
        for (i1,i2) in slot_interviewer_pairs.get(slot, []):
            # Exactly one eligible among pair for this position
            cond = ((i1 in elig) ^ (i2 in elig))
            if cond:
                key = (applicant, slot, i1, i2)
                if key in Y:
                    position_cover_meetings[(applicant, position)].append(key)
                    positions_from_meeting[key].append(position)

## =========================
##  CONSTRAINTS
## =========================
# Create assignment variables M linking positions to meetings they are covered by
M = {}  # M[(applicant, position, slot, i1, i2)] = 1 if that meeting covers that position
for (applicant, position) in interview_requests:
    for key in position_cover_meetings[(applicant, position)]:
        M[(applicant, position, *key[1:3], key[2], key[3] if len(key)>3 else key[2])] = None  # placeholder to keep unique keys

# Recreate M using consistent construction from keys in position_cover_meetings
M = {}
for (applicant, position) in interview_requests:
    for (a2, slot, i1, i2) in position_cover_meetings[(applicant, position)]:
        M[(applicant, position, slot, i1, i2)] = model.NewBoolVar(f"assign_{applicant}_{position}_{slot}_{i1}_{i2}")

# (A) Coverage via M: each scheduled position must be covered by exactly one meeting; unscheduled = 0
for (applicant, position) in interview_requests:
    covers = [M[(applicant, position, slot, i1, i2)] for (a2, slot, i1, i2) in position_cover_meetings[(applicant, position)]]
    if not covers:
        model.Add(S[(applicant, position)] == 0)
    else:
        model.Add(sum(covers) == S[(applicant, position)])

# Link M to Y: if a position is assigned to a meeting, that meeting must be selected
for (applicant, position) in interview_requests:
    for (a2, slot, i1, i2) in position_cover_meetings[(applicant, position)]:
        model.Add(M[(applicant, position, slot, i1, i2)] <= Y[(applicant, slot, i1, i2)])

# Ensure selected meetings cover at least one position: Y <= sum of M for that meeting
for (applicant, slot, i1, i2), yvar in Y.items():
    related_M = [M[(applicant, position, slot, i1, i2)]
                 for position in positions_from_meeting.get((applicant, slot, i1, i2), [])]
    if related_M:
        model.Add(yvar <= sum(related_M))
    else:
        # If no positions can be covered by this meeting, it should never be selected
        model.Add(yvar == 0)

# (B) Limit applicant: at most one meeting per slot
for applicant in {a for a,_ in interview_requests}:
    for slot in all_slots:
        model.Add( sum( Y[(a_slot_key)] for a_slot_key in Y if a_slot_key[0]==applicant and a_slot_key[1]==slot ) <= 1 )

# (B2) Force applicants who applied for exactly 3 positions to have at least 2 meetings
# This prevents a single meeting covering all three positions (user requirement).
for applicant, pos_list in positions_by_applicant.items():
    if len(pos_list) == 3:
        applicant_meetings = [var for (a, s, i1, i2), var in Y.items() if a == applicant]
        # If there are no possible meetings for this applicant, the solver will later mark positions unscheduled.
        if applicant_meetings:
            model.Add( sum(applicant_meetings) >= 2 )

# (C) Link positions to meetings logically (implicit via coverage). If you want to bound total meetings,
# you can add soft objective (minimize total meetings) instead of a hard limit.

# (D) Interviewer capacity: one meeting per interviewer per slot
for interviewer in availability:
    for slot in all_slots:
        meeting_vars = []
        for (a, s, i1, i2), var in Y.items():
            if s==slot and (i1==interviewer or i2==interviewer):
                meeting_vars.append(var)
        if meeting_vars:
            model.Add( sum(meeting_vars) <= 1 )

# (E) Global concurrency limit: no more than 2 meetings in the same slot overall
for slot in all_slots:
    slot_meetings = [var for (a,s,i1,i2), var in Y.items() if s == slot]
    if slot_meetings:
        model.Add(sum(slot_meetings) <= 2)

########################################
# 5️⃣ Interviewer fairness / load balance (from meetings)
########################################
interviewer_counts = {}
max_possible = len(Y)  # upper bound
for interviewer in availability:
    interviewer_counts[interviewer] = model.NewIntVar(0, max_possible, f"count_{interviewer}")
    # Count meetings involving interviewer
    rel = [var for (a,s,i1,i2), var in Y.items() if i1==interviewer or i2==interviewer]
    if rel:
        model.Add(interviewer_counts[interviewer] == sum(rel))
    else:
        model.Add(interviewer_counts[interviewer] == 0)

max_count = model.NewIntVar(0, max_possible, "max_count")
min_count = model.NewIntVar(0, max_possible, "min_count")
model.AddMaxEquality(max_count, [interviewer_counts[i] for i in availability])
model.AddMinEquality(min_count, [interviewer_counts[i] for i in availability])
fairness_gap = model.NewIntVar(0, max_possible, "fairness_gap")
model.Add(fairness_gap == max_count - min_count)

# Interviewer day usage variables
D = {}
for interviewer in availability:
    for day in all_days:
        D[(interviewer, day)] = model.NewBoolVar(f"day_{interviewer}_{day}")
        # If interviewer attends any meeting on that day, variable must be 1
        rel_meetings = [var for (a, s, i1, i2), var in Y.items() if (i1==interviewer or i2==interviewer) and s.startswith(day+"-")]
        if rel_meetings:
            model.Add( sum(rel_meetings) <= len(rel_meetings) * D[(interviewer, day)] )
            # If any meeting chosen then D must be 1 (linearization): for each meeting m: m <= D
            for m in rel_meetings:
                model.Add( m <= D[(interviewer, day)] )
        else:
            model.Add( D[(interviewer, day)] == 0 )

total_days_used = sum(D.values())

## =========================
##  OBJECTIVE
## =========================
unscheduled = sum(1 - S[(a,p)] for a,p in interview_requests)
total_meetings = sum(Y.values())
model.Minimize( unscheduled * 1_000_000 + total_meetings * 10_000 + total_days_used * 1_000 + fairness_gap * 1_000 + max_count )

# =========================
#  SOLVE MODEL
# =========================
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 60
result = solver.Solve(model)

# =========================
#  OUTPUT RESULTS
# =========================
if result in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
    # Map meetings to positions they cover using M assignments
    meeting_positions = defaultdict(list)
    for (applicant, position) in interview_requests:
        for (a2, slot, i1, i2) in position_cover_meetings[(applicant, position)]:
            if solver.Value(M[(applicant, position, slot, i1, i2)]) == 1:
                meeting_positions[(applicant, slot, i1, i2)].append(position)

    rows = []
    for (applicant, slot, i1, i2), positions_list in meeting_positions.items():
        rows.append({
            "Applicant": applicant,
            "Email": applicant_email.get(applicant, ""),
            "Positions": ", ".join(sorted(positions_list)),
            "Interviewers": f"{i1}, {i2}",
            "Time Slot": slot
        })
    schedule_df = pd.DataFrame(rows)
    if not schedule_df.empty:
        schedule_df = schedule_df.sort_values(by=["Time Slot","Applicant"])
        schedule_df.to_csv("final_schedule.csv", index=False)
        print("✅ Schedule Generated (meetings may cover multiple positions):\n")
        print(schedule_df)
    else:
        print("⚠️ No meetings scheduled.")

    # Unscheduled position reasons
    unscheduled_rows = []
    for (applicant, position) in interview_requests:
        if solver.Value(S[(applicant, position)]) == 0:
            reason = "No feasible interviewer pair (XOR condition) with applicant availability"
            if position_cover_meetings[(applicant, position)]:
                # They had possible theoretical coverage but objective may have skipped due to trade-offs
                reason = "Dropped due to optimization trade-off (meeting minimization / fairness)"
            unscheduled_rows.append({"Applicant": applicant, "Position": position, "Reason": reason})
    if unscheduled_rows:
        unsched_df = pd.DataFrame(unscheduled_rows)
        unsched_df.to_csv("unscheduled_positions.csv", index=False)
        print("\nUnscheduled Positions:")
        print(unsched_df)

    # Declined applicants output
    if declined:
        declined_df = pd.DataFrame(declined, columns=["Applicant","Email"])
        declined_df.to_csv("declined_applicants.csv", index=False)
        print("\nDeclined Applicants (no positions listed):")
        print(declined_df)

    # Fairness stats (report based on scheduled meetings only)
    print("\nInterviewer load balance:")
    from collections import defaultdict as _dd
    rep_counts = _dd(int)
    rep_days = _dd(set)
    for (applicant, slot, i1, i2), positions_list in meeting_positions.items():
        rep_counts[i1] += 1
        rep_counts[i2] += 1
        day = slot.split('-')[0]
        rep_days[i1].add(day)
        rep_days[i2].add(day)

    # Print per interviewer, ensuring all interviewers appear
    counts_list = []
    for interviewer in availability:
        c = rep_counts.get(interviewer, 0)
        counts_list.append(c)
        days_used = sorted(list(rep_days.get(interviewer, set())))
        print(f" - {interviewer}: {c} meetings across {len(days_used)} day(s) -> {days_used}")

    # Consistency check against solver internal count (optional, info only)
    try:
        mismatched = []
        for interviewer in availability:
            model_count = solver.Value(interviewer_counts[interviewer])
            rep_count = rep_counts.get(interviewer, 0)
            if model_count != rep_count:
                mismatched.append((interviewer, rep_count, model_count))
        if mismatched:
            print("\n[info] Detected differences between reported counts and model counts (rep vs model):")
            for name, rep_c, mod_c in mismatched:
                print(f"   - {name}: {rep_c} vs {mod_c}")
    except Exception:
        pass

    gap = solver.Value(fairness_gap)
    print(f"Max: {max(counts_list) if counts_list else 0}, Min: {min(counts_list) if counts_list else 0}, Gap: {gap}")
    # Total interviewer-days from report
    total_days_used_report = sum(len(rep_days[i]) for i in availability)
    print(f"Total interviewer-days used: {total_days_used_report}")

    # Export interviewer counts for verification
    try:
        rep_rows = []
        for interviewer in availability:
            rep_rows.append({
                "Interviewer": interviewer,
                "Meetings": rep_counts.get(interviewer, 0),
                "Days": ", ".join(sorted(list(rep_days.get(interviewer, set())))),
                "DaysCount": len(rep_days.get(interviewer, set())),
            })
        pd.DataFrame(rep_rows).to_csv("interviewer_counts.csv", index=False)
        print("Interviewer counts written to interviewer_counts.csv")
    except Exception:
        pass
else:
    print("❌ No feasible solution found.")

# (Old per-position model removed above)
