"""
Run this ONCE, locally, on your own machine — never in CI.
Logs in with your Garmin credentials (handles MFA prompt if needed) and
writes the resulting token files to ~/.garminconnect.

After this, run load_token_to_db.py to push that token into Neon.
Your Garmin password is never stored anywhere after this step.
"""

import getpass
import pathlib

from garminconnect import Garmin

TOKEN_DIR = pathlib.Path.home() / ".garminconnect"


def main() -> None:
    email = input("Garmin email: ").strip()
    password = getpass.getpass("Garmin password: ")

    TOKEN_DIR.mkdir(parents=True, exist_ok=True)

    client = Garmin(
        email,
        password,
        prompt_mfa=lambda: input("Enter the MFA code Garmin just sent you: ").strip(),
    )
    client.login(tokenstore=str(TOKEN_DIR))

    # The library's own dump-on-login is wrapped in contextlib.suppress(Exception),
    # so it can fail silently. Call it again ourselves, unsuppressed, to be sure.
    client.client.dump(str(TOKEN_DIR))

    token_file = TOKEN_DIR / "garmin_tokens.json"
    if not token_file.exists():
        raise RuntimeError(f"dump() ran without error but {token_file} still doesn't exist.")

    print(f"Token written to {token_file}")
    print("Next: run bootstrap/load_token_to_db.py to push it to Neon.")


if __name__ == "__main__":
    main()
