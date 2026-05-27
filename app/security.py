import hashlib

try:
    import bcrypt
except ImportError:  # pragma: no cover - bcrypt is optional for legacy hashes.
    bcrypt = None


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if hashed_password == hash_password(plain_password):
        return True
    if bcrypt is None:
        return False

    password_bytes = plain_password.encode("utf-8")
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]
    try:
        return bcrypt.checkpw(password_bytes, hashed_password.encode("utf-8"))
    except ValueError:
        return False
