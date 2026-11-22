# Multi-Agent Engineering & Handover Guide (`AGENTS.md`)

This repository (`https://github.com/ikuaiapp/reinstall`) houses the standalone, dedicated one-key reinstall toolchain for deploying **genuine iKuai 3.7.26** on cloud VPS instances (x86_64).
All autonomous and cooperating agents interacting with this repository MUST adhere to the architecture, conventions, security mandates, and versioning rules outlined below.

---

## 1. Architecture Overview & Module Map

The installer operates via a multi-stage pipeline: host preflight -> Alpine RAM rescue OS injection -> disk block write & configuration provisioning -> native iKuai first boot.

```
+---------------------------------------------------------------------------------------+
|  Host Preflight & Validation (install.py, ikuai.py, quick.sh)                         |
|  - Validates CPU arch (x86_64), physical RAM (>= 896 MiB), partition layout, NIC/WAN  |
|  - Interactively prompts / confirms password (or generates 10-char fallback)          |
|  - Downloads release assets, stage_rescue environment                                  |
+------------------------------------------+--------------------------------------------+
                                           |
                                           v
+---------------------------------------------------------------------------------------+
|  Rescue OS Staging & Execution (stage_rescue.py, vendor/reinstall.sh, vendor/trans.sh)|
|  - Patches upstream netboot installer with pinned Alpine 3.24.3 checksums             |
|  - Injects install profile, ikuai.py, apply_profile.py, boot.ext2 into rescue initrd  |
|  - Injects mtools into Alpine rescue environment for UEFI boot payload replacement    |
|  - Modifies GRUB / EFI NVRAM to reboot into Alpine memory rescue OS                   |
+------------------------------------------+--------------------------------------------+
                                           |
                                           v
+---------------------------------------------------------------------------------------+
|  Disk Image Flashing & Partition Customization (trans.sh, apply_profile.py)           |
|  - Downloads / verifies base raw image (3.7.16) and writes to disk block device       |
|  - Automatically deploys 3.7.26 boot payload (/configs/boot.ext2) via upgrade_boot()  |
|  - Generates 16-byte random hardware identity into Partition 2                        |
|  - Injects WAN network profile and Web/SSH ports into Partition 3 (/ikuai/config.db)  |
|  - Writes /pmd_turnoff (01) to Partition 3 and Local Market to Partition 5 (/etc/log) |
|  - Ensures iksshd & Local Plugin Market (02.pgstore) run on every 3.7.26 boot        |
|  - Resizes Partition 6 (data) to consume entire remaining disk space                  |
|  - Reboots directly into genuine iKuai 3.7.26                                         |
+---------------------------------------------------------------------------------------+
```

### Module Inventory
| File / Directory | Purpose |
| :--- | :--- |
| `quick.sh` | Interactive or unattended bootstrap bash script (`curl ... \| bash` or `curl ... \| bash -s -- <password>`). |
| `install.py` | Host preflight validator, disk selector, cloud metadata parser, unattended `--password`/`--yes` support, and rescue staging runner. |
| `stage_rescue.py` | Hooks Alpine 3.24.3 netboot initramfs, modifies host bootloader (GRUB / UEFI). |
| `apply_profile.py` | Executed inside Alpine rescue RAM: applies profile, provisions `config.db` & `/pmd_turnoff` (Part 3), provisions Local Plugin Market (`pgstore.bin.pkg` + `.__DB.3.x86_64`) to Part 5, expands Part 6, and deploys 3.7.26 `boot.ext2`. |
| `pgstore.bin.pkg` | Encrypted iKuai package containing `02.pgstore` (`2.1.0`, from `iKuai8_x64_3.7.26_plugin-store_2.1.0.bin`): Online Plugin Market (`ikuaiapp/plugin-hub`), GWID activation code gate (`GWID[4:-4]`), local `.ipk`/`.fpk` installer, `upload_limit_guard.sh`, `ui_guard.sh`, `boot_apps.sh`, `pmd_guard.sh`, and `account_setup.sh` + `debug_account.env` (`iksshd`). |
| `packages.db.enc` | AES-256-CBC encrypted package DB entry (`/__DB.3.x86_64`) triggering `pmd` `bootup_restore()` on stock 3.7.26. |
| `ikuai.py` | Core networking logic (`select_network`) and SQLite `config.db` provisioner (`provision_database`). |
| `build_image.py` | Offline utility to build sanitized raw images and inject boot payloads. |
| `make_manifest.py` | Generates signed/verified release manifest (`ikuai-cloud-v1-manifest.json`). |
| `rescue_logviewer.html` | Real-time web log viewer accessed via browser during the rescue phase. |
| `vendor/` | Vendored upstream scripts (`reinstall.sh`, `trans.sh`, `initrd-network.sh`, `LICENSE`). |
| `tests/` | Unit and integration test suite covering config, apply_profile, installer, image, quick, and manifest. |
| `VERSION` | Single source of truth for the release version string. |
| `CHANGELOG.md` | Chronological record of versions, vendor additions, and modifications. |

