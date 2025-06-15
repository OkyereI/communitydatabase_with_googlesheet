# from werkzeug.security import generate_password_hash, check_password_hash

# # Test with the problematic password
# password_complex = 'executive@2025'
# hashed_complex = generate_password_hash(password_complex)
# check_complex_1 = check_password_hash(password_complex, hashed_complex)
# check_complex_2 = check_password_hash('WRONG', hashed_complex) # Test wrong password

# # Test with the simplest password
# password_simple = 'pass'
# hashed_simple = generate_password_hash(password_simple)
# check_simple_1 = check_password_hash(password_simple, hashed_simple)
# check_simple_2 = check_password_hash('wrong', hashed_simple) # Test wrong password


# print(f"--- Standalone Werkzeug Hashing Test ---")
# print(f"\nPassword: '{password_complex}'")
# print(f"Generated Hash: '{hashed_complex}'")
# print(f"Check against generated hash (should be True): {check_complex_1}")
# print(f"Check wrong password ('WRONG') against generated hash (should be False): {check_complex_2}")

# print(f"\nPassword: '{password_simple}'")
# print(f"Generated Hash: '{hashed_simple}'")
# print(f"Check against generated hash (should be True): {check_simple_1}")
# print(f"Check wrong password ('wrong') against generated hash (should be False): {check_simple_2}")

# print(f"----------------------------------------")