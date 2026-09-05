

import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow

CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]


def authenticate():
    if not os.path.exists(CREDENTIALS_FILE):
        print(f"Error: {CREDENTIALS_FILE} not found in project directory.")
        return

    # Delete cached token if present to force clean authentication
    if os.path.exists(TOKEN_FILE):
        os.remove(TOKEN_FILE)

    with open(CREDENTIALS_FILE, "r") as f:
        data = json.load(f)
        key_name = "installed" if "installed" in data else "web"
        client_id = data.get(key_name, {}).get("client_id", "Unknown")

    
    print("--- Starting Gmail OAuth Authentication ---")
    print(f"Active Client ID: {client_id}")
    

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
    auth_url, _ = flow.authorization_url(prompt="select_account", access_type="offline")

    print("Please copy and paste this URL into your browser (or Incognito window):\n")
    print(auth_url)
    

    creds = flow.run_local_server(port=0, prompt="select_account")

    with open(TOKEN_FILE, "w") as token:
        token.write(creds.to_json())

    print(f"\nSUCCESS! Gmail OAuth authentication complete.")
    print(f"Token saved to: {os.path.abspath(TOKEN_FILE)}")


if __name__ == "__main__":
    authenticate()
