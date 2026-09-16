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
KEEP=3

if [[ "${1:-}" == "--rollback" ]]; then
  ssh "$HOST" "set -e; cd '$RELEASES'
    cur=\$(readlink current); prev=\$(ls -1dt */ | sed 's|/\$||' | grep -vx \"\$(basename \$cur)\" | head -1)
    [ -n \"\$prev\" ] || { echo 'no previous release' >&2; exit 1; }
    ln -sfn \"$RELEASES/\$prev\" current.new && mv -T current.new current && echo \"current -> \$prev\""
  exit 0
fi

DRY=0
if [[ "${1:-}" == "--dry-run" ]]; then DRY=1; shift; fi
SRC="${1:-dist/lab}"
[[ -f "$SRC/index.html" && -d "$SRC/data" ]] || { echo "no export at $SRC (run city.demo.stuttgart/export-static!)" >&2; exit 1; }

REL="$(git rev-parse --short HEAD)-$(date -u +%Y%m%dT%H%M%SZ)"
SCRATCH="${XDG_CACHE_HOME:-$HOME/.cache}/city-deploy"
STAGE="$SCRATCH/$REL"
mkdir -p "$STAGE"
cp -r "$SRC"/. "$STAGE"/
find "$STAGE" -type f \( -name '*.json' -o -name '*.js' -o -name '*.css' -o -name '*.html' -o -name '*.svg' -o -name '*.txt' \) \
     -size +1k -exec gzip -k -9 -n {} \;
(cd "$STAGE" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
echo "staged $REL: $(find "$STAGE" -type f | wc -l) files, $(du -sh --apparent-size "$STAGE" | cut -f1)"
if [[ $DRY -eq 1 ]]; then echo "dry run: $STAGE"; exit 0; fi

ssh "$HOST" "mkdir -p '$RELEASES/$REL'"
rsync -a --chmod=D755,F644 "$STAGE"/ "$HOST:$RELEASES/$REL/"
ssh "$HOST" "set -e; cd '$RELEASES/$REL' && sha256sum --quiet -c SHA256SUMS
  cd '$RELEASES' && ln -sfn '$RELEASES/$REL' current.new && mv -T current.new current
  ls -1dt */ | sed 's|/\$||' | tail -n +$((KEEP + 1)) | xargs -r rm -rf
  echo \"current -> $REL\""
rm -rf "$STAGE"
