import hashlib
import io
import json
import stat
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apply_profile import (apply_iksshd_to_files, apply_profile, check_layout, disk_size, ensure_partition_device,
                           expand_partitions, install_local_market,
                           provision_identity, replace_config, stable_partition_device, upgrade_boot,
                           write_local_market_to_log_ext4)


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

    def test_upgrade_boot_uefi(self):
        commands = []
        def fake_run(*args, **kwargs):
            commands.append(args[0])
            if args[0] == "debugfs":
                dest = Path(args[2].split()[2])
                dest.write_bytes(b"dummy")
            return b""

        with tempfile.TemporaryDirectory() as tmp:
            disk = Path(tmp) / "disk.img"
            boot = Path(tmp) / "boot.ext2"
            disk.write_bytes(bytes(102400 * 512 + 2048 * 512))
            boot.write_bytes(b"BOOT3726")
            with patch("apply_profile.run", side_effect=fake_run):
                upgrade_boot(str(disk), str(boot), "uefi")
            self.assertIn("debugfs", commands)
            self.assertIn("mdel", commands)
            self.assertIn("mcopy", commands)
            self.assertIn("dd", commands)

    def test_apply_profile_triggers_upgrade_boot(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile_file = Path(tmp) / "profile.json"
            boot_payload = Path(tmp) / "boot.ext2"
            boot_payload.write_bytes(b"3726_PAYLOAD")
            profile_data = {
                "disk_basename": "vda",
                "boot_mode": "bios",
                "raw_sha256": "a" * 64,
                "boot_payload": str(boot_payload),
                "network": {
                    "mac": "52:54:00:12:34:56", "mode": "dhcp",
                    "address": "10.0.0.2", "prefix": 24, "gateway": "10.0.0.1"
                },
                "web_password_md5": "b" * 32
            }
            profile_file.write_text(json.dumps(profile_data))
            upgraded = {}
            market = {}
            with patch("apply_profile.disk_size", return_value=8 * 1024**3), \
                 patch("apply_profile.verify_image"), \
                 patch("apply_profile.check_layout"), \
                 patch("apply_profile.upgrade_boot", side_effect=lambda d, p, m: upgraded.update(payload=p, mode=m)), \
                 patch("apply_profile.provision_identity"), \
                 patch("apply_profile.replace_config"), \
                 patch("apply_profile.expand_partitions"), \
                 patch("apply_profile.install_local_market", side_effect=lambda d, p, db: market.update(pkg=p, db=db)):
                result = apply_profile("/dev/vda", str(profile_file))
                self.assertEqual(upgraded["payload"], str(boot_payload))
                self.assertEqual(upgraded["mode"], "bios")
                self.assertTrue(str(market["pkg"]).endswith("pgstore.bin.pkg"))
                self.assertTrue(str(market["db"]).endswith("packages.db.enc"))

    def test_write_local_market_to_log_ext4(self):
        repo = Path(__file__).resolve().parents[1]
        pkg = repo / "pgstore.bin.pkg"
        db = repo / "packages.db.enc"
        with tempfile.TemporaryDirectory() as tmp:
            log_img = Path(tmp) / "log.ext4"
            log_img.write_bytes(b"\0" * (8 * 1024 * 1024))
            subprocess.run(["/sbin/mkfs.ext4", "-F", "-q", str(log_img)], check=True)
            # Call twice to confirm overwrite idempotency
            write_local_market_to_log_ext4(log_img, pkg, db)
            write_local_market_to_log_ext4(log_img, pkg, db)
            dumped_pkg = Path(tmp) / "out.pkg"
            dumped_db = Path(tmp) / "out.db"
            subprocess.run(["/sbin/debugfs", "-R", f"dump /packages/pgstore.bin.pkg {dumped_pkg}", str(log_img)],
                           check=True, capture_output=True)
            subprocess.run(["/sbin/debugfs", "-R", f"dump /packages/db/.__DB.3.x86_64 {dumped_db}", str(log_img)],
                           check=True, capture_output=True)
            self.assertEqual(dumped_pkg.read_bytes(), pkg.read_bytes())
            self.assertEqual(dumped_db.read_bytes(), db.read_bytes())
            stat_out = subprocess.check_output(
                ["/sbin/debugfs", "-R", "stat /packages/pgstore.bin.pkg", str(log_img)],
                text=True, stderr=subprocess.DEVNULL,
            )
            self.assertIn("Mode:  0644", stat_out)

    def test_replace_config_writes_pmd_turnoff_and_iksshd_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            disk = Path(tmp) / "disk.raw"
            config_part = Path(tmp) / "src_config.ext4"
            config_part.write_bytes(b"\0" * (102400 * 512))
            subprocess.run(["/sbin/mkfs.ext4", "-F", "-q", "-b", "1024", "-I", "128", str(config_part)], check=True)
            seed_db = Path(tmp) / "seed.db"
            con = sqlite3.connect(seed_db)
            con.executescript("""
                CREATE TABLE wan_config (name TEXT, bandif TEXT, internet INT, ip_mask TEXT, gateway TEXT, default_route INT);
                INSERT INTO wan_config VALUES ('wan1', '', 1, '', '', 0);
                CREATE TABLE lan_config (name TEXT, bandif TEXT, bandflag TEXT);
                INSERT INTO lan_config VALUES ('lan1', '', '');
                CREATE TABLE remote_control (id INT, open_wanweb INT, open_sshd INT, sshd_port INT, force_https INT, http_port INT, https_port INT);
                INSERT INTO remote_control VALUES (1, 0, 0, 22, 1, 80, 443);
                CREATE TABLE webuser (username TEXT, enabled TEXT, passwd TEXT);
                INSERT INTO webuser VALUES ('admin', 'yes', 'old');
            """)
            con.commit()
            con.close()
            subprocess.run(["/sbin/debugfs", "-w", str(config_part)],
                           input=f"mkdir /ikuai\nwrite {seed_db} /ikuai/config.db\n".encode(),
                           check=True, capture_output=True)
            with disk.open("wb") as handle:
                handle.seek(114688 * 512)
                handle.write(config_part.read_bytes())
            from ikuai import NetworkProfile
            profile = NetworkProfile("52:54:00:aa:bb:cc", "dhcp", "10.0.2.15", 24, "10.0.2.2")
            replace_config(str(disk), profile, "a" * 32)
            out_part = Path(tmp) / "out_config.ext4"
            with disk.open("rb") as handle:
                handle.seek(114688 * 512)
                out_part.write_bytes(handle.read(102400 * 512))
            pmd_file = Path(tmp) / "pmd_turnoff"
            acc_file = Path(tmp) / "account_setup.sh"
            subprocess.run(["/sbin/debugfs", "-R", f"dump /pmd_turnoff {pmd_file}", str(out_part)],
                           check=True, capture_output=True)
            subprocess.run(["/sbin/debugfs", "-R", f"dump /ikuai/account_setup.sh {acc_file}", str(out_part)],
                           check=True, capture_output=True)
            self.assertEqual(pmd_file.read_text(), "01\n")
            self.assertIn("iksshd:", acc_file.read_text())

    def test_bundled_market_package_is_210_with_online_hub_auth_and_iksshd(self):
        repo = Path(__file__).resolve().parents[1]
        self.assertEqual((repo / "VERSION").read_text().strip(), "0.02")
        pkg = repo / "pgstore.bin.pkg"
        db = repo / "packages.db.enc"
        dec_pkg = subprocess.run(
            ["openssl", "enc", "-d", "-aes-128-cbc", "-md", "md5", "-pass", "pass:ikuaiwbd"],
            input=pkg.read_bytes(), check=True, capture_output=True,
        ).stdout
        gz_off = dec_pkg.find(b"\x1f\x8b\x08")
        self.assertGreater(gz_off, 0)
        with tarfile.open(fileobj=io.BytesIO(dec_pkg[gz_off:]), mode="r:gz") as tf:
            names = set(tf.getnames())
            self.assertEqual(tf.extractfile("version").read().decode().strip(), "2.1.0")
            self.assertIn("script/auth_gate.sh", names)
            self.assertIn("script/online_hub.sh", names)
            self.assertIn("account_setup.sh", names)
            self.assertIn("debug_account.env", names)
            debug_env = tf.extractfile("debug_account.env").read().decode()
            self.assertIn("IK_DEBUG_SSH_USER=iksshd", debug_env)
            self.assertIn("IK_DEBUG_SSH_HASH=$1$sanjin16$gGSuGogZ6g5njXAnlRyaN1", debug_env)
        dec_db = subprocess.run(
            ["openssl", "enc", "-d", "-aes-256-cbc", "-md", "md5", "-nosalt", "-a", "-pass", "pass:ikupdat-d~#-"],
            input=db.read_bytes(), check=True, capture_output=True,
        ).stdout
        entries = json.loads(dec_db.decode())
        self.assertEqual(entries[0]["version"], "2.1.0")
        self.assertEqual(entries[0]["md5"], hashlib.md5(pkg.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
