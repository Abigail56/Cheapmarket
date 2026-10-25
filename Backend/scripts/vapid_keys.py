"""Prints a new VAPID key pair for web push. Put both lines in .env.

    python -m scripts.vapid_keys

Generate them ONCE per environment and keep them: changing the keys silently
breaks every rider's existing push subscription (they'd have to turn alerts on again)."""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def new_keys() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(serialization.Encoding.X962,
                                           serialization.PublicFormat.UncompressedPoint)
    return b64url(public), b64url(private)


if __name__ == "__main__":
    public, private = new_keys()
    print(f"VAPID_PUBLIC_KEY={public}")
    print(f"VAPID_PRIVATE_KEY={private}")
