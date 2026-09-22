"""Framed serial communication with one board lease per open session."""

from __future__ import annotations

import math
import os
from pathlib import Path
import threading
import time

import serial

from radioroc.protocol.frames import (
    bits, decode_read_response, encode_read_request, encode_write_request, validate_integer,
)
from .config import DEFAULT_PORT, DEFAULT_BAUD, DEFAULT_TIMEOUT_SECONDS, RadiorocConnectionConfig
from .discovery import board_identity
from .errors import (
    DeviceBusyError, TransportClosedError, TransportIOError,
    TransportProtocolError, TransportTimeoutError,
)
from .ownership import BoardLease


class RadiorocSerial:
    """Open an explicitly selected port and own its logical USB board.

    Requests are never automatically resent: a FIFO read may already have
    consumed data even when its response is lost. Fragmented replies are assembled
    within one deadline. Calls on this object serialize individual transactions;
    coordinating entire workflows belongs to the application job layer.
    """

    def __init__(self, port: str = DEFAULT_PORT, baud: int = DEFAULT_BAUD,
                 timeout: float = DEFAULT_TIMEOUT_SECONDS, *, lock_dir: Path | None = None):
        if not isinstance(port, str) or not port.strip():
            raise ValueError("port must be a nonempty device path")
        validate_integer(baud, 1, 100_000_000, "baud")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and greater than zero")
        self.port, self.baud, self.timeout = port, baud, timeout
        self.ser: serial.Serial | None = None
        self._lock_dir = lock_dir
        self._lease: BoardLease | None = None
        self._mutex = threading.RLock()

    @classmethod
    def from_config(cls, config: RadiorocConnectionConfig) -> "RadiorocSerial":
        return cls(config.port, config.baud, config.timeout_s)

    def __enter__(self) -> "RadiorocSerial":
        with self._mutex:
            if self.ser is not None or self._lease is not None:
                raise DeviceBusyError(f"session for {self.port} is already open")
            lease = BoardLease(board_identity(self.port), self.port, directory=self._lock_dir)
            lease.acquire()
            self._lease = lease
            try:
                options = {"exclusive": True} if os.name == "posix" else {}
                self.ser = serial.Serial(self.port, baudrate=self.baud, timeout=self.timeout,
                                         write_timeout=self.timeout, **options)
                self.ser.reset_input_buffer()
                self.ser.reset_output_buffer()
            except BaseException as exc:
                self.close()
                if isinstance(exc, (OSError, serial.SerialException)):
                    raise TransportIOError(f"cannot open/initialize {self.port}: {exc}") from exc
                raise
            return self

    def close(self) -> None:
        """Close the port before releasing ownership; retain the lease if close fails."""
        with self._mutex:
            if self.ser is not None:
                try:
                    self.ser.close()
                except (OSError, serial.SerialException) as exc:
                    raise TransportIOError(f"cannot close {self.port}; board lease retained: {exc}") from exc
                self.ser = None
            if self._lease is not None:
                self._lease.release()
                self._lease = None

    def __exit__(self, *exc: object) -> None:
        self.close()

    def transfer(self, frame: bytes, read_len: int = 0) -> bytes:
        """Send one validated frame and return a full response or an explicit error.

        `read_len` includes the four response framing bytes. Input buffers are
        cleared before read requests, as in the legacy protocol. A malformed
        response reports a short hexadecimal prefix for diagnosis.
        """
        validate_integer(read_len, 0, 65540, "read_len")
        if not isinstance(frame, bytes) or len(frame) < 5:
            raise ValueError("frame must be encoded request bytes")
        if read_len:
            expected = encode_read_request(frame[2] & 0x7F, read_len - 4)
        else:
            expected = encode_write_request(frame[2], frame[3:-1])
        if frame != expected:
            raise ValueError("frame does not match its requested transfer length/type")
        with self._mutex:
            if self.ser is None:
                raise TransportClosedError(f"serial port {self.port} is not open")
            connection = self.ser
            try:
                if read_len:
                    connection.reset_input_buffer()
                write_deadline = time.monotonic() + self.timeout
                written = connection.write(frame)
                if written != len(frame):
                    raise TransportIOError(f"short write to {self.port}: {written}/{len(frame)} bytes; not retried")
                # Avoid an unbounded tcdrain/flush on a stalled or disconnected port.
                while connection.out_waiting:
                    if time.monotonic() >= write_deadline:
                        raise TransportIOError(f"write drain timed out on {self.port}; not retried")
                    time.sleep(0.001)
                if not read_len:
                    return b""
                return self._receive(connection, read_len)
            except (OSError, serial.SerialException) as exc:
                if isinstance(exc, TransportTimeoutError):
                    raise
                raise TransportIOError(f"serial I/O failed on {self.port}: {exc}") from exc

    def _receive(self, connection: serial.Serial, read_len: int) -> bytes:
        deadline = time.monotonic() + self.timeout
        data = bytearray()
        sample = bytearray()
        received = 0
        original_timeout = connection.timeout
        try:
            while time.monotonic() < deadline:
                connection.timeout = min(0.05, max(0.0, deadline - time.monotonic()))
                chunk = connection.read(min(4096, max(1, read_len - len(data))))
                received += len(chunk)
                sample.extend(chunk[:max(0, 32 - len(sample))])
                data.extend(chunk)
                # Skip non-header leading noise, but never hunt inside a corrupt
                # payload for another frame: ADC data can contain AA/55 itself.
                while data:
                    header = data.find(b"\xaa")
                    if header < 0:
                        data.clear()
                        break
                    if header:
                        del data[:header]
                    if len(data) < read_len:
                        break
                    candidate = bytes(data[:read_len])
                    if candidate[-1] == 0x55:
                        decode_read_response(candidate, read_len - 4)
                        return candidate
                    raise TransportProtocolError(
                        f"malformed response footer on {self.port}; "
                        f"prefix={candidate[:32].hex(' ')}; request not retried"
                    )
                if not chunk:
                    time.sleep(min(0.001, max(0.0, deadline - time.monotonic())))
        finally:
            connection.timeout = original_timeout
        if received:
            raise TransportProtocolError(
                f"incomplete/malformed response on {self.port}: expected {read_len} bytes, "
                f"received {received}; prefix={sample.hex(' ')}; request not retried"
            )
        raise TransportTimeoutError(f"no response from {self.port} within {self.timeout:g}s; request not retried")

    def read_word(self, address: int) -> str:
        response = self.transfer(encode_read_request(address), 5)
        return bits(decode_read_response(response, 1)[0], 8)

    def read_words(self, address: int, length: int) -> bytes:
        # Preserve the existing encoder/client's 65536-byte maximum. The vendor
        # wrapper limits this to 65535; test the boundary offline, not on hardware.
        response = self.transfer(encode_read_request(address, length), length + 4)
        return decode_read_response(response, length)

    def write_word(self, address: int, word_bits: str) -> None:
        # Some existing FPGA operations provide seven bits; preserve zero-padding.
        if not isinstance(word_bits, str) or not 1 <= len(word_bits.strip()) <= 8 or set(word_bits.strip()) - {"0", "1"}:
            raise ValueError("word_bits must contain one to eight binary digits")
        self.transfer(encode_write_request(address, bytes([int(word_bits, 2)])))

    def write_words(self, address: int, payload: bytes) -> None:
        if not isinstance(payload, (bytes, bytearray, memoryview)):
            raise ValueError("payload must be bytes-like")
        payload = bytes(payload)
        encode_write_request(address, payload[:256])  # Validate before any I/O.
        with self._mutex:
            for offset in range(0, len(payload), 256):
                self.transfer(encode_write_request(address, payload[offset:offset + 256]))
