#!/usr/bin/env bash
# Helper script to download real pre-built Linux Kernel & Initramfs binaries
set -euo pipefail

TFTP_DIR="/tmp/tftp/qemu-board"
mkdir -p "$TFTP_DIR"

ARCH="${1:-riscv64}"

echo "========================================================"
echo " Downloading Real Linux Kernel & Initramfs ($ARCH)"
echo "========================================================"

if [ "$ARCH" = "riscv64" ]; then
    python3 -c "
import urllib.request, zipfile, io, shutil, os

tftp_dir = '$TFTP_DIR'
os.makedirs(tftp_dir, exist_ok=True)
url = 'https://gitlab.com/api/v4/projects/giomasce%2Fdqib/jobs/artifacts/master/download?job=convert_riscv64-virt'
print('Downloading official Debian DQIB RISC-V 64 kernel package...')
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
with urllib.request.urlopen(req) as resp:
    zip_bytes = resp.read()

with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
    z.extract('dqib_riscv64-virt/kernel', '/tmp')
    z.extract('dqib_riscv64-virt/initrd', '/tmp')

shutil.copy('/tmp/dqib_riscv64-virt/kernel', os.path.join(tftp_dir, 'vmlinuz'))
shutil.copy('/tmp/dqib_riscv64-virt/kernel', os.path.join(tftp_dir, 'fitImage'))
shutil.copy('/tmp/dqib_riscv64-virt/initrd', os.path.join(tftp_dir, 'initramfs'))
print('✓ Successfully extracted real Debian DQIB RISC-V 64 kernel & initrd.')
"
elif [ "$ARCH" = "x86_64" ]; then
    KERNEL_URL="https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/x86_64/netboot/vmlinuz-virt"
    INITRD_URL="https://dl-cdn.alpinelinux.org/alpine/v3.20/releases/x86_64/netboot/initramfs-virt"
    
    echo "Downloading vmlinuz from $KERNEL_URL..."
    curl -Lo "$TFTP_DIR/vmlinuz" "$KERNEL_URL"
    cp "$TFTP_DIR/vmlinuz" "$TFTP_DIR/fitImage"
    
    echo "Downloading initramfs from $INITRD_URL..."
    curl -Lo "$TFTP_DIR/initramfs" "$INITRD_URL"
else
    echo "Unsupported architecture: $ARCH."
    exit 1
fi

echo ""
echo "✓ Real Linux binaries prepared at $TFTP_DIR:"
ls -lh "$TFTP_DIR/fitImage" "$TFTP_DIR/vmlinuz" "$TFTP_DIR/initramfs"
