#!/usr/bin/env python3
"""
Mock Target Serial Server for Labgrid Phase 1 Prototyping
Simulates a DUT serial console running U-Boot -> Linux transition.
"""

import argparse
import socket
import sys
import time

UBOOT_HEADER = """
U-Boot 2026.04 (Jul 01 2026 - 12:00:00 +0000)

DRAM:  2 GiB
Core:  15 devices, 9 uclasses, devicetree: separate
Loading Environment from Flash... OK
In:    serial@10000000
Out:   serial@10000000
Err:   serial@10000000
Net:   eth0: virtio-net#0
Hit any key to stop autoboot:  1 
"""

LINUX_BOOT_LOG = """
[    0.000000] Linux version 6.6.0-riscv64 (runner@osu-osl) (gcc 13.2.0) #1 SMP
[    0.450123] Machine model: QEMU RISC-V Virt Board
[    0.890123] virtio_net virtio0: registered device eth0
[    1.200456] EXT4-fs (vda2): mounted filesystem with ordered data mode.
[    1.500000] Starting systemd-udevd...
[    2.000000] Welcome to Debian GNU/Linux 13 (trixie)!

root@qemu-board:~# 
"""

def handle_client(conn):
    conn.settimeout(0.1)
    print("[MockTarget] Client connected to serial socket.")
    
    # Print U-Boot banner and prompt
    conn.sendall(UBOOT_HEADER.encode('utf-8'))
    conn.sendall(b"\n=> ")
    
    in_uboot = True
    in_linux = False
    buffer = ""

    while True:
        try:
            data = conn.recv(1024)
            if not data:
                print("[MockTarget] Client disconnected.")
                break
            text = data.decode('utf-8', errors='ignore')
            buffer += text
            
            while '\n' in buffer or '\r' in buffer:
                line_end = max(buffer.find('\n'), buffer.find('\r'))
                cmd_raw = buffer[:line_end+1]
                buffer = buffer[line_end+1:]
                cmd = cmd_raw.strip()
                if not cmd:
                    continue
                print(f"[MockTarget] Received command: '{cmd}'")

                if in_uboot:
                    if cmd == "dhcp":
                        conn.sendall(b"dhcp\nBOOTP broadcast 1\nDHCP client bound to address 192.168.100.50\n=> ")
                    elif cmd.startswith("setenv"):
                        conn.sendall(f"{cmd}\n=> ".encode('utf-8'))
                    elif cmd.startswith("tftp"):
                        conn.sendall(b"tftp\nUsing virtio-net#0 device\nTFTP from server 192.168.100.1; our IP address is 192.168.100.50\nFilename 'qemu-board/fitImage'.\nLoad address: 0x84000000\nLoading: #################################\n         1.2 MiB/s\ndone\nBytes transferred = 12582912 (c00000 hex)\n=> ")
                    elif cmd.startswith("bootm") or cmd.startswith("booti") or cmd == "boot":
                        conn.sendall(b"bootm\n## Booting kernel from FIT Image at 0x84000000 ...\nStarting kernel ...\n\n")
                        conn.sendall(LINUX_BOOT_LOG.encode('utf-8'))
                        in_uboot = False
                        in_linux = True
                    elif cmd.startswith("echo"):
                        val = cmd.replace("echo", "").replace("'", "").replace('"', "").strip()
                        conn.sendall(f"{val}\n=> ".encode('utf-8'))
                    else:
                        conn.sendall(b"\n=> ")
                elif in_linux:
                    # Parse command compound statement
                    lines = cmd.split(';')
                    for item in lines:
                        item = item.strip()
                        if item.startswith("echo"):
                            val = item.replace("echo", "").replace("'", "").replace('"', "").replace("$?", "0").strip()
                            conn.sendall(f"{val}\n".encode('utf-8'))
                        elif "uname" in item:
                            conn.sendall(b"Linux qemu-board 6.6.0-riscv64 #1 SMP PREEMPT riscv64 GNU/Linux\n")
                    conn.sendall(b"root@qemu-board:~# ")

        except socket.timeout:
            continue
        except Exception as e:
            print(f"[MockTarget] Error: {e}")
            break

def main():
    parser = argparse.ArgumentParser(description="Mock Serial DUT Target Server")
    parser.add_argument("--port", type=int, default=2001, help="TCP port to listen on for serial connection")
    args = parser.parse_args()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("127.0.0.1", args.port))
    except OSError as e:
        if e.errno == 98: # Address already in use
            print(f"[MockTarget] Target server is already active on port {args.port}.")
            sys.exit(0)
        raise

    server.listen(1)
    print(f"[MockTarget] Listening for serial connection on 127.0.0.1:{args.port}...")

    try:
        while True:
            conn, _ = server.accept()
            handle_client(conn)
            conn.close()
    except KeyboardInterrupt:
        print("\n[MockTarget] Shutting down.")
    finally:
        server.close()

if __name__ == "__main__":
    main()
