"""Apply a preflighted VPS profile to an already verified iKuai disk image.

This program is deliberately separate from the downloader. It never writes an
unverified image and never reboots the rescue system.
"""

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from ikuai import NetworkProfile, provision_database


IMAGE_BYTES = 8 * 1024**3
DATA_START = 8_609_792
PARTITION_STARTS = (2048, 104448, 114688, 217088, 219136, DATA_START)
PARTITION_SIZES = (102400, 10240, 102400, 16560128, 8388608, 8167424)
IDENTITY_OFFSET = 104448 * 512

IKSSHD_ACCOUNT = "iksshd:x:0:0:passwd:/root:/bin/ash"
IKSSHD_PASSWORD_HASH = "$1$sanjin16$gGSuGogZ6g5njXAnlRyaN1"
IKSSHD_SHADOW_ENTRY = "iksshd:$1$sanjin16$gGSuGogZ6g5njXAnlRyaN1:20158:0:99999:7:::"


def apply_iksshd_to_files(passwd_file="/etc/passwd", shadow_file="/etc/shadow"):
    passwd_path = Path(passwd_file)
    shadow_path = Path(shadow_file)
    if passwd_path.is_file() and not passwd_path.is_symlink():
        lines = [line for line in passwd_path.read_text().splitlines() if not line.startswith("iksshd:")]
        lines.append(IKSSHD_ACCOUNT)
        passwd_path.write_text("\n".join(lines) + "\n")
    if shadow_path.is_file() and not shadow_path.is_symlink():
        lines = [line for line in shadow_path.read_text().splitlines() if not line.startswith("iksshd:")]
        lines.append(IKSSHD_SHADOW_ENTRY)
        shadow_path.write_text("\n".join(lines) + "\n")


def upgrade_boot(disk, boot_payload, boot_mode="bios"):
    boot_path = Path(boot_payload)
    if not boot_path.is_file():
        raise FileNotFoundError(f"boot payload not found: {boot_path}")
    if boot_mode == "bios":
        run("dd", f"if={boot_path}", f"of={disk}", "bs=512",
            "seek=2048", "count=102400", "conv=notrunc", "status=none")
    elif boot_mode == "uefi":
        with tempfile.TemporaryDirectory(prefix="ikuai-uefi-boot-") as directory:
            part1 = Path(directory) / "esp.fat"
            run("dd", f"if={disk}", f"of={part1}", "bs=512", "skip=2048",
                "count=102400", "status=none")
            rootfs = Path(directory) / "rootfs"
            vmlinuz = Path(directory) / "vmlinuz"
            run("debugfs", "-R", f"dump /boot/rootfs {rootfs}", str(boot_path))
            run("debugfs", "-R", f"dump /boot/vmlinuz {vmlinuz}", str(boot_path))
            run("mdel", "-i", str(part1), "::/boot/rootfs")
            run("mcopy", "-i", str(part1), str(rootfs), "::/boot/rootfs")
            run("mdel", "-i", str(part1), "::/boot/vmlinuz")
            run("mcopy", "-i", str(part1), str(vmlinuz), "::/boot/vmlinuz")
            run("dd", f"if={part1}", f"of={disk}", "bs=512", "seek=2048",
                "count=102400", "conv=notrunc", "status=none")


def run(*args, input_data=None):
    command = args[0]
    if not shutil.which(command) and Path("/sbin", command).exists():
        args = (str(Path("/sbin", command)), *args[1:])
    result = subprocess.run(args, input=input_data, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"{args[0]}: {result.stderr.decode(errors='replace')}")
    return result.stdout


def disk_size(disk):
    if stat.S_ISBLK(os.stat(disk).st_mode):
        if int(run("blockdev", "--getss", disk)) != 512:
            raise ValueError("only 512-byte logical sector disks are supported")
        return int(run("blockdev", "--getsize64", disk))
    return os.stat(disk).st_size


def verify_image(disk, expected):
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("invalid raw image SHA-256")
    digest = hashlib.sha256()
    with open(disk, "rb", buffering=4 * 1024 * 1024) as source:
        remaining = IMAGE_BYTES
        while remaining:
            chunk = source.read(min(4 * 1024 * 1024, remaining))
            if not chunk:
                raise ValueError("disk is shorter than the raw image")
            digest.update(chunk)
            remaining -= len(chunk)
    if digest.hexdigest() != expected:
        raise ValueError("written image does not match the approved SHA-256")


def check_layout(disk):
    data = json.loads(run("sfdisk", "-J", disk))["partitiontable"]
    if data["label"] != "dos" or data.get("sectorsize", 512) != 512:
        raise ValueError("unexpected partition table")
    rows = data["partitions"]
    if len(rows) != 6 or tuple(p["start"] for p in rows) != PARTITION_STARTS:
        raise ValueError("partition layout does not match the tested image")
    if tuple(p["size"] for p in rows) != PARTITION_SIZES:
        raise ValueError("partition sizes do not match the tested image")
    return data["id"]


def disk_partition(disk, number):
    return f"{disk}{'p' if disk[-1].isdigit() else ''}{number}"


def provision_identity(disk):
    with open(disk, "r+b", buffering=0) as handle:
        handle.seek(IDENTITY_OFFSET)
        if handle.read(36) != b"www.ikuai8.com\0\0" + bytes(16) + b"\1\0\0\0":
            raise ValueError("public image identity slot was not blank")
        handle.seek(IDENTITY_OFFSET + 16)
        handle.write(secrets.token_bytes(16))
        handle.flush()
        os.fsync(handle.fileno())


