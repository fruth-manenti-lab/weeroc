"""One channel selection shared by every Calibration sub-page and Acquisition.

The Calibration page owns the selection. The scan windows and the Acquisition
window read it from here instead of each keeping their own channel grid.

Trigger channels follow the selection automatically (``auto_triggers`` True):
T1 is the lowest selected channel and T2 is the next selected one, or T1 again
when only one channel is selected. Setting a trigger channel by hand turns
``auto_triggers`` off until it is turned back on.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

N_CHANNELS = 64
_FALLBACK_T1 = 4
_FALLBACK_T2 = 5
DEFAULT_HOLD_DELAY_NS = 530
MAX_HOLD_DELAY_NS = 100000
DEFAULT_TRIGGER_GAIN = 1
MIN_TRIGGER_GAIN = 1
MAX_TRIGGER_GAIN = 63
DEFAULT_OPERATING_THRESHOLD = 540
MAX_OPERATING_THRESHOLD = 1023


class CalibrationSelection(QObject):
    channels_changed = Signal(list)       # sorted list[int]
    triggers_changed = Signal(int, int)   # T1, T2
    auto_changed = Signal(bool)
    hold_delay_changed = Signal(int)      # external hold delay, ns
    trigger_gain_changed = Signal(int)    # trigger preamp gain code 1..63
    operating_threshold_changed = Signal(int)  # threshold DAC code 0..1023

    def __init__(self, channels=(4, 5), parent=None):
        super().__init__(parent)
        self._channels = self._clean(channels)
        self._auto = True
        self._hold_delay_ns = DEFAULT_HOLD_DELAY_NS
        self._trigger_gain = DEFAULT_TRIGGER_GAIN
        self._operating_threshold = DEFAULT_OPERATING_THRESHOLD
        self._t1, self._t2 = self._auto_triggers()

    @staticmethod
    def _clean(channels):
        cleaned = sorted({int(c) for c in channels})
        for channel in cleaned:
            if not 0 <= channel < N_CHANNELS:
                raise ValueError(f"channel {channel} is outside 0..{N_CHANNELS - 1}")
        return cleaned

    def _auto_triggers(self):
        if not self._channels:
            return _FALLBACK_T1, _FALLBACK_T2
        t1 = self._channels[0]
        t2 = self._channels[1] if len(self._channels) > 1 else t1
        return t1, t2

    # -- reading ------------------------------------------------------------
    def channels(self) -> list:
        return list(self._channels)

    @property
    def trigger_channel(self) -> int:
        return self._t1

    @property
    def trigger_channel_2(self) -> int:
        return self._t2

    @property
    def hold_delay_ns(self) -> int:
        return self._hold_delay_ns

    @property
    def trigger_gain(self) -> int:
        return self._trigger_gain

    @property
    def operating_threshold(self) -> int:
        return self._operating_threshold

    @property
    def auto_triggers(self) -> bool:
        return self._auto

    # -- writing ------------------------------------------------------------
    def set_channels(self, channels) -> None:
        cleaned = self._clean(channels)
        if cleaned == self._channels:
            return
        self._channels = cleaned
        self.channels_changed.emit(list(cleaned))
        if self._auto:
            self._apply_triggers(*self._auto_triggers())

    def set_trigger_channels(self, t1: int, t2: int | None = None) -> None:
        """Choose trigger channels by hand; this turns automatic selection off."""
        t1 = int(t1)
        t2 = t1 if t2 is None else int(t2)
        for channel in (t1, t2):
            if not 0 <= channel < N_CHANNELS:
                raise ValueError(f"channel {channel} is outside 0..{N_CHANNELS - 1}")
        if self._auto:
            self._auto = False
            self.auto_changed.emit(False)
        self._apply_triggers(t1, t2)

    def set_auto_triggers(self, auto: bool) -> None:
        auto = bool(auto)
        if auto == self._auto:
            return
        self._auto = auto
        self.auto_changed.emit(auto)
        if auto:
            self._apply_triggers(*self._auto_triggers())

    def _apply_triggers(self, t1: int, t2: int) -> None:
        if (t1, t2) != (self._t1, self._t2):
            self._t1, self._t2 = t1, t2
            self.triggers_changed.emit(t1, t2)

    def set_hold_delay_ns(self, value: int) -> None:
        value = int(value)
        if not 0 <= value <= MAX_HOLD_DELAY_NS:
            raise ValueError(f"hold delay {value} ns is outside 0..{MAX_HOLD_DELAY_NS}")
        if value != self._hold_delay_ns:
            self._hold_delay_ns = value
            self.hold_delay_changed.emit(value)

    def set_trigger_gain(self, value: int) -> None:
        value = int(value)
        if not MIN_TRIGGER_GAIN <= value <= MAX_TRIGGER_GAIN:
            raise ValueError(
                f"trigger gain {value} is outside {MIN_TRIGGER_GAIN}..{MAX_TRIGGER_GAIN}")
        if value != self._trigger_gain:
            self._trigger_gain = value
            self.trigger_gain_changed.emit(value)

    def set_operating_threshold(self, value: int) -> None:
        value = int(value)
        if not 0 <= value <= MAX_OPERATING_THRESHOLD:
            raise ValueError(
                f"operating threshold {value} is outside 0..{MAX_OPERATING_THRESHOLD}")
        if value != self._operating_threshold:
            self._operating_threshold = value
            self.operating_threshold_changed.emit(value)


def bind_trigger_gain(spin, selection) -> None:
    """Two-way bind a QSpinBox to ``selection.trigger_gain`` (drops 'Keep current')."""
    spin.setSpecialValueText("")
    spin.setRange(MIN_TRIGGER_GAIN, MAX_TRIGGER_GAIN)
    spin.setValue(selection.trigger_gain)
    spin.valueChanged.connect(selection.set_trigger_gain)
    selection.trigger_gain_changed.connect(
        lambda value: spin.setValue(value) if spin.value() != value else None)


def bind_operating_threshold(spin, selection) -> None:
    """Two-way bind a QSpinBox to ``selection.operating_threshold`` (drops 'Keep current')."""
    spin.setSpecialValueText("")
    spin.setRange(0, MAX_OPERATING_THRESHOLD)
    spin.setValue(selection.operating_threshold)
    spin.valueChanged.connect(selection.set_operating_threshold)
    selection.operating_threshold_changed.connect(
        lambda value: spin.setValue(value) if spin.value() != value else None)
