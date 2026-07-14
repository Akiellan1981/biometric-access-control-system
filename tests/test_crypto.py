import pytest

from acs.storage.crypto import TemplateCipher


def test_passthrough_when_disabled(tmp_path):
    c = TemplateCipher(tmp_path / "k.key", enabled=False)
    data = b"hello-embedding"
    assert c.encrypt(data) == data
    assert c.decrypt(data) == data


def test_roundtrip_when_available(tmp_path):
    pytest.importorskip("cryptography")
    c = TemplateCipher(tmp_path / "k.key", enabled=True)
    if not c.enabled:
        pytest.skip("cryptography not available")
    data = b"\x01\x02\x03secret-template"
    blob = c.encrypt(data)
    assert blob != data
    assert c.decrypt(blob) == data
    assert (tmp_path / "k.key").exists()
