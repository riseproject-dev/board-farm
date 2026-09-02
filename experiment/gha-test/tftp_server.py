#!/usr/bin/env python3
"""
Lightweight UDP TFTP Server for Local Experiment Testing.
Serves files from /tmp/tftp to QEMU / DUT clients over TFTP protocol (RFC 1350).
"""

import argparse
import os
import socket
import struct
import sys
import time

# TFTP Opcodes
OP_RRQ = 1
OP_WRQ = 2
OP_DATA = 3
OP_ACK = 4
OP_ERROR = 5

def handle_rrq(sock, client_addr, filename, root_dir):
    # Sanitize filename
    clean_name = filename.decode('utf-8', errors='ignore').strip('/')
    filepath = os.path.join(root_dir, clean_name)
    print(f"[TFTPServer] Client {client_addr} requested file: {clean_name}")

    if not os.path.exists(filepath):
        print(f"[TFTPServer] File not found: {filepath}")
        # Send error packet
        err_msg = b"File not found"
        pkt = struct.pack("!HH", OP_ERROR, 1) + err_msg + b"\x00"
        sock.sendto(pkt, client_addr)
        return

    try:
        with open(filepath, "rb") as f:
            block = 1
            while True:
                chunk = f.read(512)
                pkt = struct.pack("!HH", OP_DATA, block) + chunk
                sock.sendto(pkt, client_addr)
                
                # Wait for ACK (simple timeout loop)
                try:
                    sock.settimeout(2.0)
                    ack, addr = sock.recvfrom(512)
                    if len(ack) >= 4:
                        opcode, ack_block = struct.unpack("!HH", ack[:4])
                        if opcode == OP_ACK and ack_block == block:
                            block += 1
                except socket.timeout:
                    print(f"[TFTPServer] Timeout waiting for ACK block {block}")
                
                if len(chunk) < 512:
                    break
        print(f"[TFTPServer] Transfer of {clean_name} completed to {client_addr}")
    except Exception as e:
        print(f"[TFTPServer] Error transferring file: {e}")

def main():
    parser = argparse.ArgumentParser(description="Python TFTP Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host IP to bind to")
    parser.add_argument("--port", type=int, default=6969, help="UDP port to listen on")
    parser.add_argument("--root", default="/tmp/tftp", help="Root directory for TFTP files")
    args = parser.parse_args()

    os.makedirs(args.root, exist_ok=True)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        sock.bind((args.host, args.port))
        print(f"[TFTPServer] Listening on UDP {args.host}:{args.port} (root: {args.root})...")
    except PermissionError:
        print(f"[TFTPServer] Permission denied to bind UDP {args.host}:{args.port}. Try port > 1024.")
        sys.exit(1)

    sock.settimeout(1.0)
    while True:
        try:
            data, client_addr = sock.recvfrom(512)
            if len(data) >= 4:
                opcode = struct.unpack("!H", data[:2])[0]
                if opcode == OP_RRQ:
                    parts = data[2:].split(b"\x00")
                    filename = parts[0]
                    handle_rrq(sock, client_addr, filename, args.root)
        except socket.timeout:
            continue
        except KeyboardInterrupt:
            print("\n[TFTPServer] Shutting down.")
            break
        except Exception as e:
            print(f"[TFTPServer] Exception: {e}")

if __name__ == "__main__":
    main()
