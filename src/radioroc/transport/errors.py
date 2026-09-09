"""Failures shared by transport callers without parsing terminal messages."""


class TransportError(RuntimeError):
    """Base error for connection, ownership, and serial transfer failures."""


class DeviceBusyError(TransportError):
    """Another session owns this board, or a session was opened twice."""


class TransportIOError(TransportError):
    """Opening or accessing the serial device failed."""


class TransportClosedError(TransportError):
    """An operation requires an open serial session."""


class TransportTimeoutError(TransportError, TimeoutError):
    """The device supplied no response before the read deadline."""


class TransportProtocolError(TransportError):
    """The device supplied an incomplete or malformed response."""
