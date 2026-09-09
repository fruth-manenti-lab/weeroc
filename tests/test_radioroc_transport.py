from __future__ import annotations

from collections import deque
from contextlib import contextmanager
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

# Bootstrap the source package for both installed and legacy checkout test runs.
import radioroc_client
from radioroc.protocol.frames import FrameError, decode_read_response, encode_read_request, encode_write_request
from radioroc.transport.discovery import BoardPort, board_identity, canonical_port
from radioroc.transport.errors import (
    DeviceBusyError, TransportClosedError, TransportIOError,
    TransportProtocolError, TransportTimeoutError,
)
from radioroc.transport.ownership import BoardLease
from radioroc.transport.serial import RadiorocSerial


class ScriptedSerial:
    """Replies become available only after a request; reads respect fragmentation."""

    def __init__(self, chunks=()):
        self.chunks = deque(chunks)
        self.timeout = 0.01
        self.out_waiting = 0
        self.writes = []
        self.closed = False
        self.close_error = False

    def write(self, frame):
        self.writes.append(frame)
        return len(frame)

    def read(self, size):
        if not self.chunks:
            return b""
        chunk = self.chunks.popleft()
        if isinstance(chunk, Exception):
            raise chunk
        if len(chunk) > size:
            self.chunks.appendleft(chunk[size:])
        return chunk[:size]

    def reset_input_buffer(self):
        pass

    def reset_output_buffer(self):
        pass

    def close(self):
        if self.close_error:
            raise OSError("close failed")
        self.closed = True


@contextmanager
def fake_session(fake):
    with tempfile.TemporaryDirectory() as directory:
        with patch("radioroc.transport.serial.board_identity", return_value="usb:test"), \
             patch("radioroc.transport.serial.serial.Serial", return_value=fake):
            with RadiorocSerial("test-port", timeout=0.01, lock_dir=Path(directory)) as connection:
                yield connection


