from services.webhook_verify import sign_body, verify_signature


def test_sign_and_verify_roundtrip():
    secret = "tbwh_test_secret"
    body = b'{"event":"card_created","id":"abc"}'
    signature = sign_body(secret, body)
    assert signature.startswith("sha256=")
    assert verify_signature(secret, body, signature)
    assert not verify_signature(secret, body, "sha256=deadbeef")
    assert not verify_signature("other", body, signature)
