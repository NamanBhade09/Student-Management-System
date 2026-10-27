import pyodbc

def get_db_connection():
    try:
        conn = pyodbc.connect(
            "DRIVER={ODBC Driver 18 for SQL Server};"
            "SERVER=localhost\\SQLEXPRESS;"
            "DATABASE=SMS;"
            "Trusted_Connection=yes;"
            "Encrypt=yes;"
            "TrustServerCertificate=yes;"
        )
        return conn
    except Exception as e:
        print(f"Database Connection Error: {e}")
        return None