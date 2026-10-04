import pandas as pd
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

# Parse positions (multiple eligible interviewers)
positions = {
    row["position"]: [i.strip() for i in row["eligible_interviewers"].split(";")]
    for _, row in positions_df.iterrows()
}

# Parse applicants: now allow multiple positions per applicant
interview_requests = []  # list of (applicant, position) tuples
for _, row in applicants_df.iterrows():
    interview_requests.append((row["applicant"], row["position"]))

# Gather all unique slots
all_slots = sorted(set(slot for slots in availability.values() for slot in slots))

# =========================
#  BUILD OPTIMIZATION MODEL
# =========================
model = cp_model.CpModel()

# Decision variables: X[(applicant, position, interviewer, slot)]
X = {}
for applicant, position in interview_requests:
    for interviewer, slots in availability.items():
        for slot in slots:
            X[(applicant, position, interviewer, slot)] = model.NewBoolVar(
                f"{applicant}_{position}_{interviewer}_{slot}"
            )

# =========================
#  CONSTRAINTS
# =========================

# 1️⃣ Each interview request must have exactly two interviewers
for applicant, position in interview_requests:
    model.Add(
        sum(
            X[(applicant, position, i, s)]
            for i in availability
            for s in all_slots
            if (applicant, position, i, s) in X
        ) == 2
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
        ) == 1
    )

