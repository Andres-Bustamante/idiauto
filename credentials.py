"""Almacenamiento seguro de credenciales usando el keyring del SO.

En Linux usa Secret Service (GNOME Keyring / KWallet).
En macOS usa Keychain. En Windows usa Credential Vault.
Los secretos NO quedan en disco en texto plano.
"""
from __future__ import annotations

import json
from typing import Optional

import keyring

SERVICE = "idiAuto"
KEY = "default"


def load() -> Optional[dict]:
    """Devuelve {'usuario': ..., 'password': ...} o None si no hay."""
    try:
        raw = keyring.get_password(SERVICE, KEY)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def save(usuario: str, password: str) -> None:
    keyring.set_password(
        SERVICE, KEY, json.dumps({"usuario": usuario, "password": password}),
    )


def clear() -> None:
    try:
        keyring.delete_password(SERVICE, KEY)
    except Exception:
        pass
