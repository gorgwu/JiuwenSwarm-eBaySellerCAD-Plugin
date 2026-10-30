"""Load seller credentials and provide short-lived eBay user access tokens."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_API_BASES = {
    "sandbox": "https://api.sandbox.ebay.com",
    "production": "https://api.ebay.com",
}
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_TOKEN_LOCK = threading.Lock()


@dataclass(frozen=True)
class EbayAuth:
    environment: str
    api_base: str
    access_token: str


def settings_file_path() -> Path:
    """Return the credentials file used by the plugin."""
    configured_path = os.environ.get("EBAY_SELLER_ENV_FILE", "").strip()
    return Path(configured_path).expanduser() if configured_path else _PACKAGE_ROOT / ".env"


def load_settings() -> dict[str, str]:
    """Read the plugin's private .env without changing process environment."""
    configured_path = os.environ.get("EBAY_SELLER_ENV_FILE", "").strip()
    env_path = settings_file_path()
    values: dict[str, str] = {}
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, value = line.split("=", 1)
            name = name.strip()
            if not name.startswith("EBAY_"):
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[name] = value
    elif configured_path:
        raise ValueError("EBAY_SELLER_ENV_FILE does not point to a readable file")
    values.update({key: value for key, value in os.environ.items() if key.startswith("EBAY_")})
    return values


def user_access_token(api_base: str, environment: str, settings: dict[str, str]) -> str:
    """Reuse a user token, renewing it from the refresh token near expiry."""
    prefix = "EBAY_" + environment.upper() + "_"
    client_id = settings.get(prefix + "CLIENT_ID", "").strip()
    client_secret = settings.get(prefix + "CLIENT_SECRET", "").strip()
    refresh_token = settings.get(prefix + "USER_REFRESH_TOKEN", "").strip()
    if client_id and client_secret and refresh_token:
        cache_key = hashlib.sha256(
            "\0".join((api_base, client_id, client_secret, refresh_token)).encode("utf-8")
        ).hexdigest()
        with _TOKEN_LOCK:
            cached = _TOKEN_CACHE.get(cache_key)
            if cached and time.monotonic() < cached[1]:
                return cached[0]
            basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
            body = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": refresh_token}).encode()
            request = urllib.request.Request(
                api_base + "/identity/v1/oauth2/token",
                data=body,
                headers={"Authorization": "Basic " + basic, "Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = json.load(response)
            access_token = payload.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                raise ValueError("eBay OAuth response did not contain a user access token")
            try:
                lifetime = max(0, int(payload.get("expires_in", 0)) - 120)
            except (TypeError, ValueError):
                lifetime = 0
            if lifetime:
                _TOKEN_CACHE[cache_key] = (access_token, time.monotonic() + lifetime)
            else:
                _TOKEN_CACHE.pop(cache_key, None)
            return access_token
    access_token = settings.get(prefix + "USER_ACCESS_TOKEN", "").strip()
    if access_token:
        return access_token
    raise ValueError(
        f"Set {prefix}CLIENT_ID, {prefix}CLIENT_SECRET, and {prefix}USER_REFRESH_TOKEN "
        f"in the plugin .env or process environment, or set {prefix}USER_ACCESS_TOKEN for a short test"
    )


def get_seller_auth() -> EbayAuth:
    """Return the selected API host and a usable seller user access token."""
    settings = load_settings()
    environment = settings.get("EBAY_ENV", "sandbox").strip().lower()
    if environment not in _API_BASES:
        raise ValueError("EBAY_ENV must be sandbox or production")
    api_base = _API_BASES[environment]
    return EbayAuth(environment, api_base, user_access_token(api_base, environment, settings))


def get_sandbox_buyer_auth() -> EbayAuth:
    """Obtain a separate buyer token for Sandbox tests, without using seller tokens."""
    settings = load_settings()
    if settings.get('EBAY_ENV', 'sandbox').strip().lower() != 'sandbox':
        raise ValueError('Sandbox buyer tests require EBAY_ENV=sandbox.')
    buyer_refresh = settings.get('EBAY_SANDBOX_BUYER_REFRESH_TOKEN', '').strip()
    if not buyer_refresh:
        raise ValueError('Set EBAY_SANDBOX_BUYER_REFRESH_TOKEN using setup_oauth.py --environment sandbox --account buyer.')
    buyer_settings = dict(settings)
    buyer_settings['EBAY_SANDBOX_USER_REFRESH_TOKEN'] = buyer_refresh
    buyer_settings.pop('EBAY_SANDBOX_USER_ACCESS_TOKEN', None)
    base = _API_BASES['sandbox']
    return EbayAuth('sandbox', base, user_access_token(base, 'sandbox', buyer_settings))


def get_application_auth() -> EbayAuth:
    """Get an application token for public metadata such as category taxonomy."""
    settings = load_settings()
    environment = settings.get("EBAY_ENV", "sandbox").strip().lower()
    if environment not in _API_BASES:
        raise ValueError("EBAY_ENV must be sandbox or production")
    prefix = "EBAY_" + environment.upper() + "_"
    client_id = settings.get(prefix + "CLIENT_ID", "").strip()
    secret = settings.get(prefix + "CLIENT_SECRET", "").strip()
    if not client_id or not secret:
        raise ValueError(f"Set {prefix}CLIENT_ID and {prefix}CLIENT_SECRET")
    api_base = _API_BASES[environment]
    key = hashlib.sha256(("application\0" + api_base + "\0" + client_id + "\0" + secret).encode()).hexdigest()
    with _TOKEN_LOCK:
        cached = _TOKEN_CACHE.get(key)
        if cached and time.monotonic() < cached[1]:
            return EbayAuth(environment, api_base, cached[0])
        basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode("ascii")
        body = urllib.parse.urlencode({"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"}).encode()
        request = urllib.request.Request(api_base + "/identity/v1/oauth2/token", data=body,
            headers={"Authorization": "Basic " + basic, "Content-Type": "application/x-www-form-urlencoded"}, method="POST")
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
        token = payload.get("access_token")
        if not isinstance(token, str) or not token:
            raise ValueError("eBay OAuth response did not contain an application access token")
        try:
            lifetime = max(0, int(payload.get("expires_in", 0)) - 120)
        except (TypeError, ValueError):
            lifetime = 0
        if lifetime:
            _TOKEN_CACHE[key] = (token, time.monotonic() + lifetime)
        return EbayAuth(environment, api_base, token)
