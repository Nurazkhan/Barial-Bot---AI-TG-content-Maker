TOKEN = ""
API_ID = 
API_HASH = 
GEMINI_TOKEN  = 
ADMIN_USER_ID = 

ALLOWED_USERS_FILE = "allowed_users.txt"

ALLOWED_USER_IDS = []
try:
    with open(ALLOWED_USERS_FILE, "r") as f:
        ALLOWED_USER_IDS = [int(line.strip()) for line in f if line.strip().isdigit()]
except Exception:
    pass

def save_allowed_users():
    with open(ALLOWED_USERS_FILE, "w") as f:
        for uid in ALLOWED_USER_IDS:
            f.write(f"{uid}\n")