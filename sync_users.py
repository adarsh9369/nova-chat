import os
import csv
import json
import time
import sqlite3
import re
import requests

# Paths
JS_CONFIG_PATH = r"d:\files\APP\firebase_config.js"
CSV_PATH = r"d:\files\APP\registered_users.csv"
DB_PATH = r"d:\files\APP\nebula_chat.db"

def get_firebase_url():
    """Extract databaseURL from firebase_config.js dynamically."""
    default_url = "https://nebulachat-demo-default-rtdb.firebaseio.com/users.json"
    if os.path.exists(JS_CONFIG_PATH):
        try:
            with open(JS_CONFIG_PATH, "r", encoding="utf-8") as f:
                content = f.read()
                # Try double quoted format: "databaseURL": "value"
                match = re.search(r'"databaseURL":\s*"([^"]+)"', content)
                if not match:
                    # Try single quoted or unquoted JS format: databaseURL: "value"
                    match = re.search(r"databaseURL:\s*['\"]([^'\"]+)['\"]", content)
                if match:
                    base_url = match.group(1).rstrip("/")
                    url = f"{base_url}/users.json"
                    print(f"Loaded Firebase URL from configuration file: {url}")
                    return url
        except Exception as e:
            print(f"Error parsing firebase_config.js: {e}")
    print(f"Fallback to default Firebase URL: {default_url}")
    return default_url

def init_db():
    """Ensure the users table exists in the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            name TEXT,
            theme TEXT,
            last_seen INTEGER
        )
    """)
    conn.commit()
    conn.close()

def sync_local(users_data):
    """Write users to CSV and upsert to SQLite database."""
    if not users_data:
        users_data = {}

    # 1. Sync to CSV
    try:
        with open(CSV_PATH, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["Username", "Display Name", "Theme", "Last Seen"])
            for username, details in users_data.items():
                if not isinstance(details, dict):
                    continue
                writer.writerow([
                    details.get("username", username),
                    details.get("name", ""),
                    details.get("theme", "indigo"),
                    details.get("last_seen", 0)
                ])
        print(f"[{time.strftime('%H:%M:%S')}] Synced users list to CSV.")
    except Exception as e:
        print(f"Error writing to CSV: {e}")

    # 2. Sync to SQLite
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        for username, details in users_data.items():
            if not isinstance(details, dict):
                continue
            cursor.execute("""
                INSERT INTO users (username, name, theme, last_seen)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    name=excluded.name,
                    theme=excluded.theme,
                    last_seen=excluded.last_seen
            """, (
                details.get("username", username),
                details.get("name", ""),
                details.get("theme", "indigo"),
                details.get("last_seen", 0)
            ))
        conn.commit()
        conn.close()
        print(f"[{time.strftime('%H:%M:%S')}] Synced users to SQLite Database.")
    except Exception as e:
        print(f"Error writing to SQLite: {e}")

def fetch_and_sync(firebase_url):
    """Fetch the latest state from Firebase and write it locally."""
    try:
        response = requests.get(firebase_url, timeout=10)
        if response.status_code == 200:
            users_data = response.json()
            sync_local(users_data)
        else:
            print(f"Failed to fetch data: HTTP {response.status_code}")
    except Exception as e:
        print(f"Error during manual fetch: {e}")

def listen_to_firebase():
    """Establish a real-time SSE stream listener to Firebase users.json."""
    print("Starting real-time Firebase sync agent...")
    init_db()
    
    # Loop to handle configuration reading and stream reconnections
    while True:
        firebase_url = get_firebase_url()
        # Perform initial sync
        fetch_and_sync(firebase_url)
        
        try:
            print(f"Connecting to Firebase database stream at {firebase_url}...")
            headers = {"Accept": "text/event-stream"}
            # Stream the events
            response = requests.get(firebase_url, headers=headers, stream=True, timeout=60)
            
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8').strip()
                    if decoded_line.startswith("event:"):
                        event_type = decoded_line.replace("event:", "").strip()
                        # If we get a put or patch, perform a fresh sync
                        if event_type in ["put", "patch"]:
                            time.sleep(0.2)
                            # Reload the config just in case it was modified
                            current_url = get_firebase_url()
                            fetch_and_sync(current_url)
        except requests.exceptions.RequestException as e:
            print(f"Stream connection lost: {e}. Retrying in 5 seconds...")
            time.sleep(5)
        except Exception as e:
            print(f"Unexpected error: {e}. Retrying in 5 seconds...")
            time.sleep(5)

if __name__ == "__main__":
    listen_to_firebase()
