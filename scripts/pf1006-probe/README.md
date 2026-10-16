# Experimental PF1006 SD probe

**Not tested on hardware. This does not enable ADB or provide a flash/restore
procedure.** The first goal is to learn whether a reviewed SD-booted U-Boot build
can read consistent bytes from this unit's internal MMC device. The model and
firmware alone do not validate its DRAM configuration or pin assignments.

`probe.cmd.in` is source for a U-Boot script. It must be packaged as
`pf1006-probe.scr`, never `a33.scr`, and used only with the companion experimental
build's non-SD write/erase guard patch. Do not load it using an arbitrary PF1007L
U-Boot build. This README does not authorize a card erase or a device boot.
Follow the repository's device-write rules and review the concrete build first.

## What it does

- Writes progress to `pf1006-probe-status.txt` on FAT partition `mmc 0:1`.
- Selects `mmc 1` as a candidate internal device. An OCR register read must pass;
  the pinned U-Boot implementation refuses that command on SD media. CID and
  other unique identifiers are not exported.
- Reads sectors 0 through 8191 twice into separate, differently prefilled 4 MiB
  buffers, compares them byte for byte, and records both SHA-256 values.
- Saves `pf1006-probe.bin` on the SD card, then reloads it and verifies its exact
  length and content against the original buffer.
- Optionally records EXT_CSD revision and SEC_COUNT, without inferring capacity
  from the marketing specification. These are register reads, not EXT_CSD writes.
- Writes final status and loops indefinitely; it never starts Android or falls
  through to another boot source. The outer boot command must also halt if script
  loading or execution fails.

The source has no internal-storage write command, partition offset, or patch
application step. The companion guard build blocks non-SD block writes/erases
and restricts EXT_CSD switching. **This is not a promise of zero hardware state
changes:** booting still initializes DRAM, powers/configures controllers and
changes volatile MMC bus timing, width and user-area selection. Those operations
can fail on an incompatible board. The safeguards must be reviewed in the build,
not inferred from the script alone.

The inherited A33 profile uses the AXP221/AXP223 driver. Its SPL initialization
actively applies these settings; they are **not measurements from PF1006**:

| PMIC output | Inherited setting |
| --- | --- |
| DCDC1 | 3,000 mV; also enables the DCDC1 switch output |
| DCDC2 | 1,100 mV |
| DCDC3 | 1,200 mV |
| DCDC5 | 1,500 mV |
| ALDO1 and ALDO3 | 3,000 mV each |
| ALDO2 | 2,500 mV |
| DCDC4, DLDO1–4 and ELDO1–3 | Disabled: their configured value is zero |

The guard halts if PMIC identification/initialization fails, before the regulator
setters run. It also halts on the first setter error before another setter or
DRAM initialization. Successfully applied settings are not rolled back. A
recognized PMIC does not establish that these voltages suit the connected board.
DRAM remains the inherited 456 MHz / ZQ 15291 experiment, and the successful
initialization path subsequently requests a 1,008 MHz CPU clock. No PF1006-specific
voltage changes have been inferred or added.

Buffers are at `0x42000000` and `0x42400000`, status at `0x43000000`, and the
script at `0x43100000`. The companion build requires at least **256 MiB RAM**:
its U-Boot load address is `0x4a000000`, already beyond a 128 MiB board's memory.
SPL must stop below that minimum before loading U-Boot, and the outer boot command
must check the detected size again before loading the script. The smaller probe
buffers do not establish that a board with less RAM can boot this build.

## Building the probe

Run these commands from the repository root. Obtain the exact U-Boot source once:

```sh
git clone --depth 1 --branch v2025.10 https://github.com/u-boot/u-boot.git diagnostics/uboot-pf1006-source
git -C diagnostics/uboot-pf1006-source checkout --detach e50b1e8715011def8aff1588081a2649a2c6cd47
```

`build.sh` refuses any other source HEAD. It archives that commit into a new
per-run directory, applies the reviewed guard patch there, merges the profile,
and verifies every requested configuration setting before and after compilation.
It does not incorporate uncommitted source changes. In particular, Sunxi forces
`USE_PREBOOT=y`, so the profile explicitly makes `PREBOOT` empty and verifies that
`PREBOOT_DEFINED` is off. Kernel handoff, PSCI, network, USB and persistent
environment support are excluded from this diagnostic.

On Linux, the base prerequisites are GNU Make, GCC for the host, an ARM cross GCC
and binutils, Git, GNU sed/coreutils, tar, bison, flex, SWIG, OpenSSL development
headers, pkg-config, and Python with development headers, `venv` and setuptools.
The following base recipe assumes a Python 3.9–3.11 venv with setuptools available;
the verified Mac environment used setuptools 58.0.4. The requirements file pins
the additional pyelftools dependency and accepts only its recorded SHA-256 hashes.

