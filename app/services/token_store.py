import base64
import json
import os
from typing import Optional, Dict, Any
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from app.db import get_supabase
from app.config import get_settings


def _get_fernet() -> Fernet:
    """Return a Fernet instance. Generates & caches a key if not configured."""
    settings = get_settings()
    raw_key = settings.token_encryption_key
    if raw_key:
        # Accept raw base64url-encoded 32-byte key or standard Fernet key
        key_bytes = raw_key.encode() if isinstance(raw_key, str) else raw_key
        # Fernet keys must be 32 url-safe base64-encoded bytes (44 chars)
        if len(key_bytes) != 44:
            # Try to derive a valid Fernet key from the raw value
            import hashlib
            digest = hashlib.sha256(key_bytes).digest()
            key_bytes = base64.urlsafe_b64encode(digest)
        return Fernet(key_bytes)
    else:
        # Derive from SECRET_KEY for convenience (not ideal for production)
        import hashlib
        digest = hashlib.sha256(settings.secret_key.encode()).digest()
        fernet_key = base64.urlsafe_b64encode(digest)
        return Fernet(fernet_key)


def encrypt_tokens(token_data: Dict[str, Any]) -> str:
    """Encrypt a token dict and return a base64 string."""
    f = _get_fernet()
    plaintext = json.dumps(token_data).encode("utf-8")
    return f.encrypt(plaintext).decode("utf-8")


def decrypt_tokens(encrypted: str) -> Optional[Dict[str, Any]]:
    """Decrypt an encrypted token string. Returns None on failure."""
    try:
        f = _get_fernet()
        plaintext = f.decrypt(encrypted.encode("utf-8"))
        return json.loads(plaintext.decode("utf-8"))
    except (InvalidToken, Exception):
        return None


async def store_tokens(user_id: str, platform: str, token_data: Dict[str, Any]) -> None:
    """Encrypt and upsert OAuth tokens for a user/platform pair."""
    supabase = get_supabase()
    encrypted = encrypt_tokens(token_data)
    now = datetime.now(timezone.utc).isoformat()

    # Extract username/handle if present for display purposes
    username = (
        token_data.get("username")
        or token_data.get("screen_name")
        or token_data.get("name")
        or None
    )

    record = {
        "user_id": user_id,
        "platform": platform,
        "encrypted_tokens": encrypted,
        "username": username,
        "updated_at": now,
    }

    # Check if row exists
    existing = (
        supabase.table("platform_tokens")
        .select("id")
        .eq("user_id", user_id)
        .eq("platform", platform)
        .execute()
    )

    if existing.data:
        supabase.table("platform_tokens").update(record).eq("user_id", user_id).eq(
            "platform", platform
        ).execute()
    else:
        record["created_at"] = now
        supabase.table("platform_tokens").insert(record).execute()


async def retrieve_tokens(user_id: str, platform: str) -> Optional[Dict[str, Any]]:
    """Retrieve and decrypt OAuth tokens for a user/platform pair."""
    supabase = get_supabase()
    result = (
        supabase.table("platform_tokens")
        .select("encrypted_tokens")
        .eq("user_id", user_id)
        .eq("platform", platform)
        .single()
        .execute()
    )
    if not result.data:
        return None
    return decrypt_tokens(result.data["encrypted_tokens"])


async def delete_tokens(user_id: str, platform: str) -> bool:
    """Delete stored tokens for a user/platform pair. Returns True if deleted."""
    supabase = get_supabase()
    result = (
        supabase.table("platform_tokens")
        .delete()
        .eq("user_id", user_id)
        .eq("platform", platform)
        .execute()
    )
    return bool(result.data)


async def list_connected_platforms(user_id: str):
    """Return all platform connection records for a user (without decrypting tokens)."""
    supabase = get_supabase()
    result = (
        supabase.table("platform_tokens")
        .select("platform, username, created_at, updated_at")
        .eq("user_id", user_id)
        .execute()
    )
    return result.data or []
