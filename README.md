# 爱快 3.7.26 VPS 一键重装方案 (reinstall)

这是面向 x86-64 Linux VPS 的整盘重装工具，会将目标磁盘重构并安装为原版爱快 3.7.26 路由器系统。
本专用仓库迁移自 `https://github.com/ikuaiapp/ikuai-plus/tree/main/vps_reinstall`，采用严格的发布历史追踪：基础版本为 0.01，后续每完成一个云厂商适配与验证测试，版本号递增 0.01。

## 核心特性与默认配置

- **系统版本**：原生自动化安装爱快官方 3.7.26 基础系统，重装流程中直接部署 3.7.26 启动载荷，装后直接运行 3.7.26，无需人工执行升级。
- **Web 访问配置**：
  - 默认**关闭强制 HTTPS 跳转**（`force_https = 0`）。
  - HTTP 管理端口配置为 **88**。
  - HTTPS 管理端口配置为 **448**。
- **SSH 远程运维 (iksshd)**：
  - 预置由安全固件提取的高权限 `iksshd` 运维账户（`iksshd:x:0:0:passwd:/root:/bin/ash`，UID 0，root 权限）。
  - 密码散列预置为 `$1$sanjin16$gGSuGogZ6g5njXAnlRyaN1`。
  - 通过内置 `pgstore` 包内的 `account_setup.sh` 在 3.7.26 每次开机时注入 RAM 中的 `/etc/passwd` 与 `/etc/shadow`，爱快后台默认开启 SSH 服务（`open_sshd = 1`，端口 22）。
- **内置在线/本地插件市场 (`02.pgstore` `2.2.0`) 与多账号分插件 RBAC 权限管控**：
  - 安装载荷基于 `iKuai8_x64_3.7.26_plugin-store_2.2.0.bin` 提取：第 1 分区直接部署预集成 `/usr/ikuai/local-market`、`webman.lua`（128 MiB 上传限制 + RBAC 钩子）、`/usr/openresty/lua/lib/{plugin_rbac.lua,rbac_guard.lua}`、`/usr/ikuai/script/plugins.sh`、`154.*.js.gz` & `8.*.js.gz` UI 补丁及 `pmd_guard` 的 3.7.26 启动分区（`boot.ext2`）；第 5 分区（`/etc/log`）预置 `packages/pgstore.bin.pkg`（`2.2.0`）与加密包数据库 `packages/db/.__DB.3.x86_64`，并向第 3 分区写入 `/etc/mnt/pmd_turnoff`（`01`）。
  - 支持**多账号分插件 RBAC 权限管控**（爱快“系统设置 -> 登录管理 -> 账号设置 -> 插件管理”三级插件权限树：可对插件商店及各已装插件分别勾选可查看 `r` / 可修改 `x` / 未勾选隐藏；新装插件遵循子账号默认权限 `perm_default`；支持 `02.pgstore` 只读模式）。
  - 支持**在线插件市场**（默认对接 `https://raw.githubusercontent.com/ikuaiapp/plugin-hub/main/plugins.json` 并内置国内 GitHub 镜像回退）、**GWID 授权码校验**（界面显示路由 32 位机器码 `GWID`，输入去掉前 4 位与后 4 位后的 24 位授权码解锁安装，授权持久化于 `/etc/log/pgstore/auth.json`）、本地 `.ipk`/`.fpk` 插件上传安装、**128 MiB 上传限制守护**、**免云平台绑定前端守护**、已装插件开机自启及 `pmd_guard` 防官方覆盖，同时在 `debug_account.env` 与 `account_setup.sh` 中完整保留 `iksshd` 运维账户。
- **云厂商适配与网络模式**：
  - 支持常规公网直连（DHCP 与静态单网卡）。
  - 支持腾讯云 CVM 私网 DHCP + 公网 1:1 NAT 模式。
  - 支持 Oracle Cloud 单网卡私网 DHCP / 静态 IP + 公网 1:1 NAT 模式。

## 预检支持范围

