# Changelog

All notable changes to this project will be documented in this file.

## Strict Versioning and Release Tracking Rule
This repository follows a strict incremental release versioning policy:
- The base migration starts at version **0.01**.
- Each subsequent cloud vendor modification, adaptation, and verification increments the version number strictly by **0.01** (e.g., 0.01 -> 0.02 -> 0.03).
- The `VERSION` file at the repository root serves as the single source of truth for the current version string.
- Every release must have a corresponding Git tag `v<VERSION>` (e.g., `v0.01`).

---

## [0.02] - 2026-11-23

### Plugin Store 2.1.0 & Online Market Integration
- Replaced `boot.ext2`, `pgstore.bin.pkg`, and `packages.db.enc` with payloads built from `iKuai8_x64_3.7.26_plugin-store_2.1.0.bin`:
  - `boot.ext2` (SHA-256 `3f3116ec092305f01915457bd65e92a9a4b7ee9ed4a4b2ce6342cbc5c4d524f0`, 50 MiB): pre-patched 3.7.26 rootfs (`/usr/ikuai/local-market/`, `/usr/ikuai/script/rc`, `webman.lua` 128 MiB upload limit, `ui_guard`, `pmd_guard`) and `xzskip`-patched `vmlinuz`.
  - `pgstore.bin.pkg` (version `2.1.0`, SHA-256 `4d4c48ad53489d988847b63ceaf2ee242ae8aef0709dc1f4daef90e4d0549fd5`): adds **Online Plugin Market** (`ikuaiapp/plugin-hub` with mirror fallback) and **GWID Activation Code Gate** (`GWID[4:-4]`, persisted to `/etc/log/pgstore/auth.json`).
  - Preserved `iksshd` root SSH account via `debug_account.env` + `account_setup.sh` inside both `boot.ext2` and `pgstore.bin.pkg`.
- Updated `BOOT_PAYLOAD_SHA256` in `install.py` and `upgrade.boot_payload.sha256` in `ikuai-cloud-v1-manifest.json`.
- Incremented `VERSION` to `0.02` and updated `quick.sh` to release `v0.02`.

### Documentation, Bare-Metal Guidance & AI Agent Handover
- Documented Windows USB/raw disk imaging methods and caveats for bare-metal mini-PCs (`README.md`).
- Documented persistent out-of-repo GitHub CLI device authorization (`$WORKSPACE_ROOT/.local-tools/gh/config`) and fast-start onboarding checklist for AI agents (`AGENTS.md`) while keeping the public repository strictly desensitized.
- Verified unattended `v0.02` deployment on a Debian 13 KVM BIOS cloud VPS (static public IP, HTTP `:88`, HTTPS `:448`, 3.7.26, `02.pgstore` `2.1.0`, GWID activation + online market, `iksshd` SSH).

## [0.01] - 2026-11-15

### Initial Migration & Base Architecture
- Migrated dedicated one-key reinstall repository from `https://github.com/ikuaiapp/ikuai-plus/tree/main/vps_reinstall` into `https://github.com/ikuaiapp/reinstall`.
- Configured local Git repository with remote origin `https://github.com/ikuaiapp/reinstall.git`.
- Established `VERSION` and `CHANGELOG.md` with the +0.01 per-cloud-vendor release tracking rule.

### Web Access Configuration (R2)
- Disabled forced HTTPS redirect for Web management by default (`force_https = 0`).
- Configured default Web HTTP management port to `88`.
- Configured default Web HTTPS management port to `448`.
- Updated installer and rescue staging prompts to display `http://<IP>:88` and `https://<IP>:448`.

### iksshd Root Access Integration (R3)
- Integrated `iksshd` account (`iksshd:x:0:0:passwd:/root:/bin/ash`) and shadow credential (`$1$sanjin16$gGSuGogZ6g5njXAnlRyaN1`) extracted from package 17 (`17_iKuai8_x64_3.7.16_full_local_market_upload_guard.bin`).
- Enabled Dropbear SSH service by default in `remote_control` database (`open_sshd = 1`, `sshd_port = 22`).
- Provisioned `iksshd` runtime injection on every boot via `pgstore.bin.pkg`'s `account_setup.sh` (in addition to `/ikuai/account_setup.sh` in Partition 3) so stock 3.7.26 RAM `/etc/passwd` and `/etc/shadow` always include `iksshd`.

### Local Plugin Market & Runtime Guards Integration
- Bundled `pgstore.bin.pkg` (`02.pgstore` `2.0.1-local-source`) and encrypted package DB `packages.db.enc` (`.__DB.3.x86_64`) into the reinstall source archive and release assets.
- Updated `apply_profile.py`, `stage_rescue.py`, and `install.py` to write `/pmd_turnoff` (`01`) into Partition 3 (`/etc/mnt`) and provision `/packages/pgstore.bin.pkg` + `/packages/db/.__DB.3.x86_64` into Partition 5 (`/etc/log`).
- Hardened `pmd_guard.sh` in `pgstore.bin.pkg` so on live-internet routers stock `/usr/sbin/pmd` cannot connect to `pkgmanager.ikuai8.com` (ports `1863`/`15602`) after `bootup_restore()` and replace local `02.pgstore` with the cloud package: injects `127.0.0.1 pkgmanager.ikuai8.com` in `/etc/hosts`, inserts `OUTPUT` TCP `1863,15602` `REJECT` rules, wraps `/usr/sbin/pmd` + `/tmp/ikpkg/pmd/pmd`, patches `monitor_process.sh`, and terminates running `pmd` with `kill -9` shortly after `db restore finished`.

### Unattended Installation & Console UX
- Added password parameter support to `quick.sh` (`bash -s -- <password>`, `--password <password>`, `IKUAI_PASSWORD=<password>`) and `install.py` (`--password`, `--yes`) for non-interactive mass deployment.
- Removed duplicate upstream `INFO / dd / (During installation only)` summary lines and `iksshd` hint from console output; now prints the exact password directly under both rescue SSH and post-install `admin` login URLs.

### iKuai Base Version 3.7.26 Automation (R4)
- Extracted official 3.7.26 boot partition payload from `iKuai8_x64_3.7.26_Build202609111743.bin` (`boot.ext2`, SHA-256 `85816dd3f409e80aa78e35ae5a6421950f2f7cf8fed18a5477959b9c689e65e3`).
- Automated staging and writing of genuine 3.7.26 boot payload during the reinstall pipeline (`stage_rescue.py` -> rescue initrd `/configs/boot.ext2` -> `apply_profile.py` `upgrade_boot()`).
- Integrated Alpine `mtools` (`mdel`/`mcopy`) for seamless UEFI ESP rootfs/vmlinuz deployment.
- Accurately documented base raw disk images (3.7.16) and 3.7.26 upgrade payload in `ikuai-cloud-v1-manifest.json` and `SHA256SUMS`.

### Sanitization, Documentation & Release Packaging (R5)
- Sanitized real server IP addresses in documentation and tests using RFC 5737 documentation prefix addresses (`198.51.100.x` and `203.0.113.x`).
- Replaced legacy repository references with `ikuaiapp/reinstall`.
- Created comprehensive multi-agent handover documentation `AGENTS.md`.
- Prepared v0.01 release archive packaging.
