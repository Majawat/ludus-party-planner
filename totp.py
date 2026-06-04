import base64
import io
import json
import secrets

import pyotp
import qrcode
from flask import current_app
from werkzeug.security import check_password_hash, generate_password_hash

from models import SiteSettings


def generate_totp_secret():
    return pyotp.random_base32()


def get_totp_uri(secret, user_email):
    site_name = SiteSettings.get("site_name", "Ludus Party Planner")
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=user_email,
        issuer_name=site_name,
    )


def verify_totp_code(secret, code):
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def generate_backup_codes():
    """Return (raw_codes, hashed_codes). Raw codes are shown once to the user."""
    raw = [secrets.token_hex(4).upper() for _ in range(8)]
    hashed = [generate_password_hash(c) for c in raw]
    return raw, hashed


def verify_backup_code(user, code):
    """Check code against stored hashes. Removes the used code. Returns True if valid."""
    if not user.totp_backup_codes:
        return False
    try:
        codes = json.loads(user.totp_backup_codes)
        if not isinstance(codes, list):
            raise ValueError("backup codes not a list")
    except Exception as e:
        current_app.logger.warning(f"Failed to parse totp_backup_codes for user {user.id}: {e}")
        return False
    for i, hashed in enumerate(codes):
        if check_password_hash(hashed, code.upper().strip()):
            codes.pop(i)
            user.totp_backup_codes = json.dumps(codes)
            return True
    return False


def qr_code_data_uri(uri):
    """Return QR code as a base64 PNG data URI. No file written to disk."""
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"
