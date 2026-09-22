"""Focused offline tests for the vendor readable_adc_acq.txt reader."""

from pathlib import Path
import tempfile
import unittest

from radioroc.data.vendor_acquisition import _HEADER, read_vendor_acquisition_file


def _data_row(index, values=None):
    """Build one 129-column vendor data row; unlisted channels report 0.0/0.0."""
    values = values or {}
    fields = [str(index)]
    for channel in range(64):
        hg, lg = values.get(channel, (0.0, 0.0))
        fields.append(str(hg))
        fields.append(str(lg))
    return ",".join(fields)


class VendorAcquisitionReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def write(self, name, text):
        path = self.directory / name
        path.write_text(text)
        return path

    def readable_text(self, data_lines):
        return "\n".join([
            str(self.directory / "readable_adc_acq.txt"),
            "Trigger type: internal, T1: 512, T2: 0, window width: 50ns, nb triggers: 1",
            "Nb acq: 3, Reset_n: manual, Acquition trigger: internal, Hold: external, 530ns delay",
            _HEADER,
            *data_lines,
        ])

    def test_header_matches_the_vendor_bytecode_exactly(self):
        # A literal spot-check against the real disassembled value, not just
        # the module's own formula re-derived the same way (which would
        # agree with itself even if the formula were wrong). The formula
        # check below is still useful as a full-length structural check.
        self.assertTrue(_HEADER.startswith("#Acq,HG0,LG0,HG1,LG1,HG2,LG2"))
        self.assertTrue(_HEADER.endswith("HG62,LG62,HG63,LG63"))
        self.assertEqual(len(_HEADER.split(",")), 129)
        self.assertEqual(_HEADER, "#Acq" + "".join(f",HG{ch},LG{ch}" for ch in range(64)))

    def test_parses_a_real_shaped_fixture_into_the_normalized_shape(self):
        text = self.readable_text([
            _data_row(1, {4: (100.5, 10.25), 5: (200.0, 20.0)}),
            _data_row(2, {4: (101.5, 11.25)}),
        ])
        path = self.write("readable_adc_acq.txt", text)
        result = read_vendor_acquisition_file(path)

        self.assertIn("Trigger type: internal", result.setup_text)
        self.assertIn("Nb acq: 3", result.setup_text)
        self.assertEqual(result.warnings, ())
        # 2 rows * 64 channels each, normalized to one dict per (acq, channel).
        self.assertEqual(len(result.rows), 128)
        self.assertIn({"acq": 1, "channel": 4, "hg": 100.5, "lg": 10.25}, result.rows)
        self.assertIn({"acq": 1, "channel": 5, "hg": 200.0, "lg": 20.0}, result.rows)
        self.assertIn({"acq": 2, "channel": 4, "hg": 101.5, "lg": 11.25}, result.rows)
        # Unlisted channels on a row still come through, zeroed.
        self.assertIn({"acq": 1, "channel": 0, "hg": 0.0, "lg": 0.0}, result.rows)

    def test_wrong_header_raises(self):
        text = self.readable_text([_data_row(1)]).replace(_HEADER, "#Acq,HG0,LG0")
        path = self.write("readable_adc_acq.txt", text)
        with self.assertRaisesRegex(ValueError, "unrecognized vendor acquisition header"):
            read_vendor_acquisition_file(path)

    def test_malformed_data_row_is_skipped_with_a_warning(self):
        text = self.readable_text([
            _data_row(1, {4: (100.0, 10.0)}),
            "garbage,not,enough,columns",
            _data_row(3, {4: (300.0, 30.0)}),
        ])
        path = self.write("readable_adc_acq.txt", text)
        result = read_vendor_acquisition_file(path)

        self.assertEqual(len(result.warnings), 1)
        self.assertIn("malformed data row", result.warnings[0])
        # The good rows before and after the bad one both survive.
        acqs = sorted({row["acq"] for row in result.rows})
        self.assertEqual(acqs, [1, 3])

    def test_non_numeric_value_in_a_row_is_skipped_with_a_warning(self):
        # Build a row with a deliberately non-numeric HG value for channel 4.
        fields = ["1"] + ["0.0"] * 128
        fields[1 + 2 * 4] = "not-a-number"
        bad_row = ",".join(fields)
        text = self.readable_text([bad_row])
        path = self.write("readable_adc_acq.txt", text)
        result = read_vendor_acquisition_file(path)
        self.assertEqual(result.rows, ())
        self.assertEqual(len(result.warnings), 1)
        self.assertIn("not numeric", result.warnings[0])

    def test_raw_filename_is_out_of_scope(self):
        path = self.write("raw_adc_acq.txt", "irrelevant content")
        with self.assertRaises(NotImplementedError):
            read_vendor_acquisition_file(path)

    def test_too_short_file_raises(self):
        path = self.write("readable_adc_acq.txt", "only\ntwo\nlines")
        with self.assertRaises(ValueError):
            read_vendor_acquisition_file(path)


if __name__ == "__main__":
    unittest.main()