---

## 2. Default Configuration & Interface Contracts

Every installation generated by this repository is configured with the following defaults:

### Web Management Configuration (Requirement R2)
- **Forced HTTPS**: **Disabled** by default (`force_https = 0`). Users can connect via plain HTTP without mandatory SSL redirect.
- **HTTP Management Port**: **`88`** (`http_port = 88`).
- **HTTPS Management Port**: **`448`** (`https_port = 448`).
- **WAN Web Access**: Enabled (`open_wanweb = 1`).
- **Access URLs**:
  - `http://<Public-IP>:88/`
  - `https://<Public-IP>:448/`

### SSH Remote Control & `iksshd` Root Credentials (Requirement R3)
- **Service Status**: **Enabled** by default (`open_sshd = 1`, `sshd_port = 22`).
- **Daemon**: Dropbear SSH server (`/usr/sbin/dropbear`).
- **Account Identity**: `iksshd` (Root UID `0`, GID `0`, Home `/root`, Shell `/bin/ash`).
- **Password Hash**: `$1$sanjin16$gGSuGogZ6g5njXAnlRyaN1` (MD5-crypt hash extracted from tested firmware package 17).
- **Passwd Record**: `iksshd:x:0:0:passwd:/root:/bin/ash`
- **Shadow Record**: `iksshd:$1$sanjin16$gGSuGogZ6g5njXAnlRyaN1:20158:0:99999:7:::`
- **Preservation Mandate**: Because stock 3.7.26 does not invoke `/etc/mnt/ikuai/account_setup.sh`, `iksshd` runtime persistence relies on `pgstore.bin.pkg`'s `account_setup.sh` reading `debug_account.env` and running via both `boot.ext2`'s `/usr/ikuai/local-market/bootstrap.sh` and `pmd` `bootup_restore()` on every boot. Both `boot.ext2` (from `iKuai8_x64_3.7.26_plugin-store_2.1.0.bin`) and `pgstore.bin.pkg` + `packages.db.enc` MUST remain aligned at version `2.1.0` and preserve `iksshd`.

### Plugin Market (`02.pgstore` `2.1.0`) & Runtime Guards
- **Provisioning Path**:
  - Partition 1 (`boot.ext2`): extracted from `iKuai8_x64_3.7.26_plugin-store_2.1.0.bin` (SHA-256 `3f3116ec092305f01915457bd65e92a9a4b7ee9ed4a4b2ce6342cbc5c4d524f0`), containing pre-patched 3.7.26 `rootfs` (`/usr/ikuai/local-market/`, `rc`, `webman.lua`, UI JS, `monitor_process.sh`) and `xzskip`-patched `vmlinuz`.
  - Partition 5 (`/etc/log`): `apply_profile.py` (`install_local_market()`) writes `pgstore.bin.pkg` (`2.1.0`) -> `/packages/pgstore.bin.pkg` and `packages.db.enc` -> `/packages/db/.__DB.3.x86_64`, plus `/pmd_turnoff` (`01`) on Partition 3 (`/etc/mnt`).
- **Online Market & GWID Activation Gate**:
  - `script/online_hub.sh` connects to `https://raw.githubusercontent.com/ikuaiapp/plugin-hub/main/plugins.json` (with automatic GitHub mirror fallback chain for Mainland China).
  - `script/auth_gate.sh` displays the router's 32-character hardware `GWID` machine code and unlocks Online Market & install/uninstall actions with the activation code `GWID[4:-4]` (strip first 4 and last 4 characters), persisting authorization in `/etc/log/pgstore/auth.json` (`0700`/`0600`).
- **Boot Activation Guards**:
  1. Patches `/usr/openresty/lua/lib/webman.lua` from 50 MiB to 128 MiB (`upload_limit_guard.sh`).
  2. Links `/usr/ikuai/www/plugins/02.pgstore` and `/usr/ikuai/function/plugin_pgstore`.
  3. Patches the Webpack plugin-list `.js.gz` chunk (`ui_guard.sh`) so plugins render without cloud binding.
  4. Injects `iksshd` into `/etc/passwd` & `/etc/shadow` (`account_setup.sh` + `debug_account.env`) and starts installed apps in `/etc/log/app_dir` (`boot_apps.sh`).
  5. Enforces `pmd_guard.sh` before returning to `pmd`: adds `127.0.0.1 pkgmanager.ikuai8.com` to `/etc/hosts`, rejects outbound TCP `1863,15602`, wraps `/usr/sbin/pmd` & patches `monitor_process.sh`, and sends `kill -9` via `--late` so live-internet routers do not overwrite `02.pgstore` with cloud `pgstore`.

