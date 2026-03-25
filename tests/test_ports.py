"""Tests for frontdoor/ports.py — reserved ports set and allocation helpers."""

from unittest.mock import MagicMock, patch

from frontdoor.ports import RESERVED_PORTS, is_reserved, next_available_port


class TestReservedPorts:
    def test_framework_ports_reserved(self):
        """Common web framework ports should be reserved."""
        assert 3000 in RESERVED_PORTS
        assert 5000 in RESERVED_PORTS
        assert 8080 in RESERVED_PORTS

    def test_amplifier_ports_reserved(self):
        """Amplifier ecosystem ports 8410-8420 should be reserved."""
        assert 8410 in RESERVED_PORTS
        assert 8420 in RESERVED_PORTS

    def test_database_ports_reserved(self):
        """Well-known database ports should be reserved."""
        assert 5432 in RESERVED_PORTS  # PostgreSQL
        assert 6379 in RESERVED_PORTS  # Redis
        assert 3306 in RESERVED_PORTS  # MySQL
        assert 27017 in RESERVED_PORTS  # MongoDB

    def test_cluster_buffer(self):
        """All ports in 3000-3010 range (including +10 buffer) should be reserved."""
        for port in range(3000, 3011):
            assert port in RESERVED_PORTS, f"Port {port} should be reserved"

    def test_is_not_reserved(self):
        """Ports outside reserved ranges should not be reserved."""
        assert not is_reserved(8440)
        assert not is_reserved(9999)


class TestNextAvailablePort:
    def test_returns_first_non_reserved(self):
        """When port is not reserved and not in use, return it immediately."""
        # 8440 is not reserved; connection raises OSError → port is free
        with patch("socket.create_connection", side_effect=OSError):
            result = next_available_port(start=8440)
        assert result == 8440

    def test_skips_reserved_ports(self):
        """When start falls inside a reserved range, skip past the whole range."""
        # 8080-8090 are reserved; 8091 is not reserved and socket raises OSError → free
        with patch("socket.create_connection", side_effect=OSError):
            result = next_available_port(start=8080)
        assert result == 8091

    def test_skips_ports_in_use(self):
        """When a non-reserved port has an active listener, skip to the next one."""
        # First call (8440) succeeds → port in use; second call (8441) raises OSError → free
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        side_effects = [mock_conn, OSError()]

        with patch("socket.create_connection", side_effect=side_effects):
            result = next_available_port(start=8440)
        assert result == 8441

    def test_raises_on_invalid_start_below_zero(self):
        """next_available_port(-1) must raise ValueError — negative ports are invalid."""
        import pytest

        with pytest.raises(ValueError, match="valid port"):
            next_available_port(start=-1)

    def test_raises_on_start_above_max_port(self):
        """next_available_port(65536) must raise ValueError — 65536 exceeds valid range."""
        import pytest

        with pytest.raises(ValueError, match="valid port"):
            next_available_port(start=65536)

    def test_raises_when_range_exhausted(self):
        """When every candidate port up to 65535 is in use, raise RuntimeError."""
        import pytest

        # 65535 is not reserved; simulate it being in use → no higher port exists
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("socket.create_connection", return_value=mock_conn):
            with pytest.raises(RuntimeError, match="65535"):
                next_available_port(start=65535)
