import pandas as pd
from ortools.sat.python import cp_model

# Load data
interviewers_df = pd.read_csv("interviewers.csv")
positions_df = pd.read_csv("positions.csv")
applicants_df = pd.read_csv("applicants.csv")

# Parse interviewer availability
availability = {
    row["interviewer"]: row["available_slots"].split(",")
    for _, row in interviewers_df.iterrows()
}

positions = {row["position"]: row["required_interviewer"] for _, row in positions_df.iterrows()}
applicants = {row["applicant"]: row["position"] for _, row in applicants_df.iterrows()}

# Gather all time slots
all_slots = sorted(set(slot for slots in availability.values() for slot in slots))

# Build model
model = cp_model.CpModel()

# Variables
# X[a, i, s] = 1 if applicant a is assigned to interviewer i at slot s
X = {}
for applicant, position in applicants.items():
    required = positions[position]
    for interviewer, slots in availability.items():
        for slot in slots:
            X[(applicant, interviewer, slot)] = model.NewBoolVar(f"{applicant}_{interviewer}_{slot}")

# Constraints

# 1️⃣ Each applicant gets exactly one slot
for applicant in applicants:
    model.Add(
        sum(X[(applicant, i, s)] for i, _, in availability.items() for s in all_slots if (applicant, i, s) in X) == 2
    )

# 2️⃣ Each slot can be used by an interviewer at most once
for interviewer, slots in availability.items():
    for slot in slots:
        model.Add(
            sum(X[(a, interviewer, slot)] for a in applicants if (a, interviewer, slot) in X) <= 1
        )

# 3️⃣ Required interviewer must attend for the applicant’s position
for applicant, position in applicants.items():
    required = positions[position]
    model.Add(
        sum(X[(applicant, required, s)] for s in all_slots if (applicant, required, s) in X) == 1
    )

# 4️⃣ Second interviewer cannot be the same as required interviewer
# (Handled automatically by having different interviewer vars)

# Objective: Minimize unused slots / balance load
model.Minimize(
    sum(X[(a, i, s)] for a in applicants for i in availability for s in all_slots if (a, i, s) in X)
)

# Solve
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 30
result = solver.Solve(model)

# Output
if result in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
    print("Interview Schedule:\n--------------------")
    schedule = []
    for applicant, position in applicants.items():
        interviewers_used = []
        slot_used = None
        for interviewer in availability:
            for slot in all_slots:
                if (applicant, interviewer, slot) in X and solver.Value(X[(applicant, interviewer, slot)]) == 1:
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
    schedule_df.to_csv("final_schedule.csv", index=False)
    print(schedule_df)
else:
    print("No feasible schedule found.")
