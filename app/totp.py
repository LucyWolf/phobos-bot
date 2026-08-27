from __future__ import annotations

import base64
import io
import secrets

import pyotp
import qrcode


def generate_secret() -> str:
    return pyotp.random_base32()


def provisioning_uri(secret: str, account_name: str, issuer: str = "Phobos Bot") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account_name, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    try:
        return pyotp.TOTP(secret).verify(code.strip(), valid_window=1)
    except Exception:
        return False


def qr_data_uri(uri: str) -> str:
    img = qrcode.make(uri, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def generate_backup_codes(n: int = 8) -> list[str]:
    return ["-".join([secrets.token_hex(2), secrets.token_hex(2)]) for _ in range(n)]