```sh
python3 -m venv diagnostics/pf1006-build-venv
diagnostics/pf1006-build-venv/bin/python -I -c 'import setuptools; print(setuptools.__version__)'
diagnostics/pf1006-build-venv/bin/python -m pip install --require-hashes -r scripts/pf1006-probe/build-requirements.txt
MAKE=make CROSS_COMPILE=arm-linux-gnueabihf- \
  PYTHON="$PWD/diagnostics/pf1006-build-venv/bin/python" \
  scripts/pf1006-probe/build.sh diagnostics/uboot-pf1006-source
```

For SWIG 4.5, the pinned U-Boot pylibfdt interface still uses two removed Python 2
compatibility names. Supply
`HOSTCFLAGS='-DPyInt_AsLong=PyLong_AsLong -DPyString_FromString=PyUnicode_FromString'`
to the build command. These flags affect host tools only. The Linux recipe was
not executed during the validation recorded below.

### Validated native Apple Silicon build

The full cross-build completed on macOS 26.6.2 using ARM GCC 16.2.0, GNU binutils
2.47.20260726, GNU Make 4.4.1, Apple clang 21.0.0, SWIG 4.5.1, Python 3.9.6 and
setuptools 58.0.4. The Homebrew `make` formula supplies the `gmake` command.
With Homebrew and Xcode Command Line Tools already available, the dependencies
and build recipe used were:

```sh
brew install arm-none-eabi-gcc arm-none-eabi-binutils make bison swig openssl@3 dtc pkgconf coreutils gnu-sed
```

The build requires GNU sed and GNU cp: the pinned upstream configuration merge
script uses `sed -i` and `cp -T`. This host also required the installed macOS 26.5
SDK explicitly; the 27 SDK produced a host linker/architecture mismatch. Use a
compatible installed SDK rather than silently substituting a newer one. The
following path is the SDK used for the successful build:

```sh
/Library/Developer/CommandLineTools/usr/bin/python3 -m venv diagnostics/pf1006-build-venv
diagnostics/pf1006-build-venv/bin/python -I -c 'import setuptools; print(setuptools.__version__)'
diagnostics/pf1006-build-venv/bin/python -m pip install --require-hashes -r scripts/pf1006-probe/build-requirements.txt

PF1006_BREW_PREFIX="$(brew --prefix)"
export PATH="$PF1006_BREW_PREFIX/opt/gnu-sed/libexec/gnubin:$PF1006_BREW_PREFIX/opt/coreutils/libexec/gnubin:$PF1006_BREW_PREFIX/opt/bison/bin:$PF1006_BREW_PREFIX/bin:$PATH"
export SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk
export PKG_CONFIG_PATH="$PF1006_BREW_PREFIX/opt/openssl@3/lib/pkgconfig"
export HOSTCFLAGS="-DPyInt_AsLong=PyLong_AsLong -DPyString_FromString=PyUnicode_FromString -I$PF1006_BREW_PREFIX/opt/openssl@3/include"
export HOSTLDFLAGS="-Wl,-undefined,dynamic_lookup -L$PF1006_BREW_PREFIX/opt/openssl@3/lib"
MAKE=gmake CROSS_COMPILE=arm-none-eabi- HOSTCC=clang HOSTCXX=clang++ \
  PYTHON="$PWD/diagnostics/pf1006-build-venv/bin/python" \
  scripts/pf1006-probe/build.sh diagnostics/uboot-pf1006-source
```

The Python aliases allow the pinned pylibfdt wrapper to compile with SWIG 4.5;
macOS dynamic lookup allows its Python extension to link. OpenSSL include/library
paths point to Homebrew's installation. These are host build flags, not ARM
firmware flags. The helper passes host compiler and Python overrides directly to
Make, so upstream defaults cannot silently replace them.

Every invocation creates a fresh run ID under `diagnostics/pf1006-probe/` (or a
supplied second argument). `build.json` is written only after a successful build.
It records the pinned commit, tool versions, host flags and hashes for eight
artifacts: the combined SPL/U-Boot binary, rendered script, packaged script, run
ID, profile, resolved configuration, guard patch and source template.
`SHA256SUMS` covers those same artifacts. The files and source/build directories
remain together for review. Fresh run IDs and timestamps mean repeated builds
are not expected to have identical hashes.

Validation on 2026-10-16 (UTC) produced a 325,400-byte combined image. The ELF was ARM
32-bit with entry `0x4a000000`; the card helper accepted its manifest, source and
configuration snapshots, script CRCs, independent SPL checksum, size and guard
markers. **This verifies the build and host checks only: no frame boot or hardware
compatibility test has been performed.** Building does not prepare or write a card.

## Host verification

The build replaces `@RUN_ID@` with a fresh 32-character lowercase hexadecimal
token and records it locally. Supply that expected token from the build record,
not one copied from the card's output:

```sh
python3 -I scripts/pf1006-probe/verify.py /path/to/capture --run-id BUILD_TOKEN
```

The verifier reads files only. It requires complete success status, the expected
run ID, matching hashes from both reads, successful SD readback, and an exactly
4 MiB file. It rejects truncation, corruption, inconsistent metadata, and 64 KiB
runs of `0xCC` filler. It reports eGON boot0, Android boot and FDT signature
**candidates**, without extracting or modifying anything. Signature matches can
be false positives; they are not a partition map or permission to flash.

