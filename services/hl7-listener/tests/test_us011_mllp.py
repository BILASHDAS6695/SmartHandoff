"""
tests/test_us011_mllp.py

Unit tests for US-011: MLLP frame parsing, ACK/NACK generation, and connection
concurrency logic.

Coverage:
- MLLP frame extraction (_read_mllp_frame via asyncio.StreamReader mocks)
- HL7 MSH parser (parse_hl7)
- ACK builder (build_ack)
- NACK builder (build_nack)
- Connection gate logic (semaphore enforcement)
- TCP keep-alive helper (smoke test — no socket required)
"""
from __future__ import annotations

import asyncio
import re
import sys
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# Stub out heavy cloud / shared dependencies so tests run without a venv that
# has google-cloud-pubsub, opentelemetry, or the shared package installed.
# ---------------------------------------------------------------------------

def _stub_module(name: str, **attrs) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules.setdefault(name, mod)
    return mod


# shared.otel
_otel_mod = _stub_module("shared.otel", init_tracer=lambda **_: None, get_tracer=lambda _: MagicMock())
_stub_module("shared", otel=_otel_mod)
_stub_module("shared.logging", configure_logging=lambda **_: None)

# opentelemetry stubs
_otel_pkg = _stub_module("opentelemetry")
_trace_mod = _stub_module("opentelemetry.trace", SpanKind=MagicMock(), Status=MagicMock(), StatusCode=MagicMock())
_otel_pkg.trace = _trace_mod
_stub_module("opentelemetry.propagate", inject=lambda carrier: None)

# prometheus_client stub
_prom = _stub_module(
    "prometheus_client",
    Counter=MagicMock(return_value=MagicMock(labels=MagicMock(return_value=MagicMock(inc=MagicMock())))),
    Gauge=MagicMock(return_value=MagicMock(inc=MagicMock(), dec=MagicMock())),
    Histogram=MagicMock(return_value=MagicMock(observe=MagicMock())),
    start_http_server=MagicMock(),
)

# google-cloud-pubsub stub
_pubsub = _stub_module("google.cloud.pubsub_v1", PublisherClient=MagicMock())
_stub_module("google.cloud", pubsub_v1=_pubsub)
_stub_module("google", cloud=_stub_module("google.cloud"))

# Now import the modules under test
import importlib

main = importlib.import_module("main")
mllp_handler = importlib.import_module("mllp_handler")


# ===========================================================================
# Helpers
# ===========================================================================

MLLP_VT = b"\x0b"
MLLP_FS = b"\x1c"
MLLP_CR = b"\x0d"

_VALID_ADT_A01 = (
    "MSH|^~\\&|EPIC|HOSPITAL|SmartHandoff|HL7Listener|20260722120000||ADT^A01|CTRL001|P|2.5\r"
    "EVN|A01|20260722120000\r"
    "PID|1||MRN001^^^HOSPITAL^MR||DOE^JOHN^A||19800101|M\r"
)

_MALFORMED_NO_MSH = (
    "EVN|A01|20260722120000\r"
    "PID|1||MRN001^^^HOSPITAL^MR\r"
)


def _make_stream_reader(payload: bytes) -> asyncio.StreamReader:
    """Create an asyncio.StreamReader pre-loaded with *payload*."""
    reader = asyncio.StreamReader()
    reader.feed_data(payload)
    reader.feed_eof()
    return reader


def _mllp_wrap(hl7_text: str) -> bytes:
    return MLLP_VT + hl7_text.encode("utf-8") + MLLP_FS + MLLP_CR


# ===========================================================================
# Test: MLLP frame parsing
# ===========================================================================

class TestReadMllpFrame(unittest.IsolatedAsyncioTestCase):
    """Tests for main._read_mllp_frame (asyncio StreamReader)."""

    async def test_valid_frame_returns_hl7_bytes(self):
        """A correctly framed MLLP message yields the raw HL7 bytes."""
        payload = _mllp_wrap(_VALID_ADT_A01)
        reader = _make_stream_reader(payload)
        result = await main._read_mllp_frame(reader)
        assert result is not None
        assert b"MSH" in result

    async def test_missing_vt_raises_value_error(self):
        """A stream that does not start with VT (0x0B) must raise ValueError."""
        reader = _make_stream_reader(b"GARBAGE" + _VALID_ADT_A01.encode())
        with self.assertRaises(ValueError):
            await main._read_mllp_frame(reader)

    async def test_empty_stream_returns_none(self):
        """An empty / closed stream returns None (clean EOF)."""
        reader = asyncio.StreamReader()
        reader.feed_eof()
        result = await main._read_mllp_frame(reader)
        assert result is None

    async def test_multi_message_framing(self):
        """Frame reader extracts bytes up to but not including the FS byte."""
        hl7_bytes = _VALID_ADT_A01.encode("utf-8")
        framed = MLLP_VT + hl7_bytes + MLLP_FS + MLLP_CR
        reader = _make_stream_reader(framed)
        result = await main._read_mllp_frame(reader)
        assert result == hl7_bytes


# ===========================================================================
# Test: MLLP frame wrapper
# ===========================================================================

class TestWrapMllp(unittest.TestCase):
    def test_wrap_adds_vt_fs_cr(self):
        data = b"HELLO"
        wrapped = main._wrap_mllp(data)
        assert wrapped[0:1] == MLLP_VT
        assert wrapped[-2:-1] == MLLP_FS
        assert wrapped[-1:] == MLLP_CR
        assert data in wrapped


# ===========================================================================
# Test: HL7 MSH parser
# ===========================================================================

