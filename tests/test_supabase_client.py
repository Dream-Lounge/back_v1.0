from src.core.config import settings
from src.utils import supabase_client


def test_sync_supabase_clients_have_auth_storage(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(settings, "SUPABASE_SERVICE_KEY", "test-service-key")
    monkeypatch.setattr(settings, "SUPABASE_ANON_KEY", "test-anon-key")
    monkeypatch.setattr(supabase_client, "_admin_client", None)

    admin_client = supabase_client.get_supabase_admin_client()
    auth_client = supabase_client.create_supabase_auth_client()

    assert hasattr(admin_client.options, "storage")
    assert hasattr(auth_client.options, "storage")