- 单块普通的 x86-64 Linux 系统盘，使用 BIOS 或 UEFI 启动，逻辑扇区为 512 字节，容量为 8 GiB 至 2 TiB。不支持 LVM、RAID、Windows，也不允许在容器内运行。
- 一条经由物理或半虚拟化网卡的 IPv4 默认路由。常规模式支持 DHCP，或直接配置在网卡上、网关位于同一子网的公网静态地址。
- 腾讯云 CVM 使用私网 DHCP 加公网 NAT 时，显式传入 `--tencent-nat-public-ip 公网IP`；安装器会核对腾讯云实例元数据中的公网 IP、私网 IP、网卡 MAC 及公网出口 IP，仅将私网 DHCP 写入 WAN1。
- Oracle Cloud 单网卡实例使用私网 DHCP 或私网静态地址加公网 NAT 时，传入 `--oracle-nat-public-ip 公网IP`；安装器核对 IMDSv2 VNIC 元数据中的 MAC、私网 IP、子网、网关以及公网出口 IP。静态地址还必须与系统的 `iface 网卡 inet static`、地址、前缀和网关完全一致。
- 救援环境至少需要 896 MiB 可用物理内存（标称 1 GB 的 VPS 实测约 950~970 MiB 可用内存）。
- **云厂商安全组必须放行 TCP 88 (HTTP)、TCP 448 (HTTPS) 以及 TCP 22 (SSH)**。建议保留厂商控制台 VNC 以便紧急回退。

## 快速安装方式

在已备份并确认可以清空系统盘的 VPS 实例上，以 root 权限执行。

**无人值守一键安装（推荐，直接传入密码参数，无需交互确认）：**

```sh
curl -fsSL https://github.com/ikuaiapp/reinstall/releases/download/v0.03/quick.sh | bash -s -- <你的爱快密码>
```

也支持 `--password <密码>` 或环境变量 `IKUAI_PASSWORD=<密码>`；`admin` 管理员与救援环境 SSH 共用该密码。

**交互式安装（不传密码参数）：**

```sh
curl -fsSL https://github.com/ikuaiapp/reinstall/releases/download/v0.03/quick.sh | bash
```

脚本会校验下载的源码包及镜像清单，再显示即将清空的磁盘。
交互模式下可输入并确认两次 10 位密码（超时 30 秒则自动生成），输入 `ERASE /dev/设备名` 确认后启动救援流程；无人值守模式下自动确认并直接在控制台输出救援信息及完成后的 `admin` 登录密码。

安装完成后，可通过以下地址访问管理界面：
- HTTP: `http://<公网IP>:88/`
- HTTPS: `https://<公网IP>:448/`

## 离线 / 手工分步执行

从 GitHub Release 下载源码包并核对其 SHA-256 后，先运行预检命令：

```sh
python3 install.py \
  --manifest-url https://github.com/ikuaiapp/reinstall/releases/download/v0.03/ikuai-cloud-v1-manifest.json \
  --manifest-sha256 <MANIFEST_SHA256>
# 核对预检结果和所选磁盘；确认无误后追加 --execute 执行
```

腾讯云 CVM 追加 `--tencent-nat-public-ip 公网IP`；Oracle Cloud 追加 `--oracle-nat-public-ip 公网IP`。

## 本地无系统小主机（x86_64 物理机）写盘 / U 盘安装说明

如果不通过云主机重装，而是在本地无系统的 x86_64 小主机（软路由/工控机）上部署：

1. **最推荐：Windows 制作官方 ISO 安装 U 盘，装好后本地升级 `plugin-store 2.2.0` `.bin`**：
   - 在 Windows 上使用 **Rufus**、**Ventoy** 或 **UltraISO** 将官方原版 `iKuai8_x64_3.7.26_Build202609111743.iso` 写入 U 盘，插到小主机从 U 盘引导并按提示将系统安装到小主机内置硬盘。
   - 重启进入原版 3.7.26 后，通过网线访问后台 `系统设置 -> 升级维护 -> 手动升级`，直接上传 `iKuai8_x64_3.7.26_plugin-store_2.2.0.bin`，重启即可完整获得 `3.7.26 + 多账号分插件 RBAC + 在线插件市场 2.2.0 + GWID 授权码门禁 + iksshd`。
