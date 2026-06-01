from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import binascii

data = "615f01010e4c76a5-70af8049e10dca8de2106c09-f87502f6151f7f6407530ef40dcd11d86b545357f8357a160f34acb8b183907087525acfbb8c76a2"
parts = data.split("-")
salt = binascii.unhexlify(parts[0])
iv = binascii.unhexlify(parts[1])
ciphertext = binascii.unhexlify(parts[2])

password = b"player"

kdf = PBKDF2HMAC(
    algorithm=hashes.SHA256(),
    length=32,
    salt=salt,
    iterations=1000,
    backend=default_backend()
)
key = kdf.derive(password)

aesgcm = AESGCM(key)
try:
    plaintext = aesgcm.decrypt(iv, ciphertext, None)
    print("Decrypted:", plaintext.decode('utf-8'))
except Exception as e:
    print("Decryption failed:", e)
