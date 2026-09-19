#!/bin/sh
set -eu
umask 077
exec strato-mail-service \
  --options /data/options.json \
  --data-dir /data \
  --host 0.0.0.0 \
  --port 8098