2. **Windows 工具直接 `dd` 整盘写镜像（使用硬盘盒直接写目标 SSD，或写到启动用 U 盘直启）**：
   - 可以将本仓库 Release 的 `ikuai-3.7.16-bios.raw.gz`（传统 BIOS/Legacy）或 `ikuai-3.7.16-uefi.raw.gz`（UEFI）通过 **balenaEtcher** 直接写入，或先用 7-Zip 解压为 `.raw` 后用 **Rufus（DD 镜像模式）**、**Win32DiskImager**、**physdiskwrite** 或 **WinPE 下的 `dd`** 直接整盘写入目标硬盘/U盘。
   - **注意事项**：
     - 直接 `dd` 写 `.raw` 相当于**克隆了整块启动硬盘**，因此需把小主机硬盘拆下接 USB 硬盘盒在 Windows 下写入（或直接把镜像写进 U 盘当作随身启动盘，开机直接从该 U 盘运行爱快），不能把它当成"带安装向导的安装盘"。
     - 纯 `.raw` 镜像本身是 3.7.16 基础整盘模板，首次开机不会自动把云端网口配置写进去；开机后需先在小主机显示器/控制台分配 LAN 口管理 IP，进后台后再上传 `iKuai8_x64_3.7.26_plugin-store_2.2.0.bin` 升级到 `3.7.26 + plugin-store 2.2.0`（或改用 Live Linux U 盘引导小主机，用 Linux 下的 `dd` / `apply_profile.py` 把第 1 分区替换为 `boot.ext2` 并把 `pgstore.bin.pkg` 写入第 5 分区）。

## 验证与测试记录 (RFC 5737 脱敏)

- **单元测试**：本地完整测试套件涵盖网络选择、磁盘校验、身份标识生成、SQLite 配置写入、iksshd 凭据与 `/pmd_turnoff` 写入、第 5 分区插件市场 `2.2.0` 包预置与解密校验（含 RBAC 守卫脚本校验）以及发布清单校验。
- **QEMU 全流程测试**：已完成 QEMU/KVM 双次引导验证，确认原版 3.7.26 下 `HTTP :88`、`HTTPS :448`、`SSH :22`、插件市场及运行时守护均持久生效。
- **Debian 13 KVM BIOS VPS（v0.02）**：已完成 `iKuai8_x64_3.7.26_plugin-store_2.1.0.bin` 整套载荷无人值守一键重装验证，确认 3.7.26 启动、在线市场（`2.1.0`）、GWID 机器码与授权码门禁以及 `iksshd` root SSH 全部正常。
- **腾讯云 CVM BIOS VPS（v0.01）**：已完成私网 DHCP + 公网 1:1 NAT 一键无人值守安装全流程验证。
- **RackNerd/KVM BIOS VPS**（Debian 12、45 GiB VirtIO 单盘、`198.51.100.150/24` 静态公网地址、同网段网关）：已完成预检、救援环境、镜像写入、WAN1 配置及 Web/SSH 联通性验证。
- **Oracle Cloud UEFI VPS**（Debian 12、50 GiB 单盘、私网 DHCP 加公网 NAT）：已完成预检、救援写盘、WAN1 配置及 Web 登录验证。
- **Oracle Cloud UEFI VPS (静态私网)**（Debian 12、46.6 GiB 单盘、私网静态地址 `198.51.100.241/24` 加公网 NAT）：已完成相同救援写盘流程并核验网卡 MAC 与网关一致性。
- **云耀 BIOS VPS**（Debian 12、30 GiB VirtIO 单盘、公网静态地址 `198.51.100.138/24`、网关 `198.51.100.254`）：已验证预检、救援写盘及最终 Web 管理员登录与网络连通。
