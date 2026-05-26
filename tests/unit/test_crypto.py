"""Unit tests for the Fernet-based encrypt/decrypt utilities."""
import pytest
from cryptography.fernet import Fernet

from app.utils.crypto import encrypt, decrypt


class TestEncryptDecryptRoundtrip:
    def test_roundtrip_with_key(self, monkeypatch):
        key = Fernet.generate_key().decode()
        monkeypatch.setenv("ENCRYPTION_KEY", key)

        plaintext = "super_secret_password_123"
        assert decrypt(encrypt(plaintext)) == plaintext

    def test_empty_string_roundtrip(self, monkeypatch):
        key = Fernet.generate_key().decode()
        monkeypatch.setenv("ENCRYPTION_KEY", key)

        assert decrypt(encrypt("")) == ""

    def test_noop_without_key(self, monkeypatch):
        monkeypatch.delenv("ENCRYPTION_KEY", raising=False)

        value = "plaintext_stored_as_is"
        assert encrypt(value) == value
        assert decrypt(value) == value

    def test_different_keys_cannot_decrypt(self, monkeypatch):
        key1 = Fernet.generate_key().decode()
        key2 = Fernet.generate_key().decode()

        monkeypatch.setenv("ENCRYPTION_KEY", key1)
        ciphertext = encrypt("secret")

        monkeypatch.setenv("ENCRYPTION_KEY", key2)
        with pytest.raises(Exception):
            decrypt(ciphertext)
