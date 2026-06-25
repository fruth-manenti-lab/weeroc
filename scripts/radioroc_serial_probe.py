from __future__ import annotations

import argparse
import time

import serial


DEFAULT_PORTS = ["/dev/cu.usbserial-RD3_320", "/dev/cu.usbserial-RD3_321"]
DEFAULT_BAUDS = [9600, 115200, 921600, 1_000_000, 2_000_000, 3_000_000]


def read_frame(address: int, length: int = 1) -> bytes:
    if not 0 <= address <= 127:
        raise ValueError("address must be in range 0..127")
    if not 1 <= length <= 65536:
        raise ValueError("length must be in range 1..65536")
    encoded_length = length - 1
    return bytes(
        [
            0xAA,
            encoded_length & 0xFF,
            address | 0x80,
            (encoded_length >> 8) & 0xFF,
            0x55,
        ]
    )


def probe_port(port: str, baud: int, frame: bytes, timeout: float) -> bytes:
    with serial.Serial(port, baudrate=baud, timeout=timeout, write_timeout=timeout) as ser:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        ser.write(frame)
        ser.flush()
        time.sleep(0.15)
        return ser.read(64)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only RADIOROC USB serial probe.")
    parser.add_argument("--address", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=0.25)
    parser.add_argument("--port", action="append", default=[])
    parser.add_argument("--baud", action="append", type=int, default=[])
    args = parser.parse_args()

    ports = args.port or DEFAULT_PORTS
    bauds = args.baud or DEFAULT_BAUDS
    frame = read_frame(args.address)
    print(f"read address {args.address}: {frame.hex(' ')}")

    for port in ports:
        print(f"\nPORT {port}")
        for baud in bauds:
            try:
                data = probe_port(port, baud, frame, args.timeout)
                print(f"  baud {baud}: {len(data)} bytes {data.hex(' ')} {data!r}")
            except Exception as exc:
                print(f"  baud {baud}: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