Rebuild with a fresh run ID for a new attempt and archive previous output before
preparing the card. A token distinguishes builds, not individual power cycles:
reusing the same build with old result files can make an old success look current.
A missing/unfinished status or a dark screen is not a successful probe.

To compare two separately verified captures:

```sh
python3 -I scripts/pf1006-probe/verify.py /path/to/new --run-id NEW_TOKEN \
  --compare /path/to/prior --compare-run-id PRIOR_TOKEN
```

Equal hashes prove equal file content, not that the captures came from independent
boots. Record that provenance separately. Keep both binary captures private.
Only the first 4 MiB is read; it may not contain the Android boot partition and
is not a complete backup. No persistent change should be designed from this
prefix alone.

## macOS card helper

`card-macos.py` defaults to a **read-only plan**. It accepts a completed per-run
build directory, an explicit whole-disk identifier, and the exact card byte count.
It never chooses a disk automatically. The initial implementation accepts only
external, removable, physical USB media with 512-byte sectors and a capacity of
4–256 GB. This is the helper's guard, not a statement about every usable reader.

Find the current card identity and exact size each time it is inserted:

```sh
diskutil list external physical
diskutil info diskN
```

Replace `BUILD_DIR`, `diskN`, and `EXACT_BYTES` with observed values:

```sh
python3 -I scripts/pf1006-probe/card-macos.py BUILD_DIR diskN EXACT_BYTES
```

Before any disk mutation, the helper checks the pinned U-Boot commit, complete
manifest and SHA-256 files, reviewed source/profile/guard snapshots, resolved
configuration, rendered run ID, legacy script CRCs and source content, SPL header
and its independent little-endian additive checksum,
boot image size, and guard/unique-script markers in the binary. These checks catch
mixed or stale artifacts; marker presence does not prove hardware compatibility.
An `a33.scr` in the build or on the prepared card is refused.

For an explicitly selected spare card whose contents can be erased:

```sh
sudo python3 -I scripts/pf1006-probe/card-macos.py BUILD_DIR diskN EXACT_BYTES --action prepare
```

Preparation requires the exact confirmation `ERASE diskN`. It rechecks identity,
formats MBR/FAT32 with a 16 MB gap, saves and verifies the **post-format** first
4 MiB, writes only the unique probe script and the bootloader at byte 8192,
verifies readback, and ejects. The bootloader must end before 1 MiB. Saved card
identity and backup stay under ignored `diagnostics/pf1006-probe/cards/RUN_ID/`.
Interrupted preparation is retained for diagnosis; it is not silently retried.

**One physical frame boot per newly prepared build.** Each prepare consumes its
build token and refuses reuse. After that one attempt, collect the result. A new
attempt needs a fresh build token and a newly prepared card. The helper cannot
detect an unreported second power cycle: if all status writes failed, an earlier
success could still be on the card. Never treat such reused output as new evidence.

After the single frame boot attempt, reinsert the card in the Mac, recheck its
disk number and size, and collect without `sudo`:

```sh
python3 -I scripts/pf1006-probe/card-macos.py BUILD_DIR diskN EXACT_BYTES --action collect
```

Collection checks saved card identity, the original build, the script, and the
complete capture against the build token. It mounts read-only if a mount is needed,
copies only validated results into ignored `backups/pf1006-probe/RUN_ID/`, verifies
the saved copy, and ejects. It refuses existing destinations. Raw firmware bytes
and the card's identity remain private. Collection does not deliberately change
card files; an existing macOS read/write mount can still cause OS metadata writes.
An absent or failed result is diagnostic
evidence to inspect, not a reason to bypass a check or apply a firmware patch.

To remove this probe's bootloader from a successfully prepared card:

```sh
sudo python3 -I scripts/pf1006-probe/card-macos.py BUILD_DIR diskN EXACT_BYTES --action remove
```

Removal requires `REMOVE BOOTLOADER diskN`. It verifies the saved identity,
post-format backup hash, and two reads of the expected current boot area before
restoring that area and verifying the result. It leaves card files intact and
**does not recover the contents erased by preparation**. Keep the original build
directory and private card state until removal; collection and removal can use
that original build even if this checkout's source files have since changed.
Removal also handles an interruption after the complete bootloader write but
before the final preparation-state save, provided the current prefix exactly
matches the expected installed image. A partial or changed prefix is refused.

## Offline tests

Python 3.9 or later, standard library only:

```sh
python3 -I scripts/pf1006-probe/test_verify.py
python3 -I scripts/pf1006-probe/test_card_macos.py
```

These tests use synthetic captures to exercise corruption, truncation, filler,
stale/unfinished status, capacity decoding and independent-capture comparison.
Card-helper tests use synthetic builds, regular temporary files and a fake
`diskutil` interface to exercise disk guards, source/script tampering, stale
results, refused overwrites, and prepare/collect/restore behavior. No disk device
is opened by the tests. They do not exercise U-Boot or prove PF1006 hardware
compatibility.
