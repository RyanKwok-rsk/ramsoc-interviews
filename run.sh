py -3 .\schedule_generator_v5.py
py -3 .\format_timeslots.py --tuesday 21/10/2025
py -3 .\assign_rooms.py --input .\final_schedule_formatted.csv --rooms .\rooms.csv --output .\final_schedule_with_rooms.csv
py -3 .\separate_interviews.py --input .\final_schedule_with_rooms.csv --singles .\single_interview_applicants.csv --multis .\multi_interview_applicants.csv