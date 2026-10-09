from app.paypal import checkout_enabled, payment_mode


def test_production_checkout_only_accepts_configured_paypal_live(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("PAYPAL_MOCK_MODE", "false")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test-client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test-secret")

    monkeypatch.setenv("PAYPAL_BASE_URL", "https://api-m.paypal.com")
    assert payment_mode() == "live"
    assert checkout_enabled() is True

    monkeypatch.setenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")
    assert payment_mode() == "sandbox"
    assert checkout_enabled() is False

    monkeypatch.setenv("PAYPAL_BASE_URL", "https://payments.example.test")
    assert payment_mode() == "custom"
    assert checkout_enabled() is False


def test_paypal_mock_and_missing_credentials_are_never_checkout(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("PAYPAL_MOCK_MODE", "true")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "test-client")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("PAYPAL_BASE_URL", "https://api-m.paypal.com")
    assert payment_mode() == "mock"
    assert checkout_enabled() is False

    monkeypatch.setenv("PAYPAL_MOCK_MODE", "false")
    monkeypatch.delenv("PAYPAL_CLIENT_SECRET")
    assert payment_mode() == "unconfigured"
    assert checkout_enabled() is False