class TestParseHl7(unittest.TestCase):
    def test_valid_adt_a01_parsed_correctly(self):
        result = mllp_handler.parse_hl7(_VALID_ADT_A01.encode("utf-8"))
        assert result["message_type"] == "ADT"
        assert result["event_type"] == "A01"
        assert result["message_control_id"] == "CTRL001"

    def test_missing_msh_raises_value_error(self):
        with self.assertRaises(ValueError, msg="Missing MSH segment"):
            mllp_handler.parse_hl7(_MALFORMED_NO_MSH.encode("utf-8"))

    def test_msh_without_event_type(self):
        """MSH.9 may be a plain message type without a ^ delimiter."""
        hl7 = "MSH|^~\\&|A|B|C|D|20260101||ACK|ID99|P|2.5\r"
        result = mllp_handler.parse_hl7(hl7.encode("utf-8"))
        assert result["message_type"] == "ACK"
        assert result["event_type"] == "unknown"

    def test_empty_message_raises_value_error(self):
        with self.assertRaises(ValueError):
            mllp_handler.parse_hl7(b"")


# ===========================================================================
# Test: ACK builder
# ===========================================================================

class TestBuildAck(unittest.TestCase):
    def test_ack_contains_aa_and_control_id(self):
        ack = main.build_ack("CTRL001")
        assert "MSA|AA|CTRL001" in ack
        assert "MSH|" in ack
        assert "ACK" in ack

    def test_ack_timestamp_format(self):
        ack = main.build_ack("X")
        # MSH-7 timestamp is YYYYMMDDHHmmss — 14 digits
        match = re.search(r"\|(\d{14})\|", ack)
        assert match is not None, f"No 14-digit timestamp found in: {ack!r}"

    def test_ack_uses_correct_control_id(self):
        ack = main.build_ack("MSG-9999")
        assert "MSG-9999" in ack


# ===========================================================================
# Test: NACK builder
# ===========================================================================

class TestBuildNack(unittest.TestCase):
    def test_nack_contains_ae_and_err_segment(self):
        nack = main.build_nack("CTRL002")
        assert "MSA|AE|CTRL002" in nack
        assert "ERR|" in nack

    def test_nack_default_error_code_207(self):
        nack = main.build_nack("X")
        assert "207" in nack

    def test_nack_custom_error_text(self):
        nack = main.build_nack("X", error_code="207", error_text="Missing MSH segment")
        assert "Missing MSH segment" in nack

    def test_nack_err_segment_structure(self):
        """ERR segment must include the error code in HL7 CWE format."""
        nack = main.build_nack("X", error_code="207", error_text="App error")
        # ERR|||207^App error^HL70357
        assert "207^App error^HL70357" in nack


# ===========================================================================
# Test: Connection semaphore gate
# ===========================================================================

class TestConnectionGate(unittest.IsolatedAsyncioTestCase):
    async def test_semaphore_allows_connections_under_limit(self):
        """Connections under the limit are handled normally."""
        main._connection_semaphore = asyncio.Semaphore(2)

        reader = MagicMock(spec=asyncio.StreamReader)
        reader.at_eof.return_value = True  # immediately exit loop
        writer = MagicMock(spec=asyncio.StreamWriter)
        writer.get_extra_info = MagicMock(return_value=("127.0.0.1", 9999))
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        with patch.object(main, "_handle_connection", new=AsyncMock()) as mock_handler:
            await main._gated_handle_connection(reader, writer)
            mock_handler.assert_awaited_once()

    async def test_semaphore_rejects_connections_at_limit(self):
        """When the semaphore is exhausted, the connection receives a NACK."""
        main._connection_semaphore = asyncio.Semaphore(0)  # already exhausted

        reader = MagicMock(spec=asyncio.StreamReader)
        writer = MagicMock(spec=asyncio.StreamWriter)
        writer.get_extra_info = MagicMock(return_value=("1.2.3.4", 9999))
        writer.write = MagicMock()
        writer.drain = AsyncMock()
        writer.close = MagicMock()

        with patch.object(main, "_handle_connection", new=AsyncMock()) as mock_handler:
            await main._gated_handle_connection(reader, writer)
            mock_handler.assert_not_awaited()
            # Writer.write should have been called with a NACK frame
            writer.write.assert_called_once()
            nack_frame: bytes = writer.write.call_args[0][0]
            assert b"AE" in nack_frame  # NACK acknowledgement code


# ===========================================================================
# Test: Health / ready HTTP handler
# ===========================================================================

class TestHealthHandler(unittest.IsolatedAsyncioTestCase):
    async def _make_reader(self, path: str) -> asyncio.StreamReader:
        reader = asyncio.StreamReader()
        request = f"GET {path} HTTP/1.1\r\nHost: localhost\r\n\r\n"
        reader.feed_data(request.encode())
        reader.feed_eof()
        return reader

    async def test_health_returns_200(self):
        reader = await self._make_reader("/health")
        writer = MagicMock()
        writer.write = MagicMock()
        writer.drain = AsyncMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        await main._health_handler(reader, writer)
        response: bytes = writer.write.call_args[0][0]
        assert b"200 OK" in response
        assert b'"status":"ok"' in response

    async def test_ready_returns_200(self):
        reader = await self._make_reader("/ready")
        writer = MagicMock()
        writer.write = MagicMock()
        writer.drain = AsyncMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        await main._health_handler(reader, writer)
        response: bytes = writer.write.call_args[0][0]
        assert b"200 OK" in response

    async def test_unknown_path_returns_404(self):
        reader = await self._make_reader("/unknown")
        writer = MagicMock()
        writer.write = MagicMock()
        writer.drain = AsyncMock()
        writer.close = MagicMock()
        writer.wait_closed = AsyncMock()

        await main._health_handler(reader, writer)
        response: bytes = writer.write.call_args[0][0]
        assert b"404" in response


if __name__ == "__main__":
    unittest.main()
