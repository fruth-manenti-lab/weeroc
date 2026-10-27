import json
import tempfile
import unittest
from pathlib import Path

from radioroc.application import calibration_file as cf


def _doc(**kw):
    base = dict(channels=[4, 5], trigger_channel=4, trigger_channel_2=5, auto_triggers=True,
                operating_threshold_dac=540, bias_voltage_text="55.2", note="hi")
    base.update(kw)
    return cf.build_document(**base)


class CalibrationFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def _run(self, status="completed", cal="verified", t1=True):
        run = self.tmp / "run"
        run.mkdir(exist_ok=True)
        (run / "autocalibration_metadata.json").write_text(json.dumps({
            "status": status, "calibration_status": cal, "operation": {"t1": t1},
            "calibration_after": {"4": 31, "5": 28}}))
        return run

    def test_round_trip(self):
        autocal = {"run_directory": "x", "trim_kind": "T1", "trims": {"4": 31, "5": 28},
                   "status": "verified"}
        path = cf.save_document(self.tmp / "a.json", _doc(autocalibration=autocal))
        data = cf.load_document(path)
        self.assertEqual(data["channels"], [4, 5])
        self.assertEqual(data["operating_threshold_dac"], 540)
        self.assertEqual((data["bias_voltage_text"], data["note"]), ("55.2", "hi"))
        self.assertEqual(data["autocalibration"]["trims"], {4: 31, 5: 28})

    def test_trigger_gain_code(self):
        path = cf.save_document(self.tmp / "g.json", _doc(trigger_gain_code=8))
        self.assertEqual(json.loads(path.read_text())["trigger_gain_code"], 8)
        self.assertEqual(cf.load_document(path)["trigger_gain_code"], 8)
        old = cf.save_document(self.tmp / "o.json", _doc())
        self.assertNotIn("trigger_gain_code", json.loads(old.read_text()))
        self.assertIsNone(cf.load_document(old)["trigger_gain_code"])
        for bad in (0, 64, "1", True, 1.5):
            data = json.loads(path.read_text())
            data["trigger_gain_code"] = bad
            with self.assertRaises(cf.CalibrationFileError):
                cf.validate_document(data)

    def test_pedestals_round_trip_and_old_files(self):
        from radioroc.data.pedestals import compute_pedestals
        ps = compute_pedestals([{"channel": 6, "hg": 90 + i, "lg": 80} for i in range(6)])
        path = cf.save_document(self.tmp / "p.json", _doc(pedestals=ps))
        self.assertEqual(json.loads(path.read_text())["pedestals"], ps.to_dict())
        self.assertEqual(cf.load_document(path)["pedestals"], ps)
        old = cf.save_document(self.tmp / "o.json", _doc())
        self.assertNotIn("pedestals", json.loads(old.read_text()))
        self.assertIsNone(cf.load_document(old)["pedestals"])
        data = json.loads(path.read_text())
        data["pedestals"] = {"schema_version": 1, "channels": {"99": {}}}
        with self.assertRaises(cf.CalibrationFileError):
            cf.validate_document(data)

    def test_no_trims(self):
        path = cf.save_document(self.tmp / "a.json", _doc())
        self.assertIsNone(cf.load_document(path)["autocalibration"])

    def test_bad_documents(self):
        mutations = [
            {"schema_version": 2}, {"channels": "4"}, {"channels": [64]},
            {"operating_threshold_dac": 2000}, {"operating_threshold_dac": True},
            {"auto_triggers": "yes"}, {"note": 3},
            {"autocalibration": {"trim_kind": "T1", "trims": {"4": 64}}},
            {"autocalibration": {"trim_kind": "T3", "trims": {"4": 1}}},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                d = _doc()
                d.update(mutation)
                path = self.tmp / "b.json"
                path.write_text(json.dumps(d))
                with self.assertRaises(cf.CalibrationFileError):
                    cf.load_document(path)

    def test_unreadable_files(self):
        (self.tmp / "x.json").write_text("{not json")
        (self.tmp / "y.json").write_text("[1]")
        for name in ("x.json", "y.json", "missing.json"):
            with self.subTest(name=name), self.assertRaises(cf.CalibrationFileError):
                cf.load_document(self.tmp / name)

    def test_find_trims(self):
        found, _ = cf.find_autocalibration_trims(self._run())
        self.assertEqual(found["trims"], {"4": 31, "5": 28})
        self.assertEqual(found["trim_kind"], "T1")

    def test_find_trims_t2_missing_and_unverified(self):
        self.assertEqual(cf.find_autocalibration_trims(self._run(t1=False))[0]["trim_kind"], "T2")
        found, reason = cf.find_autocalibration_trims(self.tmp / "nope")
        self.assertIsNone(found)
        self.assertTrue(reason)
        found, reason = cf.find_autocalibration_trims(self._run(cal="unverified"))
        self.assertIsNone(found)
        self.assertIn("not completed and verified", reason)

    def test_find_trims_newest_under_root(self):
        self._run()
        found, _ = cf.find_autocalibration_trims(None, self.tmp)
        self.assertEqual(found["run_directory"], str(self.tmp / "run"))
        self.assertIsNone(cf.find_autocalibration_trims(None, self.tmp / "none")[0])

    def test_reapply_operation(self):
        op = cf.build_reapply_operation({"trim_kind": "T2", "trims": {4: 3}})
        self.assertEqual(op.t2_calibration_dac_values, {4: 3})
        self.assertIsNone(op.t1_calibration_dac_values)
        op.validate()


if __name__ == "__main__":
    unittest.main()
