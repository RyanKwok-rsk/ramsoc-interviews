import random
import pandas as pd

# ------------------------
#  Parameters
# ------------------------
days = ["Tue", "Wed", "Thu", "Fri", "Sat"]
hours = list(range(9, 19))  # 9-18
num_interviewers = 10
num_positions = 8  # fixed list supplied below
num_applicants = 60
declined_applicants = 10  # additional applicants with no positions (simulate rejected)

# Applicant availability parameters
min_applicant_slots = 8   # minimum number of slots per applicant
max_applicant_slots = 18  # maximum number of slots per applicant

# ------------------------
# Generate applicants
# ------------------------
positions = [
    "Projects",
    "Workshops",
    "Women in Mechatronics",
    "Marketing & Creatives",
    "Socials",
    "Industry and Sponsorships",
    "Outreach",
    "IT",
]
applicants = []
applicant_emails = []
applicant_positions_joined = []
applicant_slot_strings = []

# Precompute all potential slots (union of day-hour pairs)
all_possible_slots = [f"{d}-{h}" for d in days for h in hours]

for i in range(1, num_applicants + 1):
    name = f"Applicant_{i}"
    # Each applicant applies to 1-3 positions
    num_applied_positions = random.randint(1, 3)
    applied_positions = random.sample(positions, num_applied_positions)
    applicants.append(name)
    # Simple deterministic email generation (lowercase, underscores for spaces)
    email_local = name.lower().replace(" ", "_")
    applicant_emails.append(f"{email_local}@example.com")
    applicant_positions_joined.append(
        ", ".join(applied_positions)
    )  # positions separated by comma+space

    # Generate availability subset for this applicant
    slots_count = random.randint(min_applicant_slots, max_applicant_slots)
    chosen_slots = sorted(random.sample(all_possible_slots, slots_count))
    applicant_slot_strings.append(
        ",".join(chosen_slots)
    )  # NOTE: interviewer/applicant CSVs use comma (no space) between slots

## Add declined applicants (empty position)
for j in range(1, declined_applicants + 1):
    name = f"Declined_{j}"
    email_local = name.lower().replace(" ", "_")
    applicants.append(name)
    applicant_emails.append(f"{email_local}@example.com")
    applicant_positions_joined.append("")  # empty position field
    # Give them availability (optional); could also be empty.
    slots_count = random.randint(min_applicant_slots, max_applicant_slots)
    chosen_slots = sorted(random.sample(all_possible_slots, slots_count))
    applicant_slot_strings.append(
        ",".join(chosen_slots)
    )

applicants_df = pd.DataFrame({
    "applicant": applicants,
    "email": applicant_emails,
    "position": applicant_positions_joined,
    "available_slots": applicant_slot_strings,
})
applicants_df.to_csv("applicants_dummy.csv", index=False)

print("✅ Dummy data generated for interviewers, positions, and applicants!")