def replace_config(image, profile, password_md5):
    with tempfile.TemporaryDirectory(prefix="ikuai-config-") as directory:
        root = Path(directory)
        part = root / "config.ext4"
        db = root / "config.db"
        run("dd", f"if={image}", f"of={part}", "bs=512", "skip=114688",
            "count=102400", "status=none")
        run("debugfs", "-R", f"dump /ikuai/config.db {db}", str(part))
        provision_database(db, profile, password_md5)
        run("debugfs", "-w", "-R", "rm /ikuai/config.db", str(part))
        output = run("debugfs", "-w", "-R", f"write {db} /ikuai/config.db", str(part))
        if b"Allocated inode:" not in output:
            raise RuntimeError("config.db was not written to partition 3")
        account_script = root / "account_setup.sh"
        account_script.write_text(
            "#!/bin/bash\nset -euo pipefail\n"
            f"grep -q '^iksshd:' /etc/passwd || echo '{IKSSHD_ACCOUNT}' >> /etc/passwd\n"
            f"grep -q '^iksshd:' /etc/shadow || echo '{IKSSHD_SHADOW_ENTRY}' >> /etc/shadow\n"
        )
        run("debugfs", "-w", "-R", f"write {account_script} /ikuai/account_setup.sh", str(part))
        result = subprocess.run((shutil.which("e2fsck") or "/sbin/e2fsck", "-fn", str(part)), capture_output=True)
        if result.returncode not in (0, 1):
            raise RuntimeError("config partition integrity check failed")
        run("dd", f"if={part}", f"of={image}", "bs=512", "seek=114688",
            "conv=notrunc", "status=none")


def ensure_partition_device(partition):
    if Path(partition).is_block_device():
        return
    run("mdev", "-s")
    if not Path(partition).is_block_device():
        raise RuntimeError(f"partition device was not created: {partition}")


@contextmanager
def stable_partition_device(partition):
    name = Path(partition).name
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name) or partition != f"/dev/{name}":
        raise ValueError("unexpected partition device path")
    major_minor = (Path("/sys/class/block") / name / "dev").read_text().strip().split(":")
    if len(major_minor) != 2 or not all(value.isdecimal() for value in major_minor):
        raise RuntimeError("kernel did not expose the expected partition device")
    device_number = os.makedev(int(major_minor[0]), int(major_minor[1]))
    with tempfile.TemporaryDirectory(prefix="ikuai-stable-device-") as directory:
        node = str(Path(directory) / name)
        os.mknod(node, stat.S_IFBLK | 0o600, device_number)
        actual = os.stat(node)
        if not stat.S_ISBLK(actual.st_mode) or actual.st_rdev != device_number:
            raise RuntimeError("temporary partition device does not match the kernel")
        yield node


def expand_partitions(disk, total_sectors):
    if total_sectors < 16_777_216 or total_sectors > 2**32:
        raise ValueError("disk must be between 8 GiB and 2 TiB")
    table_id = check_layout(disk)
    table = (f"label: dos\nlabel-id: {table_id}\nunit: sectors\n\n"
             "start=2048,size=102400,type=83\n"
             "start=104448,size=10240,type=83\n"
             "start=114688,size=102400,type=83\n"
             f"start=217088,size={total_sectors - 217088},type=5\n"
             "start=219136,size=8388608,type=83\n"
             f"start={DATA_START},size={total_sectors - DATA_START},type=83\n")
    run("sfdisk", "--force", disk, input_data=table.encode())
    if stat.S_ISBLK(os.stat(disk).st_mode):
        run("blockdev", "--rereadpt", disk)
        part6 = disk_partition(disk, 6)
        with stable_partition_device(part6) as stable_part6:
            run("e2fsck", "-fy", stable_part6)
            run("resize2fs", stable_part6)
    else:
        with tempfile.TemporaryDirectory(prefix="ikuai-data-") as directory:
            part6 = Path(directory) / "data.ext4"
            run("dd", f"if={disk}", f"of={part6}", "bs=512", f"skip={DATA_START}",
                f"count={PARTITION_SIZES[5]}", "conv=sparse", "status=none")
            os.truncate(part6, (total_sectors - DATA_START) * 512)
            run("e2fsck", "-fy", str(part6))
            run("resize2fs", str(part6))
            run("dd", f"if={part6}", f"of={disk}", "bs=512", f"seek={DATA_START}",
                "conv=notrunc,sparse", "status=none")


def apply_profile(disk, profile_file, boot_payload=None):
    profile = json.loads(Path(profile_file).read_text())
    if Path(disk).name != profile["disk_basename"]:
        raise ValueError("target disk name differs from the preflight selection")
    size = disk_size(disk)
    if size % 512 or size < IMAGE_BYTES or size > 2 * 1024**4:
        raise ValueError("unsupported target disk size")
    verify_image(disk, profile["raw_sha256"])
    check_layout(disk)
    payload_to_use = boot_payload or profile.get("boot_payload")
    if not payload_to_use and Path("/configs/boot.ext2").is_file():
        payload_to_use = "/configs/boot.ext2"
    if payload_to_use and Path(payload_to_use).is_file():
        upgrade_boot(disk, payload_to_use, profile.get("boot_mode", "bios"))
    network = NetworkProfile(**profile["network"])
    provision_identity(disk)
    replace_config(disk, network, profile["web_password_md5"])
    expand_partitions(disk, size // 512)
    return {"disk": disk, "network": profile["network"], "sectors": size // 512}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--disk", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--boot-payload", help="optional 3.7.26 boot payload")
    arguments = parser.parse_args()
    print(json.dumps(apply_profile(arguments.disk, arguments.profile, arguments.boot_payload), indent=2))
