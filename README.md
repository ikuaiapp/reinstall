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
- **内置本地插件市场 (`02.pgstore`)**：
  - 安装过程中自动向第 5 分区（`/etc/log`）预置 `packages/pgstore.bin.pkg`（`2.0.1-local-source`）与加密包数据库 `packages/db/.__DB.3.x86_64`，并向第 3 分区写入 `/etc/mnt/pmd_turnoff`（`01`）。
  - 在原生 3.7.26 每次启动时自动激活**本地插件市场**（`/plugins/02.pgstore/02.pgstore.html` 与 `plugin_pgstore` 接口），自动运行 **128 MiB 上传限制守护**（`upload_limit_guard.sh`）、**本地插件菜单前端守护**（`ui_guard.sh`，免云平台绑定即可显示本地插件）以及 `/etc/log/app_dir` 已装插件开机自启（`boot_apps.sh`）。
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
curl -fsSL https://github.com/ikuaiapp/reinstall/releases/download/v0.01/quick.sh | bash -s -- <你的爱快密码>
```

也支持 `--password <密码>` 或环境变量 `IKUAI_PASSWORD=<密码>`；`admin` 管理员与救援环境 SSH 共用该密码。

**交互式安装（不传密码参数）：**

```sh
curl -fsSL https://github.com/ikuaiapp/reinstall/releases/download/v0.01/quick.sh | bash
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
  --manifest-url https://github.com/ikuaiapp/reinstall/releases/download/v0.01/ikuai-cloud-v1-manifest.json \
  --manifest-sha256 <MANIFEST_SHA256>
# 核对预检结果和所选磁盘；确认无误后追加 --execute 执行
```

腾讯云 CVM 追加 `--tencent-nat-public-ip 公网IP`；Oracle Cloud 追加 `--oracle-nat-public-ip 公网IP`。

## 验证与测试记录 (RFC 5737 脱敏)

- **单元测试**：本地完整测试套件涵盖网络选择、磁盘校验、身份标识生成、SQLite 配置写入、iksshd 凭据与 `/pmd_turnoff` 写入、第 5 分区本地插件市场包预置以及发布清单校验。
- **QEMU 全流程测试**：已完成 QEMU/KVM 双次引导（Boot 1 + 硬重启 + Boot 2）验证，确认原版 3.7.26 下 `HTTP :88`、`HTTPS :448`、`SSH :22`、本地插件市场（`02.pgstore` 与 `plugin_pgstore`）、128 MiB 上传限制及前端 `ui_guard` 均持久生效。
- **RackNerd/KVM BIOS VPS**（Debian 12、45 GiB VirtIO 单盘、`198.51.100.150/24` 静态公网地址、同网段网关）：已完成预检、救援环境、镜像写入、WAN1 配置及 Web/SSH 联通性验证。
- **Oracle Cloud UEFI VPS**（Debian 12、50 GiB 单盘、私网 DHCP 加公网 NAT）：已完成预检、救援写盘、WAN1 配置及 Web 登录验证。
- **Oracle Cloud UEFI VPS (静态私网)**（Debian 12、46.6 GiB 单盘、私网静态地址 `198.51.100.241/24` 加公网 NAT）：已完成相同救援写盘流程并核验网卡 MAC 与网关一致性。
- **云耀 BIOS VPS**（Debian 12、30 GiB VirtIO 单盘、公网静态地址 `198.51.100.138/24`、网关 `198.51.100.254`）：已验证预检、救援写盘及最终 Web 管理员登录与网络连通。
