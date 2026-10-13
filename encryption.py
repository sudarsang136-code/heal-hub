import os
import base64
from cryptography.fernet import Fernet

KEY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
# Key lookup order:
#   1. HEALHUB_ENCRYPTION_KEY env var (recommended)
#   2. File at HEALHUB_KEY_FILE (default: data/secret.key, git-ignored; auto-created for local dev only)
KEY_FILE = os.environ.get("HEALHUB_KEY_FILE", os.path.join(KEY_DIR, "secret.key"))

def _get_or_create_key() -> bytes:
    env_key = os.environ.get("HEALHUB_ENCRYPTION_KEY")
    if env_key:
        return env_key.strip().encode()
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read().strip()
    print("[WARN] HEALHUB_ENCRYPTION_KEY not set - generating a local dev key file (never commit it).")
    os.makedirs(os.path.dirname(KEY_FILE), exist_ok=True)
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(key)
    try:
        os.chmod(KEY_FILE, 0o600)
    except OSError:
        pass
    return key

_fernet = Fernet(_get_or_create_key())

def encrypt_text(plain_text: str) -> str:
    """Encrypts plaintext string into a secure base64 token."""
    if not plain_text:
        return ""
    try:
        return _fernet.encrypt(plain_text.encode("utf-8")).decode("utf-8")
    except Exception as e:
        print(f"Encryption error: {e}")
        return plain_text

def decrypt_text(cipher_text: str) -> str:
    """Decrypts ciphertext token back to plaintext."""
    if not cipher_text:
        return ""
    try:
        return _fernet.decrypt(cipher_text.encode("utf-8")).decode("utf-8")
    except Exception as e:
        # Fallback if unencrypted
        return cipher_text

def mask_phone(phone: str) -> str:
    """Masks phone number for privacy, e.g. +91 98*** **421."""
    if not phone or len(phone) < 6:
        return "******"
    clean = phone.strip()
    if len(clean) <= 6:
        return clean[:2] + "****" + clean[-2:]
    return clean[:3] + " " + "*" * (len(clean) - 6) + " " + clean[-3:]

def mask_email(email: str) -> str:
    """Masks email address, e.g. d***r@example.com."""
    if not email or "@" not in email:
        return "****@***.com"
    parts = email.split("@")
    name = parts[0]
    domain = parts[1]
    masked_name = name[0] + "***" + (name[-1] if len(name) > 1 else "")
    return f"{masked_name}@{domain}"