### iKuai 3.7.26 Base Version (Requirement R4)
- Installations deploy genuine iKuai 3.7.26 with `plugin-store 2.1.0` via `boot.ext2` extracted from `iKuai8_x64_3.7.26_plugin-store_2.1.0.bin` (derived from `iKuai8_x64_3.7.26_Build202609111743.bin`) written to Partition 1.
- Result: Native 3.7.26 kernel, rootfs, `iksshd`, and `02.pgstore` `2.1.0` (Online Plugin Market + GWID Gate) without requiring post-installation manual upgrades.

---

## 3. Strict +0.01 Version Increment Rule (Requirement R1)

This repository follows a strict incremental release versioning policy:
1. **Base Version**: The repository starts at **`0.01`** (current version: **`0.02`**).
2. **Increment Rule**: Each subsequent cloud vendor adaptation, modification, and verification increments the version number strictly by **`0.01`** (e.g., `0.01` -> `0.02` -> `0.03`).
3. **Single Source of Truth**: The `VERSION` file at the repository root contains the exact version string terminated by a newline (`0.02\n`).
4. **Git Tagging**: Every release MUST be tagged with `v<VERSION>` (e.g. `v0.02`).
5. **Changelog Requirement**: Every increment MUST be logged in `CHANGELOG.md` detailing the vendor name, tested VM type, and verification outcomes.

---

## 4. Cloud Vendor Adaptation Protocol

When adapting a new cloud vendor (e.g., AWS EC2, Google Cloud, Alibaba Cloud, Huawei Cloud, UCloud):

1. **Investigate Vendor Topology**:
   - Check if the instance uses direct public IP on the NIC or 1:1 NAT behind private IP.
   - If NAT, determine the vendor metadata service (e.g., `169.254.169.254`) and required auth headers.
2. **Implement Network Resolver in `install.py` / `ikuai.py`**:
   - Add a vendor metadata probe function (similar to `tencent_metadata` or `oracle_metadata_vnics`).
   - Add a corresponding CLI flag (e.g. `--aws-nat-public-ip`, `--aliyun-nat-public-ip`).
   - Validate that interface MAC, local private IP, gateway, and public egress IP match before accepting.
3. **Validate in Testing Environment**:
   - Add unit tests under `tests/test_installer.py` using mock metadata fixtures.
   - Run end-to-end preflight verification on a live test VPS of the vendor.
4. **Verify Safety & Rollback**:
   - Confirm vendor cloud security group rules allow inbound TCP 88, 448, and 22.
   - Confirm vendor serial console / VNC rescue mechanism is functional.
5. **Execute Version Bump**:
   - Increment `VERSION` by `+0.01`.
   - Document in `CHANGELOG.md`.

---

## 5. Security & Desensitization Rules (Requirement R5)

All agents MUST enforce the following security rules prior to committing or publishing:

1. **IP Desensitization**:
   - NEVER commit real server IP addresses (public or private).
   - Use RFC 5737 documentation prefix addresses only:
     - `198.51.100.0/24` (TEST-NET-2)
     - `203.0.113.0/24` (TEST-NET-3)
     - `192.0.2.0/24` (TEST-NET-1)
2. **No Secret Tokens**:
   - NEVER commit API tokens, cloud access keys, personal passwords, or private SSH keys into tracked Git files.
3. **Repository Identifiers**:
   - All repository URLs must reference `https://github.com/ikuaiapp/reinstall`.
4. **Git Identity**:
   - Commits must use the official committer identity:
     - Name: `ikuaiapp`
     - Email: `ikuaiapp@users.noreply.github.com`
5. **File Exclusion**:
   - `.gitignore` must ignore binaries, disk images (`*.img`, `*.raw`, `*.raw.gz`, `*.iso`, `*.bin`, `*.ext2`, `*.ext4`), Python cache files, and release archives.

---

## 6. Verification Commands

Run all verification checks prior to finalizing any task:

```bash
# 1. Full Unit & Integration Test Suite
python3 -m unittest discover -s tests -p "test_*.py" -v

# 2. Bash Script Syntax Validation
bash -n quick.sh vendor/*.sh

# 3. Version String Integrity
cat VERSION    # Must output exactly: 0.02

# 4. Sensitive IP, Token & Workspace Path Scan (Must return 0 hits outside tests/fixtures)
grep -rn -E 'PRIVATE KEY-----' .
# Also scan tracked files for non-RFC5737 real server IPs, passwords, tokens (gh*_/pat), or local host paths.

# 5. Git Status Check
git status     # Ensure working tree is clean and untracked files are handled
```

