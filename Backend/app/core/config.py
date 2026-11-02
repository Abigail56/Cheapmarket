from functools import lru_cache
from typing import Literal
from urllib.parse import quote_plus

from pydantic import computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # App
    PROJECT_NAME: str = "Cheapmarketdeal API"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # Security (SECRET_KEY has no default on purpose: the app must not start without it)
    SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    # PostgreSQL
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None

    # Caching / carts
    CACHE_TTL_SECONDS: int = 300
    GUEST_CART_TTL_SECONDS: int = 60 * 60 * 24 * 7

    # Business rules
    ORDER_NUMBER_PREFIX: str = "CMD"
    CURRENCY: str = "NGN"
    DEFAULT_PHONE_COUNTRY_CODE: str = "+234"
    LOW_STOCK_THRESHOLD: int = 10
    MAX_CART_ITEM_QTY: int = 100

    # Rate limiting (per IP, via Redis)
    RATE_LIMIT_ENABLED: bool = True
    # Per-account login lockout (always on): this many failed passwords for one
    # email/phone within the window blocks further attempts until it expires
    LOGIN_MAX_FAILURES: int = 5
    LOGIN_LOCKOUT_SECONDS: int = 15 * 60

    # One-time codes (password reset, phone verification)
    OTP_TTL_SECONDS: int = 15 * 60
    OTP_MAX_ATTEMPTS: int = 5

    # Logging / error tracking
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool | None = None  # None = JSON everywhere except ENVIRONMENT=local
    SENTRY_DSN: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0

    # Notifications. "console" just logs the message (no keys needed)
    SMS_BACKEND: Literal["console", "termii"] = "console"
    TERMII_API_KEY: str | None = None
    TERMII_SENDER_ID: str = "CheapMkt"
    TERMII_BASE_URL: str = "https://api.ng.termii.com"
    EMAIL_BACKEND: Literal["console", "smtp"] = "console"
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_STARTTLS: bool = True
    EMAIL_FROM: str = "Cheapmarket <no-reply@cheapmarketdeals.com>"
    NOTIFICATION_MAX_ATTEMPTS: int = 3

    # Image uploads. "local" saves under MEDIA_DIR and serves it at /media
    STORAGE_BACKEND: Literal["local", "cloudinary"] = "local"
    MEDIA_DIR: str = "media"
    MEDIA_BASE_URL: str = "http://localhost:8000/media"
    MAX_UPLOAD_BYTES: int = 5 * 1024 * 1024
    CLOUDINARY_CLOUD_NAME: str | None = None
    CLOUDINARY_API_KEY: str | None = None
    CLOUDINARY_API_SECRET: str | None = None

    # Background worker: re-checks card payments the webhook never confirmed
    RECONCILE_INTERVAL_SECONDS: int = 300
    RECONCILE_MIN_AGE_SECONDS: int = 5 * 60  # give the webhook a chance first
    RECONCILE_MAX_AGE_HOURS: int = 48  # after this a still-pending payment is marked failed

    # Deliveries
    PUBLIC_BASE_URL: str = "http://localhost:8000"  # where /track/<token> and /rider are served
    RIDER_ACCEPT_SECONDS: int = 5 * 60  # unanswered assignments go back to the admin
    GEOFENCE_METERS: int = 300  # rider must be this close to the pin to arrive / send the code
    DELIVERY_CODE_TTL_SECONDS: int = 10 * 60
    DELIVERY_CODE_MAX_ATTEMPTS: int = 5
    DELIVERY_CODE_RESEND_SECONDS: int = 60
    RIDER_SPEED_KMH: float = 20.0  # for the "about N minutes" ETA
    TRACKING_FRESH_SECONDS: int = 15 * 60  # customers only see a recent rider position

    # "Continue with Google": the OAuth client ID from Google Cloud Console (APIs & Services >
    # Credentials > OAuth client ID > Web application). Empty = the Google buttons are hidden.
    GOOGLE_CLIENT_ID: str | None = None

    # Checking rider IDs against government records. "none" = only the free checks
    # (number format, ID used twice). "dojah" = NIN + face match via Dojah (dojah.io):
    # sandbox.dojah.io for testing, api.dojah.io live (different keys).
    ID_VERIFY_PROVIDER: Literal["none", "dojah"] = "none"
    DOJAH_APP_ID: str | None = None
    DOJAH_SECRET_KEY: str | None = None
    DOJAH_BASE_URL: str = "https://sandbox.dojah.io"
    ID_FACE_MATCH_THRESHOLD: int = 90  # Dojah's own default; below this the faces don't match
    ID_NAME_MATCH_THRESHOLD: int = 80  # % similarity between typed and registered name

    # Web push for the rider app (alerts when the app is closed). Generate the pair with
    # `python -m scripts.vapid_keys`. Empty = push off (riders still get SMS).
    VAPID_PUBLIC_KEY: str | None = None
    VAPID_PRIVATE_KEY: str | None = None
    VAPID_SUBJECT: str = "mailto:admin@cheapmarketdeals.com"
    # The server only ever sends pushes to these browser push services (stops a
    # "subscription" pointing at an internal address from making us call it)
    PUSH_ALLOWED_HOSTS: list[str] = [
        "fcm.googleapis.com", "updates.push.services.mozilla.com", "web.push.apple.com",
        ".notify.windows.com", ".push.apple.com",
    ]

    # First admin (used by scripts/seed.py). CHANGE THE PASSWORD in any real environment.
    ADMIN_EMAIL: str = "admin@cheapmarketdeals.com"
    # Comma-separated: who gets an SMS/email for every new order
    ADMIN_ALERT_PHONES: str = ""
    ADMIN_ALERT_EMAILS: str = ""
    ADMIN_PASSWORD: str = "ChangeMe123!"
    ADMIN_NAME: str = "Store Admin"

    # Bank transfer details shown to customers who choose "transfer"
    BANK_NAME: str | None = None
    BANK_ACCOUNT_NUMBER: str | None = None
    BANK_ACCOUNT_NAME: str | None = None

    # Frontend (payment redirect target)
    FRONTEND_URL: str = "http://localhost:3000"

    # Payments
    PAYSTACK_SECRET_KEY: str | None = None
    PAYSTACK_BASE_URL: str = "https://api.paystack.co"
    FLUTTERWAVE_SECRET_KEY: str | None = None
    FLUTTERWAVE_SECRET_HASH: str | None = None  # the "secret hash" set in your FLW dashboard
    FLUTTERWAVE_BASE_URL: str = "https://api.flutterwave.com/v3"

    @model_validator(mode="after")
    def _refuse_unsafe_production(self) -> "Settings":
        # A live shop must not start with development settings: fail loudly instead
        if self.ENVIRONMENT != "production":
            return self
        problems = []
        if len(self.SECRET_KEY) < 32 or self.SECRET_KEY == "change-me":
            problems.append("SECRET_KEY must be a random string of 32+ characters")
        if self.DEBUG:
            problems.append("DEBUG must be false")
        if not self.PUBLIC_BASE_URL.startswith("https://"):
            problems.append("PUBLIC_BASE_URL must be https:// (riders need HTTPS for GPS/camera)")
        if not self.REDIS_PASSWORD:
            problems.append("REDIS_PASSWORD must be set")
        if problems:
            raise ValueError("Unsafe production settings: " + "; ".join(problems))
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL(self) -> str:
        pw = quote_plus(self.POSTGRES_PASSWORD)
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{pw}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def REDIS_URL(self) -> str:
        auth = f":{quote_plus(self.REDIS_PASSWORD)}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
