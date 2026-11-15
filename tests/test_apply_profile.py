import hashlib
import json
import stat
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apply_profile import (apply_iksshd_to_files, apply_profile, check_layout, disk_size, ensure_partition_device,
                           expand_partitions,
                           provision_identity, stable_partition_device, upgrade_boot)


class ApplyProfileTests(unittest.TestCase):
    def test_growth_uses_stable_device_for_both_filesystem_tools(self):
        commands = []
        with patch("apply_profile.check_layout", return_value="deadbeef"), \
             patch("apply_profile.os.stat", return_value=SimpleNamespace(st_mode=stat.S_IFBLK)), \
             patch("apply_profile.stable_partition_device",
                   return_value=nullcontext("/tmp/ikuai-stable/vda6")), \
             patch("apply_profile.run", side_effect=lambda *args, **_kwargs: commands.append(args)):
            expand_partitions("/dev/vda", 20_000_000)
        self.assertIn(("e2fsck", "-fy", "/tmp/ikuai-stable/vda6"), commands)
        self.assertIn(("resize2fs", "/tmp/ikuai-stable/vda6"), commands)
        self.assertNotIn(("resize2fs", "/dev/vda6"), commands)

    def test_rescue_populates_partition_device_after_table_reread(self):
        with patch("apply_profile.Path.is_block_device", side_effect=[False, True]), \
             patch("apply_profile.run") as run:
            ensure_partition_device("/dev/vda6")
            run.assert_called_once_with("mdev", "-s")

    def test_missing_partition_device_stops_before_resize(self):
        with patch("apply_profile.Path.is_block_device", return_value=False), \
             patch("apply_profile.run") as run:
            with self.assertRaisesRegex(RuntimeError, "partition device"):
                ensure_partition_device("/dev/vda6")
            run.assert_called_once_with("mdev", "-s")

    def test_bad_image_digest_does_not_modify_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            disk = Path(tmp) / "disk.raw"
            disk.write_bytes(b"unchanged" + bytes(1015))
            profile = Path(tmp) / "profile.json"
            profile.write_text(json.dumps({"disk_basename": "disk.raw",
                                           "raw_sha256": "0" * 64}))
            before = disk.read_bytes()
            with patch("apply_profile.IMAGE_BYTES", 1024):
                with self.assertRaisesRegex(ValueError, "SHA-256"):
                    apply_profile(str(disk), str(profile))
            self.assertEqual(disk.read_bytes(), before)

    def test_rescue_creates_unique_identity_after_verified_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            disk = Path(tmp) / "disk.raw"
            with disk.open("wb") as handle:
                handle.seek(104448 * 512)
                handle.write(b"www.ikuai8.com\0\0" + bytes(16) + b"\1\0\0\0")
            provision_identity(str(disk))
            with disk.open("rb") as handle:
                handle.seek(104448 * 512 + 16)
                first = handle.read(16)
            self.assertNotEqual(first, bytes(16))
            with self.assertRaises(ValueError):
                provision_identity(str(disk))

    def test_bios_image_profile_and_growth(self):
        source = Path("/tmp/ikuai-release/ikuai-3.7.16-bios.raw")
        if not source.exists():
            self.skipTest("BIOS image build not available")
        with tempfile.TemporaryDirectory(prefix="ikuai-apply-test-") as directory:
            disk = Path(directory) / "test.raw"
            subprocess.run(["cp", "--reflink=auto", "--sparse=always", source, disk], check=True)
            disk.open("r+b").close()
            with disk.open("r+b") as handle:
                handle.truncate(9 * 1024**3)
            with source.open("rb") as handle:
                source_hash = hashlib.file_digest(handle, "sha256").hexdigest()
            profile = {
                "disk_basename": disk.name,
                "raw_sha256": source_hash,
                "network": {"mac": "52:54:00:aa:bb:cc", "mode": "static",
                            "address": "192.168.9.10", "prefix": 24, "gateway": "192.168.9.1"},
                "web_password_md5": "a" * 32,
            }
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps(profile))
            result = apply_profile(str(disk), str(path))
            self.assertEqual(result["sectors"], 9 * 1024**3 // 512)
            table = json.loads(subprocess.check_output(["/sbin/sfdisk", "-J", disk]))["partitiontable"]
            self.assertEqual(table["partitions"][5]["size"], result["sectors"] - 8_609_792)
            part = Path(directory) / "config.ext4"
            db = Path(directory) / "config.db"
            subprocess.run(["dd", f"if={disk}", f"of={part}", "bs=512", "skip=114688",
                            "count=102400", "status=none"], check=True)
            subprocess.run(["/sbin/debugfs", "-R", f"dump /ikuai/config.db {db}", str(part)], check=True)
            con = sqlite3.connect(db)
            self.assertEqual(con.execute("SELECT bandif, internet, gateway FROM wan_config WHERE name='wan1'").fetchone(),
                             ("52:54:00:aa:bb:cc", 0, "192.168.9.1"))
            self.assertEqual(con.execute("SELECT open_wanweb,open_sshd,force_https,http_port,https_port FROM remote_control WHERE id=1").fetchone(), (1, 1, 0, 88, 448))
            self.assertEqual(con.execute("SELECT passwd FROM webuser WHERE username='admin'").fetchone()[0], "a" * 32)
            self.assertEqual(con.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            con.close()

    def test_apply_iksshd_to_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            passwd = Path(tmp) / "passwd"
            shadow = Path(tmp) / "shadow"
            passwd.write_text("root:x:0:0:root:/root:/bin/bash\n")
            shadow.write_text("root:*:19000:0:99999:7:::\n")
            apply_iksshd_to_files(passwd, shadow)
            self.assertIn("iksshd:x:0:0:passwd:/root:/bin/ash", passwd.read_text())
            self.assertIn("iksshd:$1$sanjin16$gGSuGogZ6g5njXAnlRyaN1:20158:0:99999:7:::", shadow.read_text())

    def test_upgrade_boot_bios(self):
        with tempfile.TemporaryDirectory() as tmp:
            disk = Path(tmp) / "disk.img"
            boot = Path(tmp) / "boot.ext2"
            disk.write_bytes(bytes(102400 * 512 + 2048 * 512))
            boot.write_bytes(b"BOOT3726" + bytes(102400 * 512 - 8))
            upgrade_boot(str(disk), str(boot), "bios")
            with open(disk, "rb") as f:
                f.seek(2048 * 512)
                self.assertEqual(f.read(8), b"BOOT3726")


if __name__ == "__main__":
    unittest.main()
