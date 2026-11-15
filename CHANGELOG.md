# Changelog

All notable changes to this project will be documented in this file.

## Strict Versioning and Release Tracking Rule
This repository follows a strict incremental release versioning policy:
- The base migration starts at version **0.01**.
- Each subsequent cloud vendor modification, adaptation, and verification increments the version number strictly by **0.01** (e.g., 0.01 -> 0.02 -> 0.03).
- The `VERSION` file at the repository root serves as the single source of truth for the current version string.
- Every release must have a corresponding Git tag `v<VERSION>` (e.g., `v0.01`).

---

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
- Preserved `iksshd` account setup script across provisioning and profile application routines.

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
