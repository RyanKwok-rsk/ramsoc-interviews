import pandas as pd
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

# Decision variables:
# S[(applicant, position)] = 1 if interview request scheduled, else 0
S = {}
for applicant, position in interview_requests:
    S[(applicant, position)] = model.NewBoolVar(f"sched_{applicant}_{position}")

# X[(applicant, position, interviewer, slot)] only for slots where both interviewer and applicant available
X = {}
for applicant, position in interview_requests:
    a_slots = applicant_availability.get(applicant)
    if a_slots is None:
        # will interpret as all slots interviewer has (union will be handled implicitly)
        a_slots_set = None
    else:
        a_slots_set = set(a_slots)
    for interviewer, slots in availability.items():
        for slot in slots:
            if a_slots_set is not None and slot not in a_slots_set:
                continue
            X[(applicant, position, interviewer, slot)] = model.NewBoolVar(
                f"{applicant}_{position}_{interviewer}_{slot}"
            )

# =========================
#  CONSTRAINTS
# =========================

# 1️⃣ Each interview request must have exactly two interviewers
for applicant, position in interview_requests:
    # If scheduled: exactly 2 interviewer-slot assignments
    model.Add(
        sum(
            X[(applicant, position, i, s)]
            for i in availability
            for s in all_slots
            if (applicant, position, i, s) in X
        ) == 2 * S[(applicant, position)]
    )

# 2️⃣ An interviewer can only attend one interview per slot
for interviewer, slots in availability.items():
    for slot in slots:
        model.Add(
            sum(
                X[(a, p, interviewer, slot)]
                for a, p in interview_requests
                if (a, p, interviewer, slot) in X
            ) <= 1
        )

# 3️⃣ One interviewer must come from the eligible list for that position
for applicant, position in interview_requests:
    eligible = positions[position]
    model.Add(
        sum(
            X[(applicant, position, i, s)]
            for i in eligible
            for s in all_slots
            if (applicant, position, i, s) in X
        ) == S[(applicant, position)]
    )

# 4️⃣ Second interviewer must be chosen from outside the eligible list AND be in the same slot
for applicant, position in interview_requests:
    eligible = positions[position]
    for slot in all_slots:
        model.Add(
            sum(
                X[(applicant, position, i, slot)]
                for i in availability
                if i not in eligible and (applicant, position, i, slot) in X
            ) <= S[(applicant, position)]
        )
    model.Add(
        sum(
            X[(applicant, position, i, slot)]
            for i in availability
            for slot in all_slots
            if i not in eligible and (applicant, position, i, slot) in X
        ) == S[(applicant, position)]
    )

########################################
# 5️⃣ Interviewer fairness / load balance
########################################
# Create count variables for each interviewer (# of interviews they attend)
interviewer_counts = {}
max_possible = len(interview_requests)  # upper bound per interviewer
for interviewer in availability:
    interviewer_counts[interviewer] = model.NewIntVar(0, max_possible, f"count_{interviewer}")
    model.Add(
        interviewer_counts[interviewer]
        == sum(
            X[(a, p, interviewer, s)]
            for a, p in interview_requests
            for s in all_slots
            if (a, p, interviewer, s) in X
        )
    )

# Global max/min of interviewer loads
max_count = model.NewIntVar(0, max_possible, "max_count")
min_count = model.NewIntVar(0, max_possible, "min_count")
model.AddMaxEquality(max_count, [interviewer_counts[i] for i in availability])
model.AddMinEquality(min_count, [interviewer_counts[i] for i in availability])

# Fairness gap variable (difference)
fairness_gap = model.NewIntVar(0, max_possible, "fairness_gap")
model.Add(fairness_gap == max_count - min_count)
# IMPORTANT: No hard cap is imposed on fairness. This keeps the model from becoming infeasible
# due purely to balance considerations. Fairness is optimized only via the objective below.


# =========================
#  OBJECTIVE FUNCTION
# =========================
# Objective: First minimize fairness gap, then (tie-breaker) minimize total used assignments
total_assignments = sum(
    X[(a, p, i, s)]
    for a, p in interview_requests
    for i in availability
    for s in all_slots
    if (a, p, i, s) in X
)
unscheduled = sum(1 - S[(a, p)] for a, p in interview_requests)
# Weighted objective: minimize unscheduled first, then fairness, then total assignments
model.Minimize(unscheduled * 1000000 + fairness_gap * 1000 + total_assignments)

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
    scheduled_rows = []
    unscheduled_rows = []
    for applicant, position in interview_requests:
        if solver.Value(S[(applicant, position)]) == 1:
            # Collect assigned interviewers and slot (expect both in same slot due to constraints)
            assigned = [
                (i, s)
                for i in availability
                for s in all_slots
                if (applicant, position, i, s) in X and solver.Value(X[(applicant, position, i, s)]) == 1
            ]
            if assigned:
                slot_used = assigned[0][1]
                interviewers_used = [i for i, _ in assigned]
                scheduled_rows.append({
                    "Applicant": applicant,
                    "Position": position,
                    "Interviewers": ", ".join(interviewers_used),
                    "Time Slot": slot_used,
                })
        else:
            # Reason analysis for unscheduled
            eligible = positions[position]
            a_slots = applicant_availability.get(applicant)
            a_slots_set = set(a_slots) if a_slots else None
            eligible_pairs = []
            outside_pairs = []
            for interviewer, slots in availability.items():
                for slot in slots:
                    if a_slots_set is not None and slot not in a_slots_set:
                        continue
                    if (applicant, position, interviewer, slot) not in X:
                        continue
                    if interviewer in eligible:
                        eligible_pairs.append((interviewer, slot))
                    else:
                        outside_pairs.append((interviewer, slot))
            issues = []
            if not eligible_pairs:
                issues.append("No eligible interviewer overlapping applicant availability.")
            if not outside_pairs:
                issues.append("No outside interviewer overlapping applicant availability.")
            if eligible_pairs and outside_pairs:
                # Check overlap of slots for pairing feasibility
                common = set(s for _, s in eligible_pairs) & set(s for _, s in outside_pairs)
                if not common:
                    issues.append("Eligible and outside interviewers never share a common slot.")
            unscheduled_rows.append({
                "Applicant": applicant,
                "Position": position,
                "Reason": "; ".join(issues) if issues else "Global contention / fairness trade-off",
            })

    schedule_df = pd.DataFrame(scheduled_rows)
    if not schedule_df.empty:
        schedule_df = schedule_df.sort_values(by="Time Slot")
        schedule_df.to_csv("final_schedule.csv", index=False)
        print("✅ Partial/Full Schedule Generated:\n")
        print(schedule_df)
    else:
        print("⚠️ No interviews scheduled.")

    if unscheduled_rows:
        unsched_df = pd.DataFrame(unscheduled_rows)
        print("\nUnscheduled Requests:")
        print(unsched_df)
        unsched_df.to_csv("unscheduled_requests.csv", index=False)

    # Fairness statistics (only counts from scheduled assignments)
    print("\nInterviewer load balance:")
    counts = []
    for interviewer in availability:
        c = solver.Value(interviewer_counts[interviewer])
        counts.append(c)
        print(f" - {interviewer}: {c} interviews")
    gap = solver.Value(fairness_gap)
    print(f"Max count: {max(counts) if counts else 0}, Min count: {min(counts) if counts else 0}, Gap: {gap}")
else:
    print("❌ Solver ended with status code but not feasible/optimal. This is unexpected.")
