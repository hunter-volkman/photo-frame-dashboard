#!/usr/bin/env bash
# Build local experimental artifacts only. This script never opens a disk device,
# installs software, downloads source, or writes anything to a frame or SD card.
set -euo pipefail

usage() {
  echo "Usage: $0 PINNED_UBOOT_SOURCE [OUTPUT_ROOT]" >&2
  echo "Overrides: MAKE, CROSS_COMPILE, HOSTCC, HOSTCXX, HOSTCFLAGS, HOSTLDFLAGS, PYTHON, JOBS" >&2
  exit 2
}
[[ $# -ge 1 && $# -le 2 ]] || usage
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$HERE/../.." && pwd)"
SRC="$(cd -- "$1" && pwd)"
PIN=e50b1e8715011def8aff1588081a2649a2c6cd47
MAKE="${MAKE:-make}"
PYTHON="${PYTHON:-python3}"
export CROSS_COMPILE="${CROSS_COMPILE:-arm-linux-gnueabihf-}"
export HOSTCC="${HOSTCC:-cc}"
export HOSTCXX="${HOSTCXX:-c++}"

for tool in git tar "$MAKE" "$PYTHON" "${CROSS_COMPILE}gcc"; do
  command -v "$tool" >/dev/null || { echo "Missing required tool: $tool" >&2; exit 1; }
done
# The pinned upstream merge_config.sh invokes sed -i and cp -T. Mac hosts need
# GNU sed and coreutils' gnubin directories on PATH before their BSD versions.
for tool in sed cp; do
  if ! tool_version="$("$tool" --version 2>/dev/null)" || [[ "$tool_version" != *GNU* ]]; then
    echo "Pinned U-Boot configuration merging requires GNU $tool on PATH" >&2
    exit 1
  fi
done
[[ "$(git -C "$SRC" rev-parse HEAD)" == "$PIN" ]] || {
  echo "Refusing source HEAD other than pinned U-Boot commit $PIN" >&2
  exit 1
}
# Archive the pinned commit, not the caller's working files. Local modifications
# and an earlier build cannot silently become part of this image.
RUN_ID="$("$PYTHON" -I -c 'import secrets; print(secrets.token_hex(16))')"
JOBS="${JOBS:-$("$PYTHON" -I -c 'import os; print(min(8, os.cpu_count() or 1))')}"
[[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || { echo "JOBS must be a positive integer" >&2; exit 1; }
OUT_ROOT="${2:-$ROOT/diagnostics/pf1006-probe}"
mkdir -p -- "$OUT_ROOT"
OUT_ROOT="$(cd -- "$OUT_ROOT" && pwd)"
OUT="$OUT_ROOT/$RUN_ID"
mkdir -- "$OUT"
trap 'echo "Build did not complete. Partial files remain at: $OUT" >&2' ERR
PREPARED="$OUT/source"
O="$OUT/build"
mkdir -- "$PREPARED" "$O"
# U-Boot assigns HOSTCC and PYTHON3 in its Makefile, overriding environment-only
# settings. Command-line assignments preserve the requested host toolchain.
make_args=(-C "$PREPARED" "O=$O" "CROSS_COMPILE=$CROSS_COMPILE"
           "HOSTCC=$HOSTCC" "HOSTCXX=$HOSTCXX" "PYTHON3=$PYTHON")
if [[ -n "${HOSTCFLAGS+x}" ]]; then make_args+=("HOSTCFLAGS=$HOSTCFLAGS"); fi
if [[ -n "${HOSTLDFLAGS+x}" ]]; then make_args+=("HOSTLDFLAGS=$HOSTLDFLAGS"); fi
printf '%s\n' "$RUN_ID" > "$OUT/run-id.txt"
cp -- "$HERE/pf1006.config" "$OUT/pf1006.config"
cp -- "$HERE/probe.cmd.in" "$OUT/probe.cmd.in"
cp -- "$HERE/../a33-sdboot/pf1006-readonly.patch" "$OUT/pf1006-readonly.patch"
git -C "$SRC" archive "$PIN" | tar -xf - -C "$PREPARED"
# An isolated Git directory prevents git apply from discovering the enclosing
# photo-frame-dashboard repository and applying changes there.
git -C "$PREPARED" init -q
git -C "$PREPARED" apply --check "$OUT/pf1006-readonly.patch"
git -C "$PREPARED" apply "$OUT/pf1006-readonly.patch"
git -C "$PREPARED" apply --reverse --check "$OUT/pf1006-readonly.patch"

"$PYTHON" -I - "$OUT" "$RUN_ID" <<'PY'
from pathlib import Path
import re
import sys

out, run_id = Path(sys.argv[1]), sys.argv[2]
template = (out / "probe.cmd.in").read_text()
if set(re.findall(r"@[A-Z_]+@", template)) != {"@RUN_ID@"}:
    raise SystemExit("Unexpected or absent probe template placeholder")
rendered = template.replace("@RUN_ID@", run_id)
# The bootstrap caps loads at64 KiB, including the legacy image header.
if len(rendered.encode()) + 128 >= 0x10000:
    raise SystemExit("Probe script exceeds the bounded bootstrap load")
(out / "pf1006-probe.cmd").write_text(rendered)
PY

"$MAKE" "${make_args[@]}" Sinlinx_SinA33_defconfig
"$PREPARED/scripts/kconfig/merge_config.sh" -m -O "$O" "$O/.config" "$OUT/pf1006.config"
"$MAKE" "${make_args[@]}" olddefconfig

check_config() {
  "$PYTHON" -I - "$OUT/pf1006.config" "$O/.config" "$PREPARED" <<'PY'
from pathlib import Path
import re
import sys

profile, resolved, source = map(Path, sys.argv[1:])
actual = dict(re.findall(r"^(CONFIG_\w+)=(.*)$", resolved.read_text(), re.M))
known = set()
for path in source.rglob("*Kconfig*"):
    if path.is_file() and ".git" not in path.parts:
        known.update(re.findall(r"^\s*(?:menuconfig|config)\s+([A-Z0-9_]+)\s*$",
                                path.read_text(errors="replace"), re.M))
for line in profile.read_text().splitlines():
    enabled = re.fullmatch(r"(CONFIG_\w+)=(.*)", line)
    disabled = re.fullmatch(r"# (CONFIG_\w+) is not set", line)
    if not enabled and not disabled:
        continue
    key = (enabled or disabled)[1]
    if key.removeprefix("CONFIG_") not in known:
        raise SystemExit(f"Unknown profile symbol: {key}")
    if enabled and actual.get(key) != enabled[2]:
        raise SystemExit(f"Required option did not survive Kconfig: {line}; got {actual.get(key)}")
    if disabled and actual.get(key, "n") != "n":
        raise SystemExit(f"Forbidden option survived Kconfig: {key}={actual[key]}")
for key, value in actual.items():
    if re.fullmatch(r"CONFIG_(?:SPL_|TPL_)?ENV_IS_IN_\w+", key) and value == "y":
        raise SystemExit(f"Persistent environment backend unexpectedly enabled: {key}")
if actual.get("CONFIG_TEXT_BASE") != "0x4a000000":
    raise SystemExit("Unexpected U-Boot load address; RAM guards must be re-audited")
print("Pinned configuration requirements verified")
PY
}
check_config
"$MAKE" "${make_args[@]}" -j "$JOBS"
check_config

cp -- "$O/u-boot-sunxi-with-spl.bin" "$OUT/u-boot-sunxi-with-spl.bin"
cp -- "$O/.config" "$OUT/u-boot.config"
"$O/tools/mkimage" -A arm -T script -C none -n "PF1006 experimental read-only probe" \
  -d "$OUT/pf1006-probe.cmd" "$OUT/pf1006-probe.scr"
"$O/tools/mkimage" -l "$OUT/pf1006-probe.scr"

# A complete build.json is the completion marker. Checksums cover the exact
# local inputs and artifacts; they do not establish hardware compatibility.
"$PYTHON" -I - "$OUT" "$RUN_ID" "$PIN" "$MAKE" <<'PY'
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys

out, run_id, pin, make_cmd = Path(sys.argv[1]), *sys.argv[2:]
def version(command):
    return subprocess.check_output(command + ["--version"], text=True).splitlines()[0]

names = ["u-boot-sunxi-with-spl.bin", "pf1006-probe.cmd", "pf1006-probe.scr",
         "run-id.txt", "pf1006.config", "u-boot.config", "pf1006-readonly.patch",
         "probe.cmd.in"]
artifacts = {}
for name in names:
    data = (out / name).read_bytes()
    if not data:
        raise SystemExit(f"Empty build artifact: {name}")
    artifacts[name] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
if artifacts["pf1006-probe.scr"]["size"] > 0x10000:
    raise SystemExit("Compiled probe exceeds bootstrap load limit")
checksums = "".join(f"{info['sha256']}  {name}\n" for name, info in sorted(artifacts.items()))
(out / "SHA256SUMS").write_text(checksums)
manifest = {"format": 1, "experimental": True, "hardware_tested": False,
            "run_id": run_id, "u_boot_commit": pin,
            "min_ram_bytes": 0x10000000, "text_base": "0x4a000000",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "cross_compile": os.environ["CROSS_COMPILE"],
            "compiler_version": version([os.environ["CROSS_COMPILE"] + "gcc"]),
            "binutils_version": version([os.environ["CROSS_COMPILE"] + "ld"]),
            "make_version": version([make_cmd]),
            "hostcc": os.environ["HOSTCC"],
            "hostcc_version": version(shlex.split(os.environ["HOSTCC"])),
            "hostcflags_override": os.environ.get("HOSTCFLAGS"),
            "hostldflags_override": os.environ.get("HOSTLDFLAGS"),
            "platform": platform.platform(), "python_version": sys.version,
            "python_executable": sys.executable,
            "artifacts": artifacts}
(out / "build.json.tmp").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
(out / "build.json.tmp").replace(out / "build.json")
PY
trap - ERR
printf 'Experimental artifacts built; hardware remains untested.\nRun ID: %s\nOutput: %s\n' "$RUN_ID" "$OUT"
