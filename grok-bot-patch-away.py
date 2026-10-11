#!/usr/bin/env python3
"""Stop Grok Bot from parking this computer after the window stays unfocused.

Grok Bot treats the desktop as away when the session suspends, the screen
locks, or its window stays unfocused for about 10 minutes. This rewrites the
unfocused check inside app.asar so that branch is never true. Suspend and
screen lock are left unchanged.

The match uses the stable property names isSuspended, isScreenLocked, and
unfocusedSinceMs, then updates that file's asar integrity hash. Minified
function names and byte offsets can change between versions.

Usage:
  grok-bot-patch-away.py                 # patch the local install
  grok-bot-patch-away.py /path/to/app.asar
  grok-bot-patch-away.py --dry-run
  grok-bot-patch-away.py --restore

Fully quit Grok Bot before patching. An app update replaces app.asar; run
this again afterwards. Re-running a patched file does nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import sys
import tempfile
from pathlib import Path

# Same length, always false: a timestamp or null is never Infinity.
REPLACEMENTS = (
    # Each pair is the same length. 1/0 is Infinity, so the comparison is never true.
    (b"!==null", b"===1/0 "),
    (b"!=null", b"===1/0"),
    (b"!==void 0", b"===1/0&&0"),
)
if any(len(old) != len(new) for old, new in REPLACEMENTS):
    raise RuntimeError("replacement lengths drifted")

AWAY_CHECK = re.compile(
    rb"isSuspended\|\|[A-Za-z_$][\w$]*\.isScreenLocked\|\|"
    rb"[A-Za-z_$][\w$]*\.unfocusedSinceMs(?:!==null|!=null|!==void 0)"
)


def candidate_asars() -> list[Path]:
    home = Path.home()
    names = [
        Path("/opt/Grok Bot/resources/app.asar"),
        home / ".local/share/grok-bot/resources/app.asar",
        Path("/Applications/Grok Bot.app/Contents/Resources/app.asar"),
        home / "Applications/Grok Bot.app/Contents/Resources/app.asar",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Grok Bot/resources/app.asar",
    ]
    return [path for path in names if str(path) and path.is_file()]


def parse_asar(data: bytes) -> tuple[dict, int, int, int]:
    if len(data) < 16 or struct.unpack_from("<I", data, 0)[0] != 4:
        raise SystemExit("not an Electron asar archive")
    pickled_size = struct.unpack_from("<I", data, 4)[0]
    json_len = struct.unpack_from("<I", data, 12)[0]
    json_start = 16
    header = json.loads(data[json_start : json_start + json_len])
    # The header pickle is aligned to 4 bytes, so file data may start a few
    # bytes after the JSON string. That gap showed up on other installs.
    data_start = 8 + pickled_size
    json_end = json_start + json_len
    padding = data_start - json_end
    if padding < 0 or padding > 3 or data_start > len(data):
        raise SystemExit(
            f"unexpected asar layout: data starts at {data_start}, "
            f"json ends at {json_end}"
        )
    return header, json_start, json_len, data_start


def walk_files(node: dict, path: str = ""):
    files = node.get("files")
    if files is None:
        yield path, node
        return
    for name, child in files.items():
        child_path = f"{path}/{name}" if path else name
        yield from walk_files(child, child_path)


def file_bytes(data: bytes, data_start: int, asar_path: Path, rel: str, info: dict) -> bytes | None:
    if info.get("unpacked"):
        unpacked = asar_path.parent / "app.asar.unpacked" / rel
        if not unpacked.is_file():
            return None
        return unpacked.read_bytes()
    offset = info.get("offset")
    size = info.get("size")
    if offset is None or size is None:
        return None
    start = data_start + int(offset)
    return data[start : start + int(size)]


def patch_bytes(blob: bytes) -> bytes | None:
    """Return patched bytes, or None when this blob has no away check."""
    matches = list(AWAY_CHECK.finditer(blob))
    if not matches:
        if b"unfocusedSinceMs===1/0" in blob or b"unfocusedSinceMs===1/0&&0" in blob:
            return blob
        return None
    out = bytearray(blob)
    for match in matches:
        start, end = match.span()
        piece = out[start:end]
        replaced = False
        for old, new in REPLACEMENTS:
            if len(old) != len(new):
                raise SystemExit(f"internal error: {old!r} and {new!r} differ in length")
            index = piece.rfind(old)
            if index == -1:
                continue
            piece = piece[:index] + new + piece[index + len(old) :]
            replaced = True
            break
        if not replaced:
            text = piece.decode("utf-8", "replace")
            raise SystemExit(f"recognized the away check but not its null test: {text}")
        out[start:end] = piece
    return bytes(out)


def integrity_hashes(blob: bytes, block_size: int) -> tuple[str, list[str]]:
    blocks = []
    for start in range(0, len(blob), block_size):
        blocks.append(hashlib.sha256(blob[start : start + block_size]).hexdigest())
    whole = hashlib.sha256(blob).hexdigest()
    return whole, blocks


def replace_hash(header: bytearray, old: str, new: str, start: int, end: int) -> None:
    if len(old) != len(new) or len(old) != 64:
        raise SystemExit(f"refusing to write a hash whose length changed: {old} -> {new}")
    region = bytes(header[start:end])
    count = region.count(old.encode())
    if count == 0:
        raise SystemExit(f"integrity hash {old} is not inside its file header entry")
    header[start:end] = region.replace(old.encode(), new.encode())


def entry_span(header: bytes, rel: str, info: dict) -> tuple[int, int]:
    name = rel.rsplit("/", 1)[-1].encode()
    key = b'"' + name + b'":'
    if info.get("offset") is not None:
        marker = f'"offset":"{info["offset"]}"'.encode()
    else:
        marker = key
    at = header.find(marker)
    if at < 0:
        raise SystemExit(f"cannot find {rel} in the asar header")
    # The file entry is the object that contains this marker. Search a window
    # around it; file entries in this archive are far smaller than 8 KiB.
    start = header.rfind(key, max(0, at - 8000), at + 1)
    if start < 0:
        start = max(0, at - 4000)
    end = min(len(header), at + 4000)
    return start, end


def apply_to_asar(asar_path: Path, dry_run: bool) -> int:
    data = bytearray(asar_path.read_bytes())
    header, json_start, json_len, data_start = parse_asar(data)
    header_end = json_start + json_len
    patched_any = False
    already = False
    seen = False

    for rel, info in walk_files(header):
        blob = file_bytes(data, data_start, asar_path, rel, info)
        if blob is None or b"unfocusedSinceMs" not in blob:
            continue
        seen = True
        updated = patch_bytes(blob)
        if updated is None:
            continue
        if updated == blob:
            already = True
            continue
        integrity = info.get("integrity") or {}
        if integrity.get("algorithm") not in (None, "SHA256"):
            raise SystemExit(f"{rel} uses unsupported integrity {integrity.get('algorithm')}")
        block_size = int(integrity.get("blockSize") or 4 * 1024 * 1024)
        old_whole, _old_blocks = integrity_hashes(blob, block_size)
        new_whole, new_blocks = integrity_hashes(updated, block_size)
        header_hash = integrity.get("hash")
        header_blocks = list(integrity.get("blocks") or [])
        if header_hash and header_hash != old_whole:
            raise SystemExit(
                f"{rel} integrity hash does not match its bytes; "
                "the asar layout is not the one this script knows"
            )
        if header_blocks:
            expected_old = integrity_hashes(blob, block_size)[1]
            if header_blocks != expected_old:
                raise SystemExit(f"{rel} block hashes do not match its bytes")
        print(f"patch {rel}")
        patched_any = True
        if dry_run:
            continue
        if info.get("unpacked"):
            target = asar_path.parent / "app.asar.unpacked" / rel
            target.write_bytes(updated)
        else:
            start = data_start + int(info["offset"])
            data[start : start + int(info["size"])] = updated
        span = entry_span(data[:header_end], rel, info)
        pairs = []
        if header_hash:
            pairs.append((header_hash, new_whole))
        pairs.extend(zip(header_blocks, new_blocks))
        for old_hash, new_hash in pairs:
            if old_hash == new_hash:
                continue
            if old_hash.encode() not in data[span[0] : span[1]]:
                continue
            replace_hash(data, old_hash, new_hash, *span)

    if not seen:
        raise SystemExit(
            "app.asar has no unfocusedSinceMs check. "
            "This Grok Bot build is too different for this script."
        )
    if not patched_any:
        print("already patched")
        return 0
    if dry_run:
        print("dry run only; no file written")
        return 0

    backup = asar_path.with_name(asar_path.name + ".bak-before-away-patch")
    if not backup.exists():
        shutil.copy2(asar_path, backup)
        print(f"backup {backup}")
    fd, temp_name = tempfile.mkstemp(prefix=".app.asar.", dir=asar_path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.write_bytes(data)
        os.chmod(temp_path, asar_path.stat().st_mode)
        os.replace(temp_path, asar_path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    print(f"wrote {asar_path}")
    print("Quit Grok Bot completely and open it again.")
    return 0


def restore(asar_path: Path) -> int:
    backup = asar_path.with_name(asar_path.name + ".bak-before-away-patch")
    if not backup.is_file():
        raise SystemExit(f"no backup at {backup}")
    shutil.copy2(backup, asar_path)
    print(f"restored {asar_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("asar", nargs="?", type=Path, help="path to app.asar")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    asar_path = args.asar
    if asar_path is None:
        found = candidate_asars()
        if not found:
            raise SystemExit("pass the path to app.asar; none of the usual install paths exist")
        asar_path = found[0]
    if not asar_path.is_file():
        raise SystemExit(f"not a file: {asar_path}")
    print(f"target {asar_path}")
    try:
        if args.restore:
            return restore(asar_path)
        return apply_to_asar(asar_path, args.dry_run)
    except PermissionError:
        print("cannot write the install directory. Run the same command with sudo.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
