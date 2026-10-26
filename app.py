from flask import Flask, render_template, request, jsonify
from connection import connection

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('login.html')

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    conn = connection()
    if not conn:
        return jsonify({"success": False, "message": "Database connection failed."})

    try:
        cursor = conn.cursor()

        # EXTRACT: Query the users table for the entered username
        cursor.execute("SELECT password_hash, role FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()

        if user:
            # Extract the VARBINARY password from the database
            stored_password_bytes = user.password_hash
            user_role = user.role

            # Convert the extracted bytes back to a string to check
            stored_password = stored_password_bytes.decode('utf-8')

            # CHECK: Compare the typed password with the extracted one
            if password == stored_password:
                return jsonify({
                    "success": True, 
                    "message": "Login Successful!",
                    "role": user_role
                })
            else:
                return jsonify({"success": False, "message": "Invalid password."})
        else:
            return jsonify({"success": False, "message": "Username not found."})

    except Exception as e:
        print(f"Database Error: {e}")
        return jsonify({"success": False, "message": "Server error. Check terminal."})
        
    finally:
        if conn:
            conn.close() # Always close the connection after extracting

if __name__ == '__main__':
    app.run(debug=True, port=5000)