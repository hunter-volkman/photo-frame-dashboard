# Humblestead PF1006: investigation report, ADB not yet enabled

One unit, investigated on 2026-10-15/16. Stock network ADB refused the connection;
no successful frame SD boot, frame backup, root access or firmware modification
has been demonstrated.
This records an unconfirmed device, not a working unlock procedure.

## Unit and observations

| Item | Evidence |
| --- | --- |
| Retail listing | [Humblestead, Amazon US B0BJDR9G3X](https://www.amazon.com/dp/B0BJDR9G3X); advertised as 10.1-inch, 1280 × 800, 32 GB |
| About model | `PF1006`, reported by the owner |
| About firmware | `YHK.F-null-A33-1001-D1024-PF1006-46-DL-OS-AM.0.20240910`, transcribed by the owner |
| AiMOR version | `6.0.26`, reported by the owner; the startup screen also showed `V6.0.26` |
| Setup | Owner completed the stock setup and reached System Settings → About |
| Ports | Owner confirms an SD card slot and reports no visible USB connector; slot format and complete port inventory not yet verified |
| Host | Apple silicon Mac, macOS 26.6.2, Android platform-tools 37.0.1 installed through Homebrew |
| Network ADB | `adb connect <frame-ip>:5555` returned `Connection refused`; `adb devices -l` listed no devices |
| USB ADB | Not tested; no usable connector identified |
| SoC | Allwinner A33 **inferred from the firmware string**, not confirmed by a chip query, shell or board inspection |
| Android, RAM, storage | Unverified. AiMOR's version is not the Android version; `D1024` and the advertised 32 GB are not measurements |
| Partitions, boot hash, root | Unknown; no storage read or shell access yet |

The network test establishes that ADB was not accessible on TCP 5555 at that
time. It does not establish whether `adbd` is installed, whether a hidden setting
can start it, or whether the frame can boot from SD.

## Why the PF1007L instructions are not yet applicable

The existing [SD-card route](allwinner-a33-sdcard-adb-wifi.md) is a useful starting
point for research, but its supported model and firmware do not match this unit.
Its U-Boot configuration assumes particular DRAM settings and eMMC wiring; its
scripts assume particular MMC device numbers, partition locations and boot-image
contents. These are not established for PF1006.

Do not run its apply/restore scripts on PF1006, copy its partition offsets into a
new writer, or edit its hash guard to accept this firmware. Even the dump build
has board-specific assumptions: an SD slot and an `A33` firmware string alone
do not validate that payload. A diagnostic payload can avoid internal-storage
writes while still needing compatible DRAM and pin configuration.

## Hardware references and experimental tooling

The manufacturer's 2022 [model-difference filing](https://fccid.io/2AW9M-PORTRAIT/Letter/Model-Difference-5791964)
lists PF1006 and PF1006PLUS under FCC ID `2AW9M-PORTRAIT`. The corresponding
[internal photographs](https://apps.fcc.gov/eas/GetApplicationAttachment.html?id=5791961)
show an Allwinner-branded processor, an AXP223 power-management chip, and four
Samsung K4B2G1646F memory packages. That photographed board also has USB-A and
mini-USB connectors, unlike the owner's current port report. Its identity,
wiring and memory configuration must not be assigned to this unit without
further evidence.

A separate [draft PF1006 V43 report (#151)](https://github.com/wesbos/photo-frame-dashboard/pull/151)
describes a USB-equipped board on different firmware. It did not use this SD
diagnostic and does not validate this unit or its experimental build profile.

The experimental [PF1006 prefix probe](../scripts/pf1006-probe/README.md) uses a
separate build and unique script name. It adds non-SD storage write/erase guards,
rejects persistent eMMC configuration changes, checks for at least 256 MiB of
detected RAM before loading U-Boot, and captures only a 4 MiB prefix twice. Its
offline verifier checks the expected build token, size, matching read hashes,
SD readback status and filler. It does not enable ADB or make a full backup.

Host tests exercise the patched C refusal paths and synthetic output corruption.
They do not establish SD boot or electrical compatibility. The build still starts
from another board's DRAM, pin and regulator settings. No successful probe run on
this frame has been recorded.

On 2026-10-15 the complete image cross-built on the Apple silicon Mac using
GCC 16.2.0 and binutils 2.47. The resulting ARM executable and packaged artifacts
passed the host checks, including the independent Allwinner SPL checksum and
legacy script CRC. The 43 Python tests and both C block-API variants passed.
Those results establish a buildable diagnostic candidate, not device support.

On 2026-10-16 the macOS card helper completed its first real card preparation:
a SanDisk Ultra PLUS SDXC UHS-I 64 GB card, measured at 63,864,569,856 bytes.
The card used MBR/FAT32 with the partition at 16 MiB. Bootloader and script
readback passed, the saved post-format 4 MiB card-prefix backup verified, and the
card was ejected successfully. The result of the single owner-approved frame
boot attempt is still pending; no frame capture, frame backup or ADB access has
been verified.

## Next evidence to collect

1. Record the slot type, power connector and every external port. Check the stock
   menus for an ADB/developer option without changing firmware or resetting the
   frame. Keep photographs and logs containing identifiers private.
2. After the single approved SD boot attempt, collect the probe's status and
   prefix with the helper. Its success conditions require two matching reads and
   verified card output. Treat DRAM configuration and MMC mapping as unconfirmed
   until there is hardware evidence; a dark screen
   alone proves nothing. Follow the [repository rules](../README.md#rules-we-learned-the-hard-way)
   for the specific payload and card preparation.
3. If consistent storage reads work, derive the partition map from this unit and
   make a verified backup. Record exact sizes and SHA-256 values, reject filler,
   and compare independent re-reads. Keep a second copy. A 2 GiB prefix dump is
   not a full-device backup and may omit different partitions on this model.
4. Inspect this unit's boot image and init configuration offline to determine how
   `adbd` starts and whether host-key authentication is supported. Only then design
   a PF1006-specific patch and restore path with guards based on this unit's
   verified layout and original image. No such patch is available in this report.
5. To claim support, record the actual write/readback result, authenticated ADB
   connection, shell identity, Android properties, and behavior after a cold boot.
   Test that another host key is rejected before calling network ADB protected.

Publish sanitized observations and boot-image hashes, not whole-device dumps,
whole-device hashes, vendor APKs, credentials, serials or network identifiers.
Failed tests should remain in this report alongside any eventual working route.