class ProtocolTests(unittest.TestCase):
    def test_golden_request_boundaries(self):
        vectors = {
            1: "aa 00 e4 00 55", 255: "aa fe e4 00 55", 256: "aa ff e4 00 55",
            257: "aa 00 e4 01 55", 65535: "aa fe e4 ff 55", 65536: "aa ff e4 ff 55",
        }
        for length, frame in vectors.items():
            self.assertEqual(encode_read_request(100, length), bytes.fromhex(frame))
        self.assertEqual(encode_write_request(127, b"\x03"), bytes.fromhex("aa 00 7f 03 55"))
        frame = encode_write_request(20, bytes(range(256)))
        self.assertEqual(frame[:3], bytes.fromhex("aa ff 14"))
        self.assertEqual(frame[3:-1], bytes(range(256)))

    def test_invalid_requests_rejected(self):
        for address in (-1, 128, True, 1.5, "1"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                encode_read_request(address)
        for length in (0, 65537, False, 1.5):
            with self.subTest(length=length), self.assertRaises(ValueError):
                encode_read_request(0, length)
        for payload in (b"", bytes(257), "x", [1]):
            with self.subTest(payload=type(payload)), self.assertRaises(ValueError):
                encode_write_request(0, payload)

    def test_response_validates_only_established_fields(self):
        self.assertEqual(decode_read_response(bytes.fromhex("aa 00 e4 05 55"), 1), b"\x05")
        self.assertEqual(decode_read_response(bytes.fromhex("aa 81 42 aa 55 55"), 2), b"\xaa\x55")
        for reply in (b"", bytes.fromhex("ab 00 e4 05 55"), bytes.fromhex("aa 00 e4 05 54")):
            with self.assertRaises(FrameError):
                decode_read_response(reply, 1)

    def test_legacy_imports_share_implementation(self):
        self.assertIs(radioroc_client.RadiorocSerial, RadiorocSerial)
        self.assertIs(radioroc_client.encode_read_request, encode_read_request)


class SerialTests(unittest.TestCase):
    def test_fragmented_reply_and_leading_noise(self):
        fake = ScriptedSerial([b"noise", b"\xaa", b"\x00\xe4", b"\x05", b"\x55"])
        with fake_session(fake) as connection:
            self.assertEqual(connection.read_word(100), "00000101")
            self.assertEqual(fake.timeout, 0.01)
        self.assertEqual(fake.writes, [bytes.fromhex("aa 00 e4 00 55")])
        self.assertTrue(fake.closed)

    def test_bad_footer_does_not_resync_inside_payload_or_resend(self):
        # First example contains another whole response; second contains AA/55
        # in corrupt payload bytes that could otherwise look like a new frame.
        for stream in ("aa 00 e4 05 54 aa 00 e4 06 55", "aa 00 e4 aa 00 e4 07 55"):
            fake = ScriptedSerial([bytes.fromhex(stream)])
            with self.subTest(stream=stream), fake_session(fake) as connection:
                with self.assertRaisesRegex(TransportProtocolError, "footer"):
                    connection.read_word(100)
            self.assertEqual(len(fake.writes), 1)

    def test_large_binary_payload_including_delimiters(self):
        payload = bytes(range(256)) * 2
        fake = ScriptedSerial([b"\xaa\x00\x94" + payload + b"\x55"])
        with fake_session(fake) as connection:
            self.assertEqual(connection.read_words(20, len(payload)), payload)

    def test_timeout_and_partial_fifo_are_not_retried(self):
        for chunks, error in (([], TransportTimeoutError),
                              ([b"\xaa\x00\xb7\x05"], TransportProtocolError),
                              ([b"garbage"], TransportProtocolError)):
            fake = ScriptedSerial(chunks)
            with self.subTest(error=error), fake_session(fake) as connection:
                with self.assertRaises(error):
                    connection.read_words(55, 1)
                self.assertEqual(fake.writes, [bytes.fromhex("aa 00 b7 00 55")])

    def test_disconnect_is_explicit_and_releases_lease_on_exit(self):
        fake = ScriptedSerial([OSError("USB disconnected")])
        with fake_session(fake) as connection:
            with self.assertRaisesRegex(TransportIOError, "USB disconnected"):
                connection.read_word(100)
        self.assertTrue(fake.closed)
        self.assertIsNone(connection._lease)

    def test_short_write_is_not_retried(self):
        fake = ScriptedSerial()
        with fake_session(fake) as connection, patch.object(fake, "write", return_value=2) as write:
            with self.assertRaisesRegex(TransportIOError, "short write"):
                connection.write_word(1, "1")
            write.assert_called_once()

    def test_stalled_output_has_a_deadline(self):
        fake = ScriptedSerial()
        fake.out_waiting = 10
        with fake_session(fake) as connection:
            with self.assertRaisesRegex(TransportIOError, "write drain timed out"):
                connection.write_word(1, "1")

    def test_chunks_target_same_fifo_address_and_invalid_writes_do_nothing(self):
        fake = ScriptedSerial()
        with fake_session(fake) as connection:
            connection.write_words(56, b"\x07" * 257)
            self.assertEqual(fake.writes, [b"\xaa\xff\x38" + b"\x07" * 256 + b"\x55",
                                           bytes.fromhex("aa 00 38 07 55")])
            for payload in (b"", "bad"):
                with self.assertRaises(ValueError):
                    connection.write_words(56, payload)
            for word in ("100000000", "-1", "", "222"):
                with self.assertRaises(ValueError):
                    connection.write_word(1, word)
            self.assertEqual(len(fake.writes), 2)

    def test_closed_and_invalid_connections(self):
        with self.assertRaises(TransportClosedError):
            RadiorocSerial("test-port").read_word(100)
        for timeout in (0, -1, float("nan"), float("inf"), True):
            with self.assertRaises(ValueError):
                RadiorocSerial("test-port", timeout=timeout)

    def test_open_and_initialization_failures_release_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            options = {"lock_dir": Path(directory)}
            with patch("radioroc.transport.serial.board_identity", return_value="usb:test"):
                with patch("radioroc.transport.serial.serial.Serial", side_effect=OSError("missing")):
                    connection = RadiorocSerial("test-port", **options)
                    with self.assertRaises(TransportIOError):
                        connection.__enter__()
                    self.assertIsNone(connection._lease)
                fake = ScriptedSerial()
                with patch("radioroc.transport.serial.serial.Serial", return_value=fake), \
                     patch.object(fake, "reset_input_buffer", side_effect=OSError("init failed")):
                    with self.assertRaises(TransportIOError):
                        RadiorocSerial("test-port", **options).__enter__()
                    self.assertTrue(fake.closed)
                with BoardLease("usb:test", "test-port", directory=Path(directory)):
                    pass

    def test_busy_board_prevents_serial_open(self):
        with tempfile.TemporaryDirectory() as directory:
            with BoardLease("usb:test", "interface-a", directory=Path(directory)), \
                 patch("radioroc.transport.serial.board_identity", return_value="usb:test"), \
                 patch("radioroc.transport.serial.serial.Serial") as factory:
                with self.assertRaises(DeviceBusyError):
                    RadiorocSerial("interface-b", lock_dir=Path(directory)).__enter__()
                factory.assert_not_called()

    def test_close_failure_retains_ownership_until_close_succeeds(self):
        fake = ScriptedSerial()
        with fake_session(fake) as connection:
            fake.close_error = True
            with self.assertRaises(TransportIOError):
                connection.close()
            with self.assertRaises(DeviceBusyError):
                BoardLease("usb:test", "another-port", directory=connection._lock_dir).acquire()
            fake.close_error = False
            connection.close()
            with BoardLease("usb:test", "another-port", directory=connection._lock_dir):
                pass

    def test_failed_asic_readback_does_not_return_defaults(self):
        device = radioroc_client.RadiorocDevice(radioroc_client.RadiorocMemoryTransport())
        device.load_default_config()
        with patch.object(device, "read_fifo", side_effect=TransportTimeoutError("missing")):
            with self.assertRaises(TransportTimeoutError):
                device.read_register_bits(0, 1)
        with patch.object(device, "read_fifo", return_value=b""):
            with self.assertRaises(TransportProtocolError):
                device.read_register_bits(0, 1)
        device.dry_run = True
        with patch.object(device, "read_fifo") as read:
            self.assertEqual(device.read_register_bits(0, 1), device.find_i2c_row(0, 1).data)
            read.assert_not_called()


class IdentityTests(unittest.TestCase):
    def test_shared_serial_across_interfaces_and_distinct_boards(self):
        first = BoardPort("/dev/cu.usbserial-RD3_320", "PCB_RADIOROC", 0x403, 0x6010, "RD3_32", "1-1", None)
        second = BoardPort("/dev/cu.usbserial-RD3_321", "PCB_RADIOROC", 0x403, 0x6010, "RD3_32", "1-1", None)
        other = BoardPort("/dev/cu.usbserial-RD3_330", "PCB_RADIOROC", 0x403, 0x6010, "RD3_33", "1-2", None)
        self.assertEqual(first.identity, second.identity)
        self.assertNotEqual(first.identity, other.identity)
        with patch("radioroc.transport.discovery.list_board_ports", return_value=[first, second]):
            self.assertEqual(board_identity("/dev/tty.usbserial-RD3_320"), second.identity)

    def test_linux_location_fallback_groups_interfaces(self):
        first = BoardPort("/dev/ttyUSB0", "", 0x403, 0x6010, None, "1-2.3:1.0", None)
        second = BoardPort("/dev/ttyUSB1", "", 0x403, 0x6010, None, "1-2.3:1.1", None)
        self.assertEqual(first.identity, second.identity)

    @unittest.skipUnless(os.name == "posix", "POSIX device aliases")
    def test_symlink_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "port"
            target.touch()
            alias = Path(directory) / "alias"
            alias.symlink_to(target)
            self.assertEqual(canonical_port(str(target)), canonical_port(str(alias)))


@unittest.skipUnless(os.name == "posix", "process-lock acceptance currently targets macOS/Linux")
class ProcessOwnershipTests(unittest.TestCase):
    CHILD = '''
from pathlib import Path
import sys
from radioroc.transport.ownership import BoardLease
from radioroc.transport.errors import DeviceBusyError
try:
    with BoardLease(sys.argv[2], sys.argv[3], directory=Path(sys.argv[1])):
        print('OWNED', flush=True)
        if sys.argv[4] == 'hold':
            sys.stdin.readline()
except DeviceBusyError:
    print('BUSY', flush=True)
    sys.exit(12)
'''

    def child_args(self, directory, identity="usb:test", port="port-a", mode="try"):
        return [sys.executable, "-c", self.CHILD, directory, identity, port, mode]

    def test_separate_processes_normal_exit_and_crash(self):
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
        for crash in (False, True):
            with self.subTest(crash=crash), tempfile.TemporaryDirectory() as directory:
                holder = subprocess.Popen(self.child_args(directory, mode="hold"), env=env,
                                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    with selectors.DefaultSelector() as selector:
                        selector.register(holder.stdout, selectors.EVENT_READ)
                        self.assertTrue(selector.select(timeout=10), "lock holder startup timed out")
                    self.assertEqual(holder.stdout.readline().strip(), "OWNED")
                    contender = subprocess.run(self.child_args(directory, port="port-b"), env=env,
                                               capture_output=True, text=True, timeout=10)
                    self.assertEqual(contender.returncode, 12, contender.stderr)
                    self.assertEqual(contender.stdout.strip(), "BUSY")
                    other = subprocess.run(self.child_args(directory, identity="usb:other"), env=env,
                                           capture_output=True, text=True, timeout=10)
                    self.assertEqual(other.returncode, 0, other.stderr)
                    if crash:
                        holder.kill()
                        holder.communicate(timeout=10)
                    else:
                        holder.communicate(input="stop\n", timeout=10)
                    next_owner = subprocess.run(self.child_args(directory), env=env,
                                                capture_output=True, text=True, timeout=10)
                    self.assertEqual(next_owner.returncode, 0, next_owner.stderr)
                finally:
                    if holder.poll() is None:
                        holder.kill()
                    holder.communicate(timeout=10)


if __name__ == "__main__":
    unittest.main()
