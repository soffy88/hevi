from obase.auth import argon2_hash, argon2_verify


def hash_password(password: str) -> str:
    """Hash a password using argon2."""
    return argon2_hash(password=password)


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a hash."""
    return argon2_verify(password=password, hash=hashed)
