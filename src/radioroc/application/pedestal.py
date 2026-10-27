"""Pedestal measurement: a forced-trigger acquisition with no input pulses.

Wraps `AcquisitionJob` (snapshot/restore/verify/cancellation are its) with fixed
forced-trigger settings, then computes per-channel pedestals from the saved events and
writes ``pedestals.json`` into the run folder. Verified on the bench: the FPGA synchro
pulse per ADC batch (the vendor's "forced trigger") reads clean pedestals with the SiPMs
attached, independent of any discriminator condition.
"""

from dataclasses import dataclass
from pathlib import Path

from radioroc_client import AcquisitionConfig, AcquisitionResult, RadiorocDevice
from radioroc.data.acquisition_reader import read_acquisition_run
from radioroc.data.pedestals import PEDESTALS_FILENAME, PedestalSet, compute_pedestals, save_pedestals_json
from .acquisition import AcquisitionJob, AcquisitionJobConfig
from .jobs import CancellationToken

ACQUISITIONS_PER_BATCH = 20
DEFAULT_EVENTS = 200
DEFAULT_THRESHOLD_DAC = 550  # irrelevant when forced; kept so the discriminator is in a defined state


@dataclass(frozen=True)
class PedestalJobConfig:
    channels: list[int]
    out_dir: Path
    hold_delay_ns: int = 30
    conversion_delay_ns: int = 400
    pat_gain: int = 1
    events: int = DEFAULT_EVENTS
    high_gain_code: int | None = None
    low_gain_code: int | None = None
    timeout_s: float = 5.0
    config_path: Path | None = None
    initialize_fpga: bool = False
    apply_defaults: bool = False

    def validate(self) -> None:
        if not self.channels:
            raise ValueError("select at least one channel")
        if not isinstance(self.events, int) or isinstance(self.events, bool) or self.events < 5:
            raise ValueError("events must be a whole number of at least 5")

    @property
    def batches(self) -> int:
        return -(-self.events // ACQUISITIONS_PER_BATCH)

    def settings(self) -> dict:
        return {"channels": list(self.channels), "trigger_channel": self.channels[0],
                "hold_delay_ns": self.hold_delay_ns, "conversion_delay_ns": self.conversion_delay_ns,
                "pat_gain": self.pat_gain, "events_requested": self.batches * ACQUISITIONS_PER_BATCH,
                "acquisitions_per_batch": ACQUISITIONS_PER_BATCH, "batches": self.batches,
                "trigger": "forced (synchro pulse per ADC batch)", "adc_trigger_type": 0,
                "trigger_source": 3, "threshold_dac": DEFAULT_THRESHOLD_DAC,
                "external_trigger": False, "mask": True,
                "high_gain_code": self.high_gain_code, "low_gain_code": self.low_gain_code}

    def acquisition_job_config(self) -> AcquisitionJobConfig:
        self.validate()
        channels = sorted({int(c) for c in self.channels})
        acquisition = AcquisitionConfig(
            channels=channels, trigger_channel=channels[0], threshold_dac=DEFAULT_THRESHOLD_DAC,
            hold_delay_ns=self.hold_delay_ns, conversion_delay_ns=self.conversion_delay_ns,
            acquisitions_per_batch=ACQUISITIONS_PER_BATCH, batches=self.batches,
            timeout_s=self.timeout_s, trigger_preamp_gain=self.pat_gain,
            high_gain_code=self.high_gain_code, low_gain_code=self.low_gain_code,
            use_mask=True, trigger_type=0, trigger_source=3, external_trigger=False,
            synchro_trigger=True, out_dir=Path(self.out_dir))
        return AcquisitionJobConfig(acquisition, config_path=self.config_path,
                                    initialize_fpga=self.initialize_fpga, apply_defaults=self.apply_defaults)


@dataclass
class PedestalResult:
    acquisition: AcquisitionResult
    pedestals: PedestalSet | None = None
    path: Path | None = None
    error: str | None = None


def finish_pedestals(config: PedestalJobConfig, result: AcquisitionResult) -> PedestalResult:
    """Compute and write pedestals.json from a finished acquisition run (also used by the GUI,
    which runs the acquisition on the shared connection worker)."""
    out = PedestalResult(result)
    if result.status != "completed" or result.execution_mode == "dry-run":
        out.error = f"acquisition {result.status}; no pedestals computed"
        return out
    try:
        run_dir = Path(config.out_dir)
        run = read_acquisition_run(run_dir)
        ps = compute_pedestals(run.rows, config.channels, settings=config.settings(), source_run=str(run_dir))
        if not ps.channels:
            out.error = "no channel produced enough events (need at least 5)"
            return out
        out.pedestals = ps
        out.path = save_pedestals_json(run_dir / PEDESTALS_FILENAME, ps)
    except Exception as exc:
        out.error = f"{type(exc).__name__}: {exc}"
    return out


class PedestalJob:
    @staticmethod
    def preview(config: PedestalJobConfig) -> dict:
        preview = AcquisitionJob.preview(config.acquisition_job_config())
        preview["pedestal_settings"] = config.settings()
        return preview

    def run(self, device: RadiorocDevice, config: PedestalJobConfig, *, metadata=None,
            cancellation: CancellationToken | None = None, on_event=None,
            verify_restoration: bool = False) -> PedestalResult:
        result = AcquisitionJob().run(device, config.acquisition_job_config(), metadata=metadata,
                                      cancellation=cancellation, on_event=on_event,
                                      verify_restoration=verify_restoration)
        return finish_pedestals(config, result)
