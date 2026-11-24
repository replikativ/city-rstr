#!/usr/bin/env bash
# Executed on the release host after upload. Serialize pointer changes and pruning.
set -euo pipefail
cd -- "$1"
exec 9>.activation.lock
flock 9
release_name() { [[ "$1" =~ ^[0-9a-f]+-[0-9]{8}T[0-9]{6}Z$ ]]; }
pointer() {
  local target
  target=$(readlink "$1") || return 1
  basename -- "$target"
}
switch_to() {
  ln -sfn -- "$2" "$1.new"
  mv -Tf -- "$1.new" "$1"
}
old=$(pointer current || true)
if [[ -n "$old" ]]; then
  release_name "$old" && [[ -d "$old" ]] || { echo 'Unrecognized current release' >&2; exit 1; }
fi
release=$2
if [[ "$release" == --rollback ]]; then
  release=$(pointer previous) || { echo 'No recorded previous release' >&2; exit 1; }
fi
release_name "$release" && [[ ! -L "$release" && -d "$release" ]] || exit 1
[[ "$release" != "$old" ]] || exit 0
(cd -- "$release" && sha256sum --quiet -c SHA256SUMS)
if [[ -n "$old" ]]; then switch_to previous "$old"; fi
switch_to current "$release"
echo "current -> $release"
# Prune only previously activated releases. Uploads in progress remain untouched.
touch -- "$release/.activated"
kept=0
while read -r stamp dir; do
  name=${dir%/.activated}
  name=${name#./}
  release_name "$name" || continue
  [[ "$name" != "$release" && "$name" != "$old" ]] || continue
  if (( kept < 1 )); then kept=$((kept + 1)); else rm -rf -- "$name"; fi
done < <(find . -mindepth 2 -maxdepth 2 -type f -name .activated -printf '%T@ %p\n' | sort -nr)
