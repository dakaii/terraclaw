# ZeroClaw + Litestream for durable SQLite on ephemeral Cloud Run disks.
# https://litestream.io/guides/gcs/

# ZeroClaw requires rust-version >= 1.87 (see upstream Cargo.toml).
FROM rust:1-bookworm AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake pkg-config libssl-dev git clang \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
ARG ZEROCLAW_REF=master
RUN git clone --depth 1 --branch "${ZEROCLAW_REF}" https://github.com/zeroclaw-labs/zeroclaw.git .

# Release build (may take 15–30+ minutes on first run).
ENV RUSTFLAGS="-C target-cpu=generic"
RUN cargo build --release

FROM debian:bookworm-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

ARG LITESTREAM_VERSION=0.3.13
RUN curl -fsSL "https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-v${LITESTREAM_VERSION}-linux-amd64.tar.gz" \
    | tar -xz -C /usr/local/bin litestream

COPY --from=builder /src/target/release/zeroclaw /usr/local/bin/zeroclaw
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh /usr/local/bin/zeroclaw

ENV HOME=/data \
    ZEROCLAW_WORKSPACE=/data/workspace

RUN mkdir -p /data/workspace

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
# Port is set at runtime (Cloud Run injects PORT).
