"""One-time Gmail authorization.

Run once:  python authorize_gmail.py

Opens a browser for you to grant access to the connected Gmail account, then
caches the token to token.json so the server never needs to re-auth (until the
refresh token is revoked). Safe to re-run; it reuses an existing valid token.
"""

from app.services.gmail import get_profile


def main() -> None:
    profile = get_profile()  # triggers the OAuth flow if no valid token exists
    print("Authorized Gmail account:")
    print(f"  email:          {profile.get('emailAddress')}")
    print(f"  total messages: {profile.get('messagesTotal')}")
    print("Token cached to token.json — future runs will not prompt.")


if __name__ == "__main__":
    main()
