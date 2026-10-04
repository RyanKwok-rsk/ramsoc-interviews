# availability_generator.py

# Aneesa
# available_days = ['Tue', 'Wed', 'Thu', 'Fri', 'Sat']
# time_availabilities = [(9, 18), (15, 18), (15, 18), (17, 18), (14, 18)]

# # Teonie
# available_days = ['Tue', 'Wed', 'Fri', 'Sat']
# time_availabilities = [(10, 18), (10, 17), (10, 17), (10, 18)]

# Ryan
# available_days = ['Tue', 'Thu', 'Fri', 'Sat']
# time_availabilities = [(9, 18), (9, 18), (9, 18), (9, 18)]

# Artem
# available_days = ['Tue', 'Wed', 'Thu', 'Fri', 'Sat']
# time_availabilities = [(9, 18), (9, 18), (9, 18), (9, 12), (9, 18)]

# Trisha
# available_days = ['Tue', 'Wed', 'Thu', 'Sat']
# time_availabilities = [(11, 18), (11, 18), (11, 18), (12, 18)]

# Sammy
# available_days = ['Tue', 'Wed', 'Thu', 'Fri', 'Sat']
# time_availabilities = [(10, 18), (10, 18), (10, 18), (10, 18), (10, 18)]

# Sam
available_days = ['Tue', 'Thu', 'Sat']
time_availabilities = [(11, 18), (11, 18), (11, 18)]

def generate_availability_strings(days, time_ranges):
    availability = []
    for day, (start, end) in zip(days, time_ranges):
        # If end < start, assume it wraps to next day (optional)
        for hour in range(start, end):
            availability.append(f"{day}-{hour}")
    return ",".join(availability)

if __name__ == "__main__":
    result = generate_availability_strings(available_days, time_availabilities)
    print(result)