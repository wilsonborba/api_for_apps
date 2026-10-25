#!/usr/bin/env bash
# Run after the tagged Rust release and return merges are complete.
set -euo pipefail
if [[ $(id -u) -ne 0 ]]; then echo 'Run this prepared cutover with sudo.' >&2; exit 1; fi
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
CANONICAL=$(cd "$SCRIPT_DIR/../../api_for_apps" && pwd)
RELEASE_REF=${1:?Usage: sudo scripts/cutover_rust.sh vX.Y.Z}
if [[ ! "$RELEASE_REF" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then echo 'An explicit release tag is required.' >&2; exit 1; fi
OWNER=$(stat -c %U "$CANONICAL")
git_owner() { runuser -u "$OWNER" -- git -C "$CANONICAL" "$@"; }
if [[ -n $(git_owner status --porcelain) ]]; then echo 'Canonical checkout has local changes; inspect before cutover.' >&2; exit 1; fi
git_owner rev-parse --verify "refs/tags/$RELEASE_REF" >/dev/null
git_owner merge-base --is-ancestor "$RELEASE_REF" feature/main
PREVIOUS_COMMIT=$(git_owner rev-parse HEAD)
# The owner has already tested the separate Rust worktree. Canonical Python
# remains on the previous tagged checkout until this explicit privileged step.
systemctl stop asodya-api.service
if git_owner switch feature/main && "$CANONICAL/scripts/install_service.sh"; then
  systemctl is-active --quiet asodya-api.service
  echo "Rust cutover complete: $RELEASE_REF"
else
  echo 'Cutover failed. Restoring the previous checkout and service.' >&2
  systemctl stop asodya-api.service || true
  git_owner switch --detach "$PREVIOUS_COMMIT"
  systemctl restart asodya-api.service
  exit 1
fi
