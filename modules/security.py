import os
import base64
import uuid
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

def get_machine_key():
    """
    Generates a stable key based on the machine's MAC address and a static salt.
    This ensures the database keys can only be decrypted on the same machine (user environment).
    """
    # 1. Get Machine Identity (MAC Address)
    node_id = uuid.getnode()
    machine_id = str(node_id).encode()
    
    # 2. Use a static salt (could be moved to env, but hardcoded allows zero-config)
    # The requirement is "based on user environment", so tying to hardware/node is good.
    salt = b'genesis_ai_secure_salt_v1'
    
    # 3. Derive a 32-byte key
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = kdf.derive(machine_id)
    return base64.urlsafe_b64encode(key)

_CIPHER = None

def get_cipher():
    global _CIPHER
    if _CIPHER is None:
        key = get_machine_key()
        _CIPHER = Fernet(key)
    return _CIPHER

def encrypt_value(text):
    if not text:
        return None
    cipher = get_cipher()
    return cipher.encrypt(text.encode()).decode()

def decrypt_value(token):
    if not token:
        return None
    try:
        cipher = get_cipher()
        return cipher.decrypt(token.encode()).decode()
    except Exception as e:
        print(f"[Security] Decryption failed: {e}")
        return None
