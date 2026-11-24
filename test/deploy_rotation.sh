#!/usr/bin/env bash
set -euo pipefail
root=$(mktemp -d)
trap 'rm -rf -- "$root"' EXIT
for n in 01 02 03 04; do
  release="abcd123-20261123T1200${n}Z"
  mkdir "$root/$release"
  echo "$n" > "$root/$release/index.html"
  (cd "$root/$release" && sha256sum index.html > SHA256SUMS)
  bash deploy/activate.sh "$root" "$release"
done
test ! -d "$root/abcd123-20261123T120001Z"
bash deploy/activate.sh "$root" --rollback
test "$(readlink "$root/current")" = abcd123-20261123T120003Z
echo corrupt > "$root/previous/index.html"
if bash deploy/activate.sh "$root" --rollback; then exit 1; fi
test "$(readlink "$root/current")" = abcd123-20261123T120003Z
