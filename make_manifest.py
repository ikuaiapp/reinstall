"""Verify local BIOS/UEFI images and create a GitHub Release manifest."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path


RAW_SIZE = 8 * 1024**3
IDENTITY_OFFSET = 104448 * 512 + 16
ASSET_LIMIT = 2 * 1024**3


def digest(stream):
    result = hashlib.sha256()
    size = 0
    for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
        size += len(block)
        result.update(block)
    return result.hexdigest(), size


def image_entry(prefix, mode):
    raw = Path(f"{prefix}.raw")
    compressed = Path(f"{prefix}.raw.gz")
    if compressed.name not in (f"ikuai-3.7.16-{mode}.raw.gz", f"ikuai-3.7.26-{mode}.raw.gz") or not raw.is_file() or not compressed.is_file():
        raise ValueError(f"missing or incorrectly named {mode} image")
    expected_name = compressed.name
    if raw.stat().st_size != RAW_SIZE or compressed.stat().st_size >= ASSET_LIMIT:
        raise ValueError(f"{mode} image size is outside the supported range")
    with raw.open("rb") as source:
        source.seek(IDENTITY_OFFSET)
        if source.read(16) != bytes(16):
            raise ValueError(f"{mode} image contains a device identity")
        source.seek(0)
        raw_hash, raw_size = digest(source)
    with compressed.open("rb") as source:
        compressed_hash, _ = digest(source)
    with gzip.open(compressed, "rb") as source:
        unpacked_hash, unpacked_size = digest(source)
    if (raw_hash, raw_size) != (unpacked_hash, unpacked_size):
        raise ValueError(f"{mode} gzip does not match the raw disk")
    return {"filename": expected_name, "sha256": compressed_hash,
            "raw_sha256": raw_hash}


def create_manifest(bios_prefix, uefi_prefix, output, boot_payload=None):
    output = Path(output)
    if output.exists():
        raise ValueError("refusing to overwrite an existing manifest")
    result = {"format": "ikuai-cloud-v1",
              "images": {"bios": image_entry(bios_prefix, "bios"),
                         "uefi": image_entry(uefi_prefix, "uefi")}}
    if boot_payload and Path(boot_payload).is_file():
        bp = Path(boot_payload)
        with bp.open("rb") as f:
            bp_hash = hashlib.sha256(f.read()).hexdigest()
        result["upgrade"] = {
            "boot_payload": {
                "filename": bp.name,
                "sha256": bp_hash,
                "target_version": "3.7.26"
            }
        }
    payload = (json.dumps(result, indent=2, sort_keys=True) + "\n").encode("ascii")
    output.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bios-prefix", required=True)
    parser.add_argument("--uefi-prefix", required=True)
    parser.add_argument("--boot-payload", help="optional 3.7.26 boot payload")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(create_manifest(args.bios_prefix, args.uefi_prefix, args.output, args.boot_payload))
