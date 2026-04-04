"""One-time script to generate Gmail OAuth token JSON.

Usage:
    pip install google-auth-oauthlib
    python generate_token.py

It will open a browser for Google login, then print the token JSON
to paste into your GMAIL_OAUTH_JSON GitHub secret.
"""

import json

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

# Paste your OAuth Client ID and Client Secret from Google Cloud Console
CLIENT_ID = input("Enter your Google OAuth Client ID: ").strip()
CLIENT_SECRET = input("Enter your Google OAuth Client Secret: ").strip()

client_config = {
    "installed": {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": ["http://localhost"],
    }
}

flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
creds = flow.run_local_server(port=0)

token_data = {
    "token": creds.token,
    "refresh_token": creds.refresh_token,
    "token_uri": creds.token_uri,
    "client_id": creds.client_id,
    "client_secret": creds.client_secret,
    "scopes": list(creds.scopes),
}

token_json = json.dumps(token_data)
print("\n" + "=" * 60)
print("Copy this entire JSON string into your GMAIL_OAUTH_JSON secret:")
print("=" * 60)
print(token_json)
print("=" * 60)
