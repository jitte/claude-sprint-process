#!/bin/bash
# 仕様封印 (spec seal)
#
# <docs.sprintRoot>/**/SPEC.md・TEST.md の「封印領域」のハッシュを
# .sprint/spec-hashes.json に記録し、改変を検出する。
#
# 封印領域 = ファイル全体 − UNSEAL ブロック。
#   <!-- UNSEAL:BEGIN --> … <!-- UNSEAL:END --> の内側だけが可変。
#   UNSEAL マーカーが無いファイルは全体が封印領域。
#
# qa は manifest を書けず、封印領域も書けない（edit-scope-gate.sh が制御）。
# main が仕様を確定したら `bash harness/bin/sprint seal` で manifest を更新（＝承認）。
#
# サブコマンド:
#   seal              全対象ファイルを再ハッシュして manifest を更新
#   verify            manifest と現状を照合（不一致で exit 1）
#   list              対象ファイル一覧
#   hash-file <path>  指定ファイルの封印ハッシュを出力
#   hash-stdin        stdin の内容を封印ハッシュ化して出力
#   regions-unsealed <path>  封印外（可変）領域の内容を出力
#   manifest-get <path>      manifest 記録値を出力

set -euo pipefail
export PATH="${PATH:+$PATH:}/usr/local/bin:/usr/bin:/bin"   # 呼び出し元の PATH を優先し、hook の最小環境でも基本コマンドを保証する

. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
sprint_config_require
ROOT=$(sprint_root)
MANIFEST="$ROOT/.sprint/spec-hashes.json"
SPRINT_ROOT_DIR=$(sprint_abs_path "$(sprint_config '.docs.sprintRoot')")

# ファイルの「封印領域」を正規化して標準出力へ。
# UNSEAL ブロックの中身は除去するが、マーカー行は残す（位置を固定するため）。
_sealed_stream() {
  awk '
    /<!-- UNSEAL:BEGIN -->/ { print; skip=1; next }
    /<!-- UNSEAL:END -->/   { print; skip=0; next }
    skip==1 { next }
    { print }
  ' | sed 's/\r$//; s/[[:space:]]*$//'
}

# 封印外（UNSEAL ブロック内側）の内容を標準出力へ。
_unsealed_stream() {
  awk '
    /<!-- UNSEAL:BEGIN -->/ { skip=1; next }
    /<!-- UNSEAL:END -->/   { skip=0; next }
    skip==1 { print }
  '
}

_hash_stream() {
  _sealed_stream | sha256sum | cut -d' ' -f1
}

_rel() {
  # 絶対/相対パスを ROOT 相対へ
  local p="$1"
  case "$p" in
    /*) realpath --relative-to="$ROOT" "$p" 2>/dev/null || echo "$p" ;;
    *)  realpath --relative-to="$ROOT" "$ROOT/$p" 2>/dev/null || echo "$p" ;;
  esac
}

_targets() {
  find "$SPRINT_ROOT_DIR" \( -name SPEC.md -o -name TEST.md \) 2>/dev/null | sort
}

cmd="${1:-}"
case "$cmd" in
  hash-file)
    [ -f "$2" ] || { echo "no such file: $2" >&2; exit 2; }
    _hash_stream < "$2"
    ;;

  hash-stdin)
    _hash_stream
    ;;

  regions-unsealed)
    [ -f "$2" ] || exit 0
    _unsealed_stream < "$2"
    ;;

  manifest-get)
    [ -f "$MANIFEST" ] || { echo ""; exit 0; }
    rel=$(_rel "$2")
    jq -r --arg k "$rel" '.[$k] // ""' "$MANIFEST"
    ;;

  list)
    _targets | while read -r f; do _rel "$f"; done
    ;;

  seal)
    mkdir -p "$ROOT/.sprint"
    tmp=$(mktemp)
    echo '{}' > "$tmp"
    _targets | while read -r f; do
      rel=$(_rel "$f")
      h=$(_hash_stream < "$f")
      jq --arg k "$rel" --arg v "$h" '.[$k]=$v' "$tmp" > "$tmp.next" && mv "$tmp.next" "$tmp"
    done
    jq -S '.' "$tmp" > "$MANIFEST"
    rm -f "$tmp"
    echo "sealed $(jq 'length' "$MANIFEST") files -> ${MANIFEST#"$ROOT"/}"
    ;;

  verify)
    if [ ! -f "$MANIFEST" ]; then
      echo "FAIL: manifest がありません ($MANIFEST)。bash harness/bin/sprint seal を実行してください。" >&2
      exit 1
    fi
    fail=0
    # manifest の各エントリを照合
    while read -r rel; do
      [ -z "$rel" ] && continue
      f="$ROOT/$rel"
      if [ ! -f "$f" ]; then
        echo "FAIL: 封印対象が消えています: $rel" >&2
        fail=1
        continue
      fi
      want=$(jq -r --arg k "$rel" '.[$k]' "$MANIFEST")
      got=$(_hash_stream < "$f")
      if [ "$want" != "$got" ]; then
        echo "FAIL: 封印領域が改変されています: $rel" >&2
        fail=1
      fi
    done < <(jq -r 'keys[]' "$MANIFEST")
    # manifest 未登録の対象ファイルを警告
    while read -r f; do
      rel=$(_rel "$f")
      if ! jq -e --arg k "$rel" 'has($k)' "$MANIFEST" >/dev/null; then
        echo "WARN: 未封印の仕様ファイル: ${rel}（bash harness/bin/sprint seal で封印してください）" >&2
        fail=1
      fi
    done < <(_targets)
    if [ "$fail" -ne 0 ]; then
      exit 1
    fi
    echo "spec-verify: OK ($(jq 'length' "$MANIFEST") files)"
    ;;

  *)
    echo "usage: spec-seal.sh {seal|verify|list|hash-file <p>|hash-stdin|regions-unsealed <p>|manifest-get <p>}" >&2
    exit 2
    ;;
esac
