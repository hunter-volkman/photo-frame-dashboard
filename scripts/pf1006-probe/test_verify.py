"""Host-only tests. Synthetic captures do not validate hardware compatibility."""

import contextlib
import hashlib
import importlib.util
import io
import json
import struct
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("pf1006_verify", Path(__file__).with_name("verify.py"))
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)

RUN_ID = "0123456789abcdef0123456789abcdef"
OTHER_RUN_ID = "abcdef0123456789abcdef0123456789"


class ProbeVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = bytearray(bytes(range(256)) * (VERIFY.PREFIX_BYTES // 256))
        data[8196:8204] = b"eGON.BT0"
        struct.pack_into("<I", data, 8192 + 16, 32768)
        data[1048576:1048584] = b"ANDROID!"
        data[2097152:2097156] = b"\xd0\x0d\xfe\xed"
        struct.pack_into(">I", data, 2097152 + 4, 4096)
        cls.payload = bytes(data)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.card = Path(self.temp.name)
        self.fields = {
            "format": "1", "run_id": RUN_ID, "stage": "finished",
            "result": "VERIFIED_4MIB_PREFIX", "start_sector": "0",
            "sector_count": "0x2000", "read_bytes": "0x400000",
            "read1_sha256": hashlib.sha256(self.payload).hexdigest(),
            "read2_sha256": hashlib.sha256(self.payload).hexdigest(),
            "reread": "equal", "card_verify": "equal", "media": "mmc",
            "extcsd_status": "available", "extcsd_rev": "8",
            "extcsd_sec0": "0", "extcsd_sec1": "a0",
            "extcsd_sec2": "d5", "extcsd_sec3": "1",
        }
        self.write_capture()

    def write_capture(self, data=None):
        (self.card / VERIFY.PREFIX_NAME).write_bytes(self.payload if data is None else data)
        self.write_status()

    def write_status(self):
        content = "".join("pf1006_{}={}\n".format(k, v) for k, v in sorted(self.fields.items()))
        (self.card / VERIFY.STATUS_NAME).write_bytes(content.encode("ascii") + b"\0")

    def assert_rejected(self, message):
        with self.assertRaisesRegex(VERIFY.VerificationError, message):
            VERIFY.verify(self.card, RUN_ID)

    def test_valid_capture_and_signature_candidates(self):
        result = VERIFY.verify(self.card, RUN_ID)
        self.assertEqual(result["bytes"], 4194304)
        self.assertEqual(result["ext_csd_capacity_bytes"], 15758000128)
        candidates = {item["kind"]: item for item in result["signature_candidates"]}
        self.assertEqual(candidates["eGON boot0"]["header_offset"], 8192)
        self.assertEqual(candidates["eGON boot0"]["declared_bytes"], 32768)
        self.assertEqual(candidates["Android boot"]["magic_offset"], 1048576)
        self.assertEqual(candidates["FDT"]["declared_bytes"], 4096)

    def test_corrupted_prefix(self):
        data = bytearray(self.payload)
        data[2048] ^= 1
        self.write_capture(bytes(data))
        self.assert_rejected("SHA-256 differs")

    def test_truncated_prefix(self):
        self.write_capture(self.payload[:-1])
        self.assert_rejected("exactly 4 MiB")

    def test_oversized_prefix(self):
        self.write_capture(self.payload + b"\0")
        self.assert_rejected("exactly 4 MiB")

    def test_filler_even_when_hashes_match_and_run_is_unaligned(self):
        data = bytearray(self.payload)
        data[123:123 + 65536] = b"\xcc" * 65536
        digest = hashlib.sha256(data).hexdigest()
        self.fields.update(read1_sha256=digest, read2_sha256=digest)
        self.write_capture(bytes(data))
        self.assert_rejected("0xCC filler")

    def test_two_device_reads_must_match(self):
        self.fields["read2_sha256"] = "0" * 64
        self.write_status()
        self.assert_rejected("independent read hashes differ")

    def test_incomplete_and_failed_capture_status(self):
        for field, value in (("stage", "reading"), ("result", "FAIL_SECOND_READ"),
                             ("reread", "not_run"), ("card_verify", "not_run"),
                             ("media", "unconfirmed")):
            with self.subTest(field=field):
                original = self.fields[field]
                self.fields[field] = value
                self.write_status()
                self.assert_rejected("unexpected or incomplete")
                self.fields[field] = original

    def test_rejects_stale_build_token(self):
        self.fields["run_id"] = OTHER_RUN_ID
        self.write_status()
        self.assert_rejected("run ID mismatch")

    def test_malformed_or_duplicated_status(self):
        status = self.card / VERIFY.STATUS_NAME
        good = status.read_bytes()
        for corrupt in (good[:-1], good + b"garbage", good[:-1] + b"pf1006_format=1\n\0"):
            with self.subTest(corrupt_bytes=len(corrupt)):
                status.write_bytes(corrupt)
                self.assert_rejected("terminator|duplicate")

    def test_missing_status_field(self):
        del self.fields["read_bytes"]
        self.write_status()
        self.assert_rejected("missing or unexpected")

    def test_optional_capacity_unknown(self):
        self.fields["extcsd_status"] = "unavailable"
        for key in list(self.fields):
            if key.startswith("extcsd_") and key != "extcsd_status":
                self.fields[key] = "unknown"
        self.write_status()
        self.assertIsNone(VERIFY.verify(self.card, RUN_ID)["ext_csd_capacity_bytes"])

    def test_bad_capacity_byte(self):
        self.fields["extcsd_sec3"] = "100"
        self.write_status()
        self.assert_rejected("invalid EXT_CSD byte")

    def test_declared_small_capacity(self):
        self.fields.update(extcsd_sec0="1", extcsd_sec1="0", extcsd_sec2="0", extcsd_sec3="0")
        self.write_status()
        self.assert_rejected("capacity is smaller")

    def test_boundary_signature_does_not_parse_past_end(self):
        data = b"eGON.BT0" + b"x" * 8 + b"\xd0\x0d\xfe\xed"
        findings = VERIFY.signature_candidates(data)
        self.assertEqual(len(findings), 2)
        self.assertNotIn("header_offset", findings[0])
        self.assertNotIn("declared_bytes", findings[1])

    def test_cli_compares_two_verified_captures(self):
        prior = self.card / "prior"
        prior.mkdir()
        (prior / VERIFY.PREFIX_NAME).write_bytes(self.payload)
        status = (self.card / VERIFY.STATUS_NAME).read_bytes().replace(RUN_ID.encode(), OTHER_RUN_ID.encode())
        (prior / VERIFY.STATUS_NAME).write_bytes(status)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = VERIFY.main([str(self.card), "--run-id", RUN_ID, "--compare", str(prior),
                              "--compare-run-id", OTHER_RUN_ID, "--json"])
        self.assertEqual(rc, 0)
        self.assertIn("independent_capture", json.loads(output.getvalue()))

        changed = bytearray(self.payload)
        changed[512] ^= 1
        digest = hashlib.sha256(changed).hexdigest().encode()
        status = status.replace(self.fields["read1_sha256"].encode(), digest)
        (prior / VERIFY.PREFIX_NAME).write_bytes(changed)
        (prior / VERIFY.STATUS_NAME).write_bytes(status)
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            rc = VERIFY.main([str(self.card), "--run-id", RUN_ID, "--compare", str(prior),
                              "--compare-run-id", OTHER_RUN_ID])
        self.assertEqual(rc, 1)
        self.assertIn("independent capture differs", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
