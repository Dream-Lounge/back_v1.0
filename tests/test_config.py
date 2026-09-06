from src.core.config import Settings


def _settings(database_url: str) -> Settings:
    return Settings(
        DATABASE_URL=database_url,
        SECRET_KEY="test-secret-key-that-is-at-least-32-characters",
        _env_file=None,
    )


def test_database_password_reserved_characters_are_percent_encoded():
    settings = _settings(
        "postgresql://dreamlounge_backend.project:long-password!@"
        "@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
    )

    assert "long-password%21%40@aws-0-ap-southeast-1.pooler.supabase.com" in settings.DATABASE_URL


def test_database_password_already_encoded_is_not_double_encoded():
    settings = _settings(
        "postgresql+psycopg://dreamlounge_backend.project:long-password%21%40"
        "@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require"
    )

    assert "%2521" not in settings.DATABASE_URL
    assert "long-password%21%40@aws-0-ap-southeast-1.pooler.supabase.com" in settings.DATABASE_URL
