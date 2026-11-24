#!/usr/bin/env bash
# Deploy the static explorer to simm.is/city/ as a new release, separate from
# the website's releases.
#
#   deploy/deploy.sh [export-dir]      stage, upload, verify, switch `current`
#   deploy/deploy.sh --dry-run [dir]   stage and checksum locally only
#   deploy/deploy.sh --rollback        point `current` at the previous release
#
# A release is a folder <commit>-<UTC time> under $CITY_RELEASES on the host.
# Text files larger than 1 KB are shipped with a gzip twin, which Nginx serves
# with gzip_static (deploy/nginx-city.conf). Every file is checked on the host
# against the SHA-256 list made before upload, and only then does `current`
# move, atomically. The three newest releases are kept.
set -euo pipefail

HOST="${CITY_DEPLOY_HOST:-simmis@simm.is}"
RELEASES="${CITY_RELEASES:-/var/www/city-releases}"
SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd)

if [[ "${1:-}" == "--rollback" ]]; then
  ssh "$HOST" bash -s -- "$RELEASES" --rollback < "$SCRIPT_DIR/activate.sh"
  exit 0
fi

DRY=0
if [[ "${1:-}" == "--dry-run" ]]; then DRY=1; shift; fi
SRC="${1:-dist/city-previews/current}"
[[ -f "$SRC/index.html" && -f "$SRC/SHA256SUMS" && -d "$SRC/data" ]] || { echo "no export at $SRC (run npm run preview:bundle)" >&2; exit 1; }

REL="$(git rev-parse --short HEAD)-$(date -u +%Y%m%dT%H%M%SZ)"
SCRATCH="${XDG_CACHE_HOME:-$HOME/.cache}/city-deploy"
STAGE="$SCRATCH/$REL"
mkdir -p "$SCRATCH"
mkdir "$STAGE"
cp -r "$SRC"/. "$STAGE"/
(cd "$STAGE" && sha256sum --quiet -c SHA256SUMS)
find "$STAGE" -type f \( -name '*.json' -o -name '*.js' -o -name '*.css' -o -name '*.html' -o -name '*.svg' -o -name '*.txt' \) \
     -size +1k -exec gzip -k -9 -n {} +
(cd "$STAGE" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
echo "staged $REL: $(find "$STAGE" -type f | wc -l) files, $(du -sh --apparent-size "$STAGE" | cut -f1)"
if [[ $DRY -eq 1 ]]; then echo "dry run: $STAGE"; exit 0; fi

ssh "$HOST" "mkdir '$RELEASES/$REL'"
rsync -a --chmod=D755,F644 "$STAGE"/ "$HOST:$RELEASES/$REL/"
ssh "$HOST" bash -s -- "$RELEASES" "$REL" < "$SCRIPT_DIR/activate.sh"
rm -rf "$STAGE"
