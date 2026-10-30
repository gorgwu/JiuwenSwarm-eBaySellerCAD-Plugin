"""One-time interactive eBay OAuth setup. Uses only Python's standard library."""

from __future__ import annotations

import argparse
import base64
import getpass
import json
import os
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ebayseller_common.oauth import load_settings, settings_file_path

AUTH_BASES = {"sandbox": "https://auth.sandbox.ebay.com", "production": "https://auth.ebay.com"}
API_BASES = {"sandbox": "https://api.sandbox.ebay.com", "production": "https://api.ebay.com"}
SCOPE = " ".join("https://api.ebay.com/oauth/api_scope/" + name for name in (
    "sell.account", "sell.inventory", "sell.fulfillment",
))


def authorization_url(environment: str, client_id: str, runame: str, state: str, *, include_refunds: bool = False, account: str = 'seller') -> str:
    scopes = ('https://api.ebay.com/oauth/api_scope' if account == 'buyer' else SCOPE + (" https://api.ebay.com/oauth/api_scope/sell.finances" if include_refunds else ""))
    params = {"client_id": client_id, "redirect_uri": runame, "response_type": "code", "scope": scopes, "state": state}
    if account == 'buyer':
        params['prompt'] = 'login'
    return AUTH_BASES[environment] + "/oauth2/authorize?" + urllib.parse.urlencode(params)


def authorization_code(callback_url: str, expected_state: str) -> str:
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(callback_url.strip()).query)
    if "error" in query:
        raise ValueError("eBay did not grant access. Check the account sign-in and try again.")
    if query.get("state") != [expected_state]:
        raise ValueError("The callback state did not match this setup attempt. Start again with the newly opened URL.")
    code = query.get("code", [""])[0]
    if not code:
        raise ValueError("No code was found in the callback URL. Save the RuName's Auth Accepted URL and repeat setup.")
    return code


def exchange_code(environment: str, client_id: str, client_secret: str, runame: str, code: str) -> str:
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
    body = urllib.parse.urlencode({"grant_type": "authorization_code", "code": code, "redirect_uri": runame}).encode("utf-8")
    request = urllib.request.Request(
        API_BASES[environment] + "/identity/v1/oauth2/token",
        data=body,
        headers={"Authorization": "Basic " + basic, "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"eBay rejected the token exchange (HTTP {exc.code}). Check the App ID, Cert ID, RuName, and code; then rerun setup.") from None
    except urllib.error.URLError:
        raise ValueError("Could not reach eBay's token endpoint. Check your connection and rerun setup.") from None
    token = payload.get("refresh_token")
    if not isinstance(token, str) or not token:
        raise ValueError("eBay did not return a refresh token. Check the authorization scope and try again.")
    return token


def save_settings(path: Path, updates: dict[str, str]) -> None:
    """Update only named keys, preserving other environment entries and comments."""
    if path.exists():
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    else:
        template = Path(__file__).resolve().parents[1] / ".env.example"
        lines = template.read_text(encoding="utf-8-sig").splitlines() if template.exists() else []
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in updates:
            if key not in seen:
                result.append(f"{key}={updates[key]}")
                seen.add(key)
        else:
            result.append(line)
    result.extend(f"{key}={value}" for key, value in updates.items() if key not in seen)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as output:
            output.write("\n".join(result) + "\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def required_value(settings: dict[str, str], key: str, label: str, *, secret: bool = False) -> str:
    value = settings.get(key, "").strip()
    while not value:
        value = (getpass.getpass if secret else input)(f"{label}: ").strip()
    if "\n" in value or "\r" in value:
        raise ValueError(f"{label} must be a single line")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Authorize an eBay seller or Sandbox test buyer and save a renewable token.")
    parser.add_argument("--environment", choices=tuple(AUTH_BASES), help="Choose sandbox or production (default: EBAY_ENV in .env).")
    parser.add_argument("--include-refunds", action="store_true", help="Also request sell.finances for refund operations, if enabled for your keyset.")
    parser.add_argument('--account', choices=('seller', 'buyer'), default='seller', help='Authorize the seller (default) or a separate Sandbox buyer.')
    args = parser.parse_args()
    try:
        settings = load_settings()
        environment = args.environment or settings.get("EBAY_ENV", "sandbox").strip().lower()
        if environment not in AUTH_BASES:
            raise ValueError("EBAY_ENV must be sandbox or production")
        if args.account == 'buyer' and (environment != 'sandbox' or args.include_refunds):
            raise ValueError('Buyer authorization is available only in Sandbox and does not use refund scopes.')
        prefix = "EBAY_" + environment.upper() + "_"
        client_id = required_value(settings, prefix + "CLIENT_ID", "eBay App ID (Client ID)")
        client_secret = required_value(settings, prefix + "CLIENT_SECRET", "eBay Cert ID (Client Secret)", secret=True)
        runame = required_value(settings, prefix + "RUNAME", "eBay RuName (not the display title or Accepted URL)")
        path = settings_file_path()
        values = {
            prefix + "CLIENT_ID": client_id,
            prefix + "CLIENT_SECRET": client_secret,
            prefix + "RUNAME": runame,
        }
        if args.account == 'seller':
            values['EBAY_ENV'] = environment
        save_settings(path, values)
        state = secrets.token_urlsafe(24)
        url = authorization_url(environment, client_id, runame, state, include_refunds=args.include_refunds, account=args.account)
        print(f"\nOpening eBay {environment} {args.account} authorization in your browser...")
        if not webbrowser.open(url):
            print("Open this URL in a browser:\n" + url)
        print(f"Sign in as the {args.account} and approve access. Copy the entire final browser address, including code= and state=.")
        callback = getpass.getpass("Paste the final browser address here (hidden): ")
        code = authorization_code(callback, state)
        refresh_token = exchange_code(environment, client_id, client_secret, runame, code)
        token_prefix = 'EBAY_SANDBOX_BUYER_' if args.account == 'buyer' else prefix + 'USER_'
        updates = {token_prefix + 'REFRESH_TOKEN': refresh_token}
        if args.account == 'seller':
            updates[token_prefix + 'ACCESS_TOKEN'] = ''
        save_settings(path, updates)
        print(f"Success. Renewable {args.account} credentials saved to {path}. Keep that file private.")
        return 0
    except (ValueError, OSError, EOFError, KeyboardInterrupt) as exc:
        print(f"Setup stopped: {exc if not isinstance(exc, KeyboardInterrupt) else 'cancelled'}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
