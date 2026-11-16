#!/usr/bin/env bash
set -euo pipefail

if [[ $(id -u) -ne 0 ]]; then
  echo 'Run as root on the VPS host.' >&2
  exit 1
fi
for tool in curl sha256sum tar python3; do
  command -v "$tool" >/dev/null || { echo "Missing required tool: $tool" >&2; exit 1; }
done

user_password=${IKUAI_PASSWORD:-}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --password|-p)
      [[ $# -ge 2 ]] || { echo "Missing value for $1" >&2; exit 1; }
      user_password=$2
      shift 2
      ;;
    --password=*)
      user_password=${1#*=}
      shift
      ;;
    --)
      shift
      if [[ $# -gt 0 ]] && [[ -z "$user_password" ]]; then
        user_password=$1
        shift
      fi
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      if [[ -n "$user_password" ]]; then
        echo "Unexpected argument: $1" >&2
        exit 1
      fi
      user_password=$1
      shift
      ;;
  esac
done

if [[ -z "$user_password" ]] && [[ ! -r /dev/tty ]]; then
  echo 'An interactive terminal is required for the disk confirmation.' >&2
  exit 1
fi

release='https://github.com/ikuaiapp/reinstall/releases/download/v0.01'
source_sha='b768b7ba6dd4250fe7ba1216b9e99c96165d9171edfe2c83f01c869c2fadb36c'
manifest_sha='d32f1c0e072b3f2009f4a9fd188db1483cf4d229abe4241af0fb892b67f255aa'
provider_args=()
if public_ip=$(curl --noproxy '*' -fsS --max-time 3 \
    http://169.254.0.23/latest/meta-data/public-ipv4 2>/dev/null); then
  # The installer independently checks Tencent metadata, WAN MAC, private IP,
  # and public egress before accepting this NAT mode.
  provider_args=(--tencent-nat-public-ip "$public_ip")
elif curl --noproxy '*' -fsS --max-time 3 -H 'Authorization: Bearer Oracle' \
    -o /dev/null http://169.254.169.254/opc/v2/vnics/ 2>/dev/null; then
  public_ip=$(curl --noproxy '*' -fsS --max-time 10 https://api.ipify.org)
  provider_args=(--oracle-nat-public-ip "$public_ip")
fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
curl -fL --retry 3 --connect-timeout 10 --max-time 180 -o "$tmp/source.tar.gz" "$release/ikuai-vps-reinstall-source.tar.gz"
printf '%s  %s\n' "$source_sha" "$tmp/source.tar.gz" | sha256sum -c -
tar -xzf "$tmp/source.tar.gz" -C "$tmp"
python_entry=$(find "$tmp" -name install.py | head -n1)
if [[ -n "$user_password" ]]; then
  python3 "$python_entry" \
    --manifest-url "$release/ikuai-cloud-v1-manifest.json" \
    --manifest-sha256 "$manifest_sha" \
    --password "$user_password" --yes \
    "${provider_args[@]}" --execute
else
  python3 "$python_entry" \
    --manifest-url "$release/ikuai-cloud-v1-manifest.json" \
    --manifest-sha256 "$manifest_sha" \
    "${provider_args[@]}" --execute </dev/tty
fi
