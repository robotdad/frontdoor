"""Tests for frontdoor/tokens.py — token lifecycle."""

import json
from pathlib import Path

import pytest


class TestCreateToken:
    def test_returns_id_and_raw_token(self, tmp_path):
        """create_token returns (token_id, raw_token) tuple."""
        from frontdoor.tokens import create_token
        tokens_file = tmp_path / "tokens.json"
        token_id, raw_token = create_token("test-device", tokens_file=tokens_file)
        assert token_id.startswith("tok_")
        assert raw_token.startswith("ft_")

    def test_stores_hash_not_raw(self, tmp_path):
        """Token file stores sha256 hash, never the raw token."""
        from frontdoor.tokens import create_token
        tokens_file = tmp_path / "tokens.json"
        token_id, raw_token = create_token("test-device", tokens_file=tokens_file)
        data = json.loads(tokens_file.read_text())
        assert token_id in data
        assert "token_hash" in data[token_id]
        assert raw_token not in tokens_file.read_text()

    def test_multiple_tokens_coexist(self, tmp_path):
        """Creating multiple tokens adds entries without overwriting."""
        from frontdoor.tokens import create_token
        tokens_file = tmp_path / "tokens.json"
        id1, _ = create_token("device-1", tokens_file=tokens_file)
        id2, _ = create_token("device-2", tokens_file=tokens_file)
        data = json.loads(tokens_file.read_text())
        assert id1 in data
        assert id2 in data
        assert data[id1]["name"] == "device-1"
        assert data[id2]["name"] == "device-2"

    def test_creates_file_if_missing(self, tmp_path):
        """create_token creates the tokens file if it doesn't exist."""
        from frontdoor.tokens import create_token
        tokens_file = tmp_path / "subdir" / "tokens.json"
        create_token("test", tokens_file=tokens_file)
        assert tokens_file.exists()


class TestValidateToken:
    def test_valid_token_returns_name(self, tmp_path):
        """validate_token returns the token name for a valid raw token."""
        from frontdoor.tokens import create_token, validate_token
        tokens_file = tmp_path / "tokens.json"
        _, raw_token = create_token("my-laptop", tokens_file=tokens_file)
        result = validate_token(raw_token, tokens_file=tokens_file)
        assert result == "my-laptop"

    def test_invalid_token_returns_none(self, tmp_path):
        """validate_token returns None for an invalid token."""
        from frontdoor.tokens import create_token, validate_token
        tokens_file = tmp_path / "tokens.json"
        create_token("my-laptop", tokens_file=tokens_file)
        result = validate_token("ft_invalid_garbage", tokens_file=tokens_file)
        assert result is None

    def test_non_ft_prefix_returns_none(self, tmp_path):
        """validate_token returns None for tokens without ft_ prefix."""
        from frontdoor.tokens import validate_token
        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text("{}")
        result = validate_token("not_a_valid_token", tokens_file=tokens_file)
        assert result is None

    def test_missing_file_returns_none(self, tmp_path):
        """validate_token returns None when tokens file doesn't exist."""
        from frontdoor.tokens import validate_token
        tokens_file = tmp_path / "nonexistent.json"
        result = validate_token("ft_anything", tokens_file=tokens_file)
        assert result is None


class TestListTokens:
    def test_lists_tokens_without_hashes(self, tmp_path):
        """list_tokens returns id, name, created_at but never token_hash."""
        from frontdoor.tokens import create_token, list_tokens
        tokens_file = tmp_path / "tokens.json"
        create_token("device-a", tokens_file=tokens_file)
        create_token("device-b", tokens_file=tokens_file)
        result = list_tokens(tokens_file=tokens_file)
        assert len(result) == 2
        for entry in result:
            assert "id" in entry
            assert "name" in entry
            assert "created_at" in entry
            assert "token_hash" not in entry

    def test_empty_file_returns_empty_list(self, tmp_path):
        """list_tokens returns [] when no tokens exist."""
        from frontdoor.tokens import list_tokens
        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text("{}")
        result = list_tokens(tokens_file=tokens_file)
        assert result == []


class TestRevokeToken:
    def test_revoke_existing_returns_true(self, tmp_path):
        """revoke_token returns True and removes the token entry."""
        from frontdoor.tokens import create_token, revoke_token, validate_token
        tokens_file = tmp_path / "tokens.json"
        token_id, raw_token = create_token("ephemeral", tokens_file=tokens_file)
        assert revoke_token(token_id, tokens_file=tokens_file) is True
        assert validate_token(raw_token, tokens_file=tokens_file) is None

    def test_revoke_nonexistent_returns_false(self, tmp_path):
        """revoke_token returns False when the token_id doesn't exist."""
        from frontdoor.tokens import revoke_token
        tokens_file = tmp_path / "tokens.json"
        tokens_file.write_text("{}")
        assert revoke_token("tok_doesnotexist", tokens_file=tokens_file) is False