---

## 7. Release Packaging Workflow

To generate `v0.02` release assets:

1. **Source Archive**:
   ```bash
   tar --sort=name --mtime='@0' --owner=0 --group=0 --numeric-owner \
       --exclude-vcs --exclude='*.pyc' --exclude='__pycache__' \
       --exclude='*.raw*' --exclude='*.img' --exclude='*.ext*' --exclude='*.tar.gz' \
       --exclude='quick.sh' --exclude='SHA256SUMS' \
       -czf ikuai-vps-reinstall-source.tar.gz .
   ```
2. **Manifest Generation** (when base images or `boot.ext2` change):
   ```bash
   python3 make_manifest.py --bios-prefix /path/to/ikuai-3.7.16-bios \
                            --uefi-prefix /path/to/ikuai-3.7.16-uefi \
                            --boot-payload /path/to/boot.ext2 \
                            --output ikuai-cloud-v1-manifest.json
   ```
3. **Update `quick.sh` & Compile `SHA256SUMS`**:
   Update `release`, `source_sha`, and `manifest_sha` in `quick.sh`, then compile:
   ```bash
   sha256sum ikuai-3.7.16-bios.raw.gz ikuai-3.7.16-uefi.raw.gz boot.ext2 \
             pgstore.bin.pkg packages.db.enc \
             ikuai-cloud-v1-manifest.json ikuai-vps-reinstall-source.tar.gz quick.sh > SHA256SUMS
   ```
4. **Git Tag & Release (using Out-of-Repo Persistent `gh` Auth)**:
   ```bash
   git tag -a v0.02 -m "Release v0.02: iKuai 3.7.26 reinstall with plugin-store 2.1.0"
   WORKSPACE_ROOT="$(cd "$(git rev-parse --show-toplevel)/../.." && pwd)"
   GH_BIN="$WORKSPACE_ROOT/.local-tools/gh/bin/gh"
   GH_CFG="$WORKSPACE_ROOT/.local-tools/gh/config"
   GH_CONFIG_DIR="$GH_CFG" "$GH_BIN" auth status
   GH_CONFIG_DIR="$GH_CFG" "$GH_BIN" auth setup-git
   git push origin main --tags
   ```

---

## 8. AI Agent Fast-Start & Persistent Out-of-Repo GitHub Auth (Preserve Device Code)

To guarantee that any future AI Agent or clean environment takeover can immediately push/release without losing GitHub OAuth device authorization ("机器码") OR leaking credentials during desensitization:

1. **Out-of-Repo Auth Storage**:
   - NEVER store `hosts.yml`, OAuth tokens, `.env`, or credentials inside this Git repository.
   - The workspace maintains a persistent out-of-repo GitHub CLI binary & config two levels above the repository root (`$WORKSPACE_ROOT/.local-tools/gh/bin/gh` and `$WORKSPACE_ROOT/.local-tools/gh/config/hosts.yml`).
   - Always invoke `gh` with `GH_CONFIG_DIR` pointing to that out-of-repo directory:
     ```bash
     WORKSPACE_ROOT="$(cd "$(git rev-parse --show-toplevel)/../.." && pwd)"
     GH_CONFIG_DIR="$WORKSPACE_ROOT/.local-tools/gh/config" "$WORKSPACE_ROOT/.local-tools/gh/bin/gh" auth status
     ```
2. **Preserve Device Authorization Across Cleanups**:
   - NEVER delete or overwrite `$WORKSPACE_ROOT/.local-tools/gh/config` during repository cleanup, history sanitization, or container resets.
   - If the token is ever missing or expired, re-run `gh auth login --hostname github.com --git-protocol https --web` with `GH_CONFIG_DIR="$WORKSPACE_ROOT/.local-tools/gh/config"` so only a single device code verification is needed for all repositories in the workspace.
3. **Quick Agent Onboarding Checklist**:
   1. Read `VERSION`, `AGENTS.md`, `CHANGELOG.md`, and run `python3 -m unittest discover -s tests -p "test_*.py"`.
   2. Verify out-of-repo `gh auth status` as `ikuaiapp`.
   3. When integrating a new `plugin-store` firmware `.bin`: extract 50 MiB `boot.ext2` via `parse_outer_bin` + `gzip.decompress`, copy aligned `pgstore.bin.pkg` and `packages.db.enc` (ensuring `debug_account.env` + `account_setup.sh` preserve `iksshd`), update `BOOT_PAYLOAD_SHA256` in `install.py` and `ikuai-cloud-v1-manifest.json`, rebuild `ikuai-vps-reinstall-source.tar.gz`, refresh `quick.sh` + `SHA256SUMS`, run tests + grep desensitization check, bump `VERSION` by `+0.01`, push, and verify on live VPS.

