#!/usr/bin/env python3
"""Verify an experimental PF1006 probe's 4 MiB prefix, without modifying files.

This is not a backup verifier or a PF1006 compatibility test. Header signatures
are candidates only; none establishes the partition layout or permits flashing.
Keep prefix data private: it can contain firmware and unit-specific information.
Python 3.9+, standard library only.
"""

import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

PREFIX_BYTES = 4 * 1024 * 1024
STATUS_NAME = "pf1006-probe-status.txt"
PREFIX_NAME = "pf1006-probe.bin"
STATUS_KEYS = {
    "format", "run_id", "stage", "result", "start_sector", "sector_count",
    "read_bytes", "read1_sha256", "read2_sha256", "reread", "card_verify",
    "media", "extcsd_status", "extcsd_rev", "extcsd_sec0", "extcsd_sec1",
    "extcsd_sec2", "extcsd_sec3",
}


class VerificationError(ValueError):
    """Probe output is incomplete, inconsistent, or unsuitable as evidence."""


def parse_status(path):
    if path.stat().st_size > 16384:
        raise VerificationError("status exceeds 16 KiB")
    raw = path.read_bytes()
    if not raw.endswith(b"\0") or b"\0" in raw[:-1]:
        raise VerificationError("status must have exactly one final NUL terminator")
    try:
        text = raw[:-1].decode("ascii")
    except UnicodeDecodeError as exc:
        raise VerificationError("status is not ASCII") from exc
    if not text.endswith("\n"):
        raise VerificationError("status has an incomplete final line")
    fields = {}
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if not separator or not key.startswith("pf1006_"):
            raise VerificationError("unexpected status line")
        name = key[len("pf1006_"):]
        if name in fields:
            raise VerificationError("duplicate status field: " + name)
        fields[name] = value
    if set(fields) != STATUS_KEYS:
        raise VerificationError("missing or unexpected status fields")
    return fields


def signature_candidates(data):
    findings = []
    for name, magic in (("eGON boot0", b"eGON.BT0"),
                        ("Android boot", b"ANDROID!"),
                        ("FDT", b"\xd0\x0d\xfe\xed")):
        offset = 0
        count = 0
        while True:
            offset = data.find(magic, offset)
            if offset < 0:
                break
            item = {"kind": name, "magic_offset": offset}
            if name == "eGON boot0" and offset >= 4 and offset + 16 <= len(data):
                start = offset - 4
                size = struct.unpack_from("<I", data, start + 16)[0]
                item.update(header_offset=start, declared_bytes=size,
                            declared_range_in_prefix=20 <= size <= len(data) - start)
            elif name == "FDT" and offset + 8 <= len(data):
                size = struct.unpack_from(">I", data, offset + 4)[0]
                item.update(declared_bytes=size,
                            declared_range_in_prefix=40 <= size <= len(data) - offset)
            findings.append(item)
            count += 1
            if count >= 64:
                findings.append({"kind": name, "more_candidates_omitted": True})
                break
            offset += len(magic)
    return findings


def verify(card, expected_run_id):
    if not re.fullmatch(r"[0-9a-f]{32}", expected_run_id):
        raise VerificationError("expected run ID must be 32 lowercase hexadecimal characters")
    card = Path(card)
    fields = parse_status(card / STATUS_NAME)
    if fields["run_id"] != expected_run_id:
        raise VerificationError("run ID mismatch: possible output from an earlier build")
    required = {
        "format": "1", "stage": "finished", "result": "VERIFIED_4MIB_PREFIX",
        "start_sector": "0", "sector_count": "0x2000", "read_bytes": "0x400000",
        "reread": "equal", "card_verify": "equal", "media": "mmc",
    }
    for key, value in required.items():
        if fields[key] != value:
            raise VerificationError("unexpected or incomplete " + key + ": " + fields[key])
    first_hash = fields["read1_sha256"]
    if not re.fullmatch(r"[0-9a-f]{64}", first_hash):
        raise VerificationError("invalid SHA-256 in status")
    if fields["read2_sha256"] != first_hash:
        raise VerificationError("independent read hashes differ")
    prefix = card / PREFIX_NAME
    if prefix.stat().st_size != PREFIX_BYTES:
        raise VerificationError("prefix must be exactly 4 MiB")
    data = prefix.read_bytes()
    if len(data) != PREFIX_BYTES:
        raise VerificationError("prefix changed while reading")
    if hashlib.sha256(data).hexdigest() != first_hash:
        raise VerificationError("prefix SHA-256 differs from the on-frame reads")
    if b"\xcc" * 65536 in data:
        raise VerificationError("prefix contains a 64 KiB run of 0xCC filler")
    if data in (b"\0" * PREFIX_BYTES, b"\xff" * PREFIX_BYTES):
        raise VerificationError("prefix is entirely zero or 0xFF; not useful evidence")

    capacity = None
    revision = None
    if fields["extcsd_status"] == "available":
        values = []
        for key in ("extcsd_rev", "extcsd_sec0", "extcsd_sec1", "extcsd_sec2", "extcsd_sec3"):
            if not re.fullmatch(r"[0-9a-f]{1,2}", fields[key]):
                raise VerificationError("invalid EXT_CSD byte: " + key)
            values.append(int(fields[key], 16))
        revision = values[0]
        sectors = int.from_bytes(bytes(values[1:]), "little")
        # SEC_COUNT can be zero on small/older devices. Do not invent a capacity.
        if sectors:
            capacity = sectors * 512
            if capacity < PREFIX_BYTES:
                raise VerificationError("reported capacity is smaller than the prefix")
    elif fields["extcsd_status"] != "unavailable":
        raise VerificationError("unexpected EXT_CSD status")

    return {
        "result": "verified_prefix_only", "run_id": expected_run_id,
        "bytes": len(data), "sha256": first_hash,
        "media": "MMC (not SD), according to U-Boot register check",
        "ext_csd_revision": revision, "ext_csd_capacity_bytes": capacity,
        "signature_candidates": signature_candidates(data),
        "limits": "4 MiB prefix only; not a full backup, unlock, or verified partition map",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("card", type=Path, help="directory containing both probe output files")
    parser.add_argument("--run-id", required=True, help="expected token from this build")
    parser.add_argument("--compare", type=Path, help="independent prior capture to compare")
    parser.add_argument("--compare-run-id", help="expected token for the prior capture")
    parser.add_argument("--json", action="store_true", help="print structured metadata")
    args = parser.parse_args(argv)
    if bool(args.compare) != bool(args.compare_run_id):
        parser.error("--compare and --compare-run-id must be supplied together")
    try:
        report = verify(args.card, args.run_id)
        if args.compare:
            other = verify(args.compare, args.compare_run_id)
            if report["sha256"] != other["sha256"]:
                raise VerificationError("independent capture differs")
            report["independent_capture"] = "same prefix hash; provenance must be checked separately"
    except (OSError, VerificationError) as exc:
        print("FAIL: " + str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("PASS: 4 MiB prefix matches two on-frame reads and SD readback.")
        print("SHA-256: " + report["sha256"])
        if report["ext_csd_capacity_bytes"] is not None:
            print("EXT_CSD user-area capacity: {} bytes".format(report["ext_csd_capacity_bytes"]))
        for candidate in report["signature_candidates"]:
            print("Signature candidate (not a validated header): " + json.dumps(candidate))
        if args.compare:
            print("Independent capture has the same prefix hash; confirm capture provenance separately.")
        print(report["limits"] + ".")
        print("Keep the binary and any device-identifying output private.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
