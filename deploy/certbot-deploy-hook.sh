#!/usr/bin/env bash
# certbot --deploy-hook: copy the renewed certificate into HELM_TLS_DIR (real files, not
# the live/ symlinks, readable by the non-root nginx user 101) and reload nginx.
#
#   sudo certbot certonly --webroot -w /opt/helm-marine/deploy/certbot-www -d DOMAIN \
#     --deploy-hook /opt/helm-marine/deploy/certbot-deploy-hook.sh
#
# Env: HELM_APP_DIR (default /opt/helm-marine), HELM_TLS_DIR (default $HELM_APP_DIR/deploy/certs).
# certbot sets RENEWED_LINEAGE to /etc/letsencrypt/live/DOMAIN.
set -euo pipefail
app_dir="${HELM_APP_DIR:-/opt/helm-marine}"
tls_dir="${HELM_TLS_DIR:-$app_dir/deploy/certs}"
lineage="${RENEWED_LINEAGE:?run from certbot (RENEWED_LINEAGE is not set)}"

install -d -m 0750 -g 101 "$tls_dir"
install -m 0644 "$lineage/fullchain.pem" "$tls_dir/fullchain.pem"
install -m 0640 -g 101 "$lineage/privkey.pem" "$tls_dir/privkey.pem"

if docker compose --env-file "$app_dir/.env.prod" -f "$app_dir/docker-compose.prod.yml" ps --status running --services | grep -qx web; then
  docker compose --env-file "$app_dir/.env.prod" -f "$app_dir/docker-compose.prod.yml" exec -T web nginx -s reload
fi
echo "certificate installed in $tls_dir"
