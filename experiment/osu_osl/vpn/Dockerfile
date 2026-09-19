FROM alpine:3.20

RUN apk add --no-cache \
    openvpn \
    iproute2 \
    bind-tools \
    netcat-openbsd \
    socat \
    dante-server \
    curl \
    bash

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
