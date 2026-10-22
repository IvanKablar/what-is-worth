#!/usr/bin/env bash
# Freigabe: exportiert den letzten Commit nach ~/.local/share/what-is-worth/app.
# Statusline und der Befehl `wiw` laufen nur aus dieser Kopie, damit halbfertige
# Änderungen im Arbeitsstand nie live ausgeführt werden.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
base="${WIW_DATA_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/what-is-worth}"
sha="$(git -C "$repo" rev-parse --short HEAD)"
target="$base/app-$sha"
if ! git -C "$repo" diff --quiet HEAD -- src bin; then
  echo "Hinweis: nicht committete Änderungen in src/ oder bin/ werden nicht freigegeben." >&2
fi
rm -rf "$target" && mkdir -p "$target"
git -C "$repo" archive HEAD src bin | tar -x -C "$target"
ln -sfn "app-$sha" "$base/app.new" && mv -T "$base/app.new" "$base/app"
find "$base" -maxdepth 1 -name 'app-*' ! -name "app-$sha" -exec rm -rf {} +
echo "Freigegeben: $sha -> $base/app"