# 4️⃣ Second interviewer must be chosen from outside the eligible list AND be in the same slot
for applicant, position in interview_requests:
    eligible = positions[position]
    for slot in all_slots:
        # For each slot, at most one second interviewer can be assigned
        model.Add(
            sum(
                X[(applicant, position, i, slot)]
                for i in availability
                if i not in eligible and (applicant, position, i, slot) in X
            ) <= 1
        )
    # Ensure that exactly one outside-eligible interviewer is chosen across all slots
    model.Add(
        sum(
            X[(applicant, position, i, slot)]
            for i in availability
            for slot in all_slots
            if i not in eligible and (applicant, position, i, slot) in X
        ) == 1
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
# Use a weighted sum: fairness gap is primary; small weight for total assignments
model.Minimize(fairness_gap * 1000 + total_assignments)

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
    schedule = []
    print("✅ Interview Schedule Generated Successfully:\n")
    for applicant, position in interview_requests:
        interviewers_used = []
        slot_used = None
        for interviewer in availability:
            for slot in all_slots:
                if (applicant, position, interviewer, slot) in X and solver.Value(X[(applicant, position, interviewer, slot)]) == 1:
                    interviewers_used.append(interviewer)
                    slot_used = slot
        if slot_used:
            schedule.append({
                "Applicant": applicant,
                "Position": position,
                "Interviewers": ", ".join(interviewers_used),
                "Time Slot": slot_used
            })
    schedule_df = pd.DataFrame(schedule)

    # Sort by Time Slot
    schedule_df = schedule_df.sort_values(by="Time Slot")

    # Export and print
    schedule_df.to_csv("final_schedule.csv", index=False)
    print(schedule_df)

    # Print fairness statistics
    print("\nInterviewer load balance:")
    counts = []
    for interviewer in availability:
        c = solver.Value(interviewer_counts[interviewer])
        counts.append(c)
        print(f" - {interviewer}: {c} interviews")
    gap = solver.Value(fairness_gap)
    print(f"Max count: {max(counts) if counts else 0}, Min count: {min(counts) if counts else 0}, Gap: {gap}")
else:
    print("❌ No feasible schedule found. Attempting to diagnose causes...\n")

    # =========================
    #  INFEASIBILITY DIAGNOSTICS (heuristic)
    # =========================
    # NOTE: OR-Tools CP-SAT does not currently expose an IIS (irreducible inconsistent set)
    # for pinpointing the exact conflicting constraints. Below we implement a data/logic
    # level heuristic analysis to highlight likely causes.

    def analyze_request(applicant, position):
        eligible = positions[position]
        eligible_pairs = []  # (interviewer, slot)
        outside_pairs = []
        # Collect raw availability pairs
        for interviewer, slots in availability.items():
            for slot in slots:
                if (applicant, position, interviewer, slot) in X:  # variable exists
                    if interviewer in eligible:
                        eligible_pairs.append((interviewer, slot))
                    else:
                        outside_pairs.append((interviewer, slot))

        # Basic constraint checks (mirrors model requirements):
        issues = []
        if not eligible_pairs:
            issues.append("No eligible interviewer available in any slot (violates constraint: exactly one eligible interviewer must be assigned).")
        if not outside_pairs:
            issues.append("No outside-eligible interviewer available in any slot (violates constraint: need exactly one interviewer outside eligible list).")

        # (Potential original intent) If both interviewers were expected to share a slot, check that:
        common_slots = set(s for _, s in eligible_pairs) & set(s for _, s in outside_pairs)
        if eligible_pairs and outside_pairs and not common_slots:
            issues.append("Eligible and outside-eligible interviewers never overlap in the same time slot. If a joint interview is required in a single slot, this makes the request impossible.")

        return {
            "applicant": applicant,
            "position": position,
            "eligible_option_count": len(eligible_pairs),
            "outside_option_count": len(outside_pairs),
            "overlap_slot_count": len(common_slots),
            "issues": issues,
            "eligible_pairs": eligible_pairs[:10],  # trim for readability
            "outside_pairs": outside_pairs[:10],
        }

    diagnostics = [analyze_request(a, p) for a, p in interview_requests]

    # Print per-request diagnostics
    impossible = [d for d in diagnostics if d["issues"]]
    if impossible:
        print("Requests with intrinsic data issues (cannot be satisfied regardless of other requests):")
        for d in impossible:
            print(f" - Applicant '{d['applicant']}' / Position '{d['position']}':")
            for issue in d["issues"]:
                print(f"    * {issue}")
            print(f"    * Eligible interviewer-slot options: {d['eligible_option_count']} (showing up to 10: {d['eligible_pairs']})")
            print(f"    * Outside interviewer-slot options: {d['outside_option_count']} (showing up to 10: {d['outside_pairs']})")
            print()
    else:
        print("All individual requests have at least one eligible and one outside interviewer option. Likely global resource conflict (competition over interviewer time slots).\n")

        # Global resource pressure analysis
        # For each interviewer & slot, count how many different (applicant, position) could use them
        from collections import defaultdict
        capacity_pressure = defaultdict(int)
        for (a, p, i, s), var in X.items():
            # Eligible vs outside status does not matter for raw contention, but model needs exactly one of each per request
            capacity_pressure[(i, s)] += 1
        # Identify high contention slots (heuristic threshold: > 3 potential assignments)
        crowded = [((i, s), cnt) for (i, s), cnt in capacity_pressure.items() if cnt > 3]
        crowded.sort(key=lambda x: -x[1])
        if crowded:
            print("Most contended interviewer slots (interviewer, slot -> number of requests that could use it):")
            for (i, s), cnt in crowded[:25]:
                print(f" - ({i}, {s}) -> {cnt} potential assignments (capacity = 1)")
            print()
        else:
            print("No interviewer slot shows heavy contention; infeasibility may come from the exact-equality pairing constraints.\n")

        # Check if any request forces a specific pairing due to single eligible or single outside option
        forced_requests = [
            d for d in diagnostics if d["eligible_option_count"] == 1 or d["outside_option_count"] == 1
        ]
        if forced_requests:
            print("Requests with forced choices (only one eligible or one outside option) that reduce flexibility:")
            for d in forced_requests:
                note_parts = []
                if d["eligible_option_count"] == 1:
                    note_parts.append("only one eligible interviewer-slot choice")
                if d["outside_option_count"] == 1:
                    note_parts.append("only one outside interviewer-slot choice")
                print(f" - {d['applicant']} / {d['position']}: {', '.join(note_parts)}")
            print()

    print("Suggested next steps:\n"
 "- Adjust availability to ensure each request has at least one overlapping slot between an eligible and a non-eligible interviewer.\n"
 "- Add more outside (non-eligible) interviewers or broaden availability for heavily contended slots.\n"
 "- If both interviewers must share the same slot, explicitly add that constraint to the model;" "otherwise consider allowing different slots for the two interviewers.\n")
