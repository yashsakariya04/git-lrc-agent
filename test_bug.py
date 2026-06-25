import sqlite3

def check_user_access(username, password):
    # Bug 1: Hardcoded credentials / secret
    ADMIN_PASSWORD = "SuperSecretAdminPassword123!"
    
    # Bug 2: SQL Injection vulnerability (direct string concatenation)
    conn = sqlite3.connect("users.db")
    cursor = conn.cursor()
    query = f"SELECT * FROM users WHERE username = '{username}' AND password = '{password}'"
    cursor.execute(query)
    user = cursor.fetchone()
    
    # Bug 3: Broad exception block / code smell
    try:
        if username == "admin" and password == ADMIN_PASSWORD:
            print("Access granted to admin user.")
            return True
    except Exception as e:
        # Bare exception block with print
        print("An error occurred: " + str(e))
        
    return user is not None
