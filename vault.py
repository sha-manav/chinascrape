"""Passphrase encryption for data published to the public x-data branch.

AES-256-GCM with a key from PBKDF2-SHA256 (210,000 rounds), the same scheme the drafts page uses
in the browser (WebCrypto), so only someone with DRAFTS_PASSPHRASE can read the published feed.
"""
import base64, json, os
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROUNDS = 210_000


def _key(passphrase, salt):
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ROUNDS).derive(passphrase.encode())


def seal(obj, passphrase):
    salt, iv = os.urandom(16), os.urandom(12)
    ct = AESGCM(_key(passphrase, salt)).encrypt(iv, json.dumps(obj, ensure_ascii=False).encode(), None)
    b64 = lambda b: base64.b64encode(b).decode()
    return {"v": 1, "kdf": "PBKDF2-SHA256", "rounds": ROUNDS, "salt": b64(salt), "iv": b64(iv), "ct": b64(ct)}


def open_(box, passphrase):
    d = lambda k: base64.b64decode(box[k])
    return json.loads(AESGCM(_key(passphrase, d("salt"))).decrypt(d("iv"), d("ct"), None))
