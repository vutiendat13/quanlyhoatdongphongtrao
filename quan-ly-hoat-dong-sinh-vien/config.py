from pathlib import Path
import os
import secrets

BASE_DIR = Path(__file__).resolve().parent


class Config:
    DATABASE = BASE_DIR / "instance" / "app.db"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

    @staticmethod
    def secret_key():
        configured = os.environ.get("FLASK_SECRET_KEY")
        if configured:
            return configured
        key_file = BASE_DIR / "instance" / ".secret_key"
        key_file.parent.mkdir(parents=True, exist_ok=True)
        if key_file.exists():
            return key_file.read_text(encoding="utf-8").strip()
        generated = secrets.token_hex(32)
        key_file.write_text(generated, encoding="utf-8")
        return generated


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret-not-for-production"

