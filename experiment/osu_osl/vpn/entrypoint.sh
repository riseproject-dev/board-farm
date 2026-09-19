#!/bin/sh
set -e

echo "[osu-vpn] Starting OpenVPN client..."
openvpn --config /etc/openvpn/client.ovpn --daemon ovpn_daemon

echo "[osu-vpn] Waiting for tun0 interface..."
for i in $(seq 1 30); do
    if ip addr show dev tun0 2>/dev/null | grep -q "inet "; then
        break
    fi
    sleep 1
done

VPN_IP=$(ip -4 addr show dev tun0 | awk '/inet / {print $2}' | cut -d/ -f1)
echo "[osu-vpn] Connected! Assigned IP: $VPN_IP"

# Configure DNS inside container
echo "nameserver 10.1.0.131" > /etc/resolv.conf
echo "nameserver 10.1.0.130" >> /etc/resolv.conf
echo "nameserver 8.8.8.8" >> /etc/resolv.conf
echo "search bak.milne.osuosl.org osuosl.org" >> /etc/resolv.conf

# Start SOCKS5 proxy via Dante on port 1080
cat << 'DANTE' > /etc/sockd.conf
logoutput: stderr
internal: 0.0.0.0 port = 1080
external: tun0
socksmethod: none
clientmethod: none
user.privileged: root
user.unprivileged: nobody

client pass {
    from: 0.0.0.0/0 to: 0.0.0.0/0
    log: error
}

socks pass {
    from: 0.0.0.0/0 to: 0.0.0.0/0
    log: error
}
DANTE

sockd -D &
echo "[osu-vpn] SOCKS5 proxy started on 0.0.0.0:1080"
echo "[osu-vpn] Ready to forward traffic."

# Keep container running
exec tail -f /dev/null
