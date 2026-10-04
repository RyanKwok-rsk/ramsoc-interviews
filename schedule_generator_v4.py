import pandas as pd
from itertools import combinations
from collections import defaultdict
from ortools.sat.python import cp_model

# =========================
#  LOAD INPUT DATA
# =========================
interviewers_df = pd.read_csv("interviewers.csv")
positions_df = pd.read_csv("positions.csv")
applicants_df = pd.read_csv("applicants_dummy.csv")

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
for _, row in applicants_df.iterrows():
    applicant_name = row["applicant"].strip()
    # Split positions on comma, allowing for forms like "Role A, Role B" or single value
    raw_positions = row["position"] if isinstance(row["position"], str) else str(row["position"])
    position_list = [p.strip() for p in raw_positions.split(",") if p.strip()]
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
    # Availability (optional). Reuse same availability across all positions for this applicant
    if "available_slots" in row and isinstance(row["available_slots"], str) and row["available_slots"].strip():
        applicant_availability[applicant_name] = [s.strip() for s in row["available_slots"].split(",") if s.strip()]
    else:
        applicant_availability[applicant_name] = None  # None => treated as fully flexible later

# Gather all unique slots
all_slots = sorted(set(slot for slots in availability.values() for slot in slots))

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

## =========================
##  CONSTRAINTS
## =========================
# (A) Coverage: each scheduled position must be covered by exactly one meeting; unscheduled = 0
for (applicant, position) in interview_requests:
    covers = position_cover_meetings[(applicant, position)]
    if not covers:
        # No feasible meeting can cover this position -> force unscheduled
        model.Add(S[(applicant, position)] == 0)
    else:
        model.Add( sum( Y[key] for key in covers ) == S[(applicant, position)] )

# (B) Limit applicant: at most one meeting per slot
for applicant in {a for a,_ in interview_requests}:
    for slot in all_slots:
        model.Add( sum( Y[(a_slot_key)] for a_slot_key in Y if a_slot_key[0]==applicant and a_slot_key[1]==slot ) <= 1 )

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

## =========================
##  OBJECTIVE
## =========================
unscheduled = sum(1 - S[(a,p)] for a,p in interview_requests)
total_meetings = sum(Y.values())
model.Minimize( unscheduled * 1_000_000 + total_meetings * 10_000 + fairness_gap * 1000 + max_count )

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
    # Map meetings to positions they cover
    meeting_positions = defaultdict(list)
    for (applicant, position) in interview_requests:
        if solver.Value(S[(applicant, position)]) == 1:
            for key in position_cover_meetings[(applicant, position)]:
                if solver.Value(Y[key]) == 1:
                    meeting_positions[key].append(position)
                    break

    rows = []
    for (applicant, slot, i1, i2), positions_list in meeting_positions.items():
        rows.append({
            "Applicant": applicant,
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

    # Fairness stats
    print("\nInterviewer load balance:")
    counts = []
    for interviewer in availability:
        c = solver.Value(interviewer_counts[interviewer])
        counts.append(c)
        print(f" - {interviewer}: {c} meetings")
    gap = solver.Value(fairness_gap)
    print(f"Max: {max(counts) if counts else 0}, Min: {min(counts) if counts else 0}, Gap: {gap}")
else:
    print("❌ No feasible solution found.")

# (Old per-position model removed above)
