#!/bin/bash
# api-routes.sh — 実装の公開ルート集合と仕様が書くルート集合を双方向に比較する。
#
# 仕様側の置き場は設定の docs.specDir、実装側の集合を出すコマンドは設定の sets.routes.implCmd。
#
# **本スクリプトはルート名を一切持たない。** 除外・展開の規則は仕様側の
# ```api-routes フェンス宣言（expand / alias）と、ルート名に依存しない
# 正規化規則だけで表現する。
#
# サブコマンド:
#   impl    正規化済みの実装ルートを 1 行 1 件で出す
#   spec    正規化・展開済みの仕様ルートを 1 行 1 件で出す
#   verify  双方向の差分を出す。0=一致 / 1=実装にあって仕様に無い / 2=仕様にあって実装に無い
#
# 環境変数:
#   API_ROUTES_ROOT      仕様スキャンの起点（既定: リポジトリルート）。
#                        配下の <docs.specDir>/**/*.md（README.md 除く）を読む
#   API_ROUTES_IMPL_CMD  実装ルート JSON を出すコマンド（既定: 設定の sets.routes.implCmd。プロジェクトルートで bash -c する）
#
# 失敗時のメッセージは **標準出力**に書く（ゲートの出力に残すため）。
set -uo pipefail

. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
sprint_config_require
REPO_ROOT=$(sprint_root)
ROOT="${API_ROUTES_ROOT:-$REPO_ROOT}"
SPEC_REL=$(sprint_config '.docs.specDir')
case "$SPEC_REL" in /*) SPEC_DIR="$SPEC_REL" ;; *) SPEC_DIR="$ROOT/$SPEC_REL" ;; esac
IMPL_CMD="${API_ROUTES_IMPL_CMD:-$(sprint_config '.sets.routes.implCmd // empty')}"
[ -n "$IMPL_CMD" ] || { echo "api-routes: 実装ルートの取得コマンドが無い（API_ROUTES_IMPL_CMD または設定の sets.routes.implCmd）"; exit 4; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

die() { echo "$*"; exit 1; }

usage() {
  echo "usage: api-routes.sh <impl|spec|verify>"
  exit 1
}

# --------------------------------------------------------------------------
# 仕様側の走査
# --------------------------------------------------------------------------

# 05 配下の Markdown を走査し、宣言行とルート出現を取り出す。
#   D <TAB> file <TAB> lineno <TAB> 宣言行        （```api-routes フェンス内）
#   R <TAB> file <TAB> lineno <TAB> METHOD <TAB> path
# ```mermaid フェンス内（N-3.4）と ```api-routes フェンス内（N-5.7）は
# ルート抽出の対象にしない。
# 走査の前提を確かめる。**呼び出し側がリダイレクトする関数の外で行う。**
# scan_spec_files の中で die すると、メッセージが走査結果と一緒に
# ファイルへ吸い込まれて消える（E-1.1 と同じ型の握り潰し）。
check_spec_dir() {
  [ -d "$SPEC_DIR" ] || die "api-routes: 仕様ディレクトリがありません: $SPEC_DIR"
  [ -n "$(find "$SPEC_DIR" -type f -name '*.md' ! -name 'README.md' | head -n 1)" ] \
    || die "api-routes: 仕様 Markdown が 1 件もありません: $SPEC_DIR"
}

scan_spec_files() {
  local files
  files=$(find "$SPEC_DIR" -type f -name '*.md' ! -name 'README.md' | LC_ALL=C sort)

  # shellcheck disable=SC2086
  echo "$files" | while IFS= read -r f; do
    awk '
      function trim(s) { sub(/^[ \t]+/, "", s); sub(/[ \t]+$/, "", s); return s }
      {
        t = trim($0)
        if (t ~ /^```/) {
          if (infence) { infence = 0; info = "" }
          else {
            infence = 1
            info = t
            sub(/^`+/, "", info)
            info = trim(info)
            n = split(info, w, /[ \t]/)
            info = (n > 0 ? w[1] : "")
          }
          next
        }
        if (infence && info == "mermaid") next
        if (infence && info == "api-routes") {
          d = trim($0)
          if (d != "") printf "D\t%s\t%d\t%s\n", FILENAME, FNR, d
          next
        }

        # N-2.1 / N-2.1a: <METHOD> <path>。path は / + 英字で始まり、
        # 文字集合 A-Z a-z 0-9 / : { } _ . - * の最長一致で切る。
        s = $0
        while (match(s, /(GET|POST|PUT|PATCH|DELETE)[ \t]+\/[A-Za-z][A-Za-z0-9\/:{}_.*-]*/)) {
          # メソッド名が語の途中（TARGET など）に埋もれている場合は採らない
          if (RSTART > 1) {
            pc = substr(s, RSTART - 1, 1)
            if (pc ~ /[A-Za-z0-9]/) { s = substr(s, RSTART + 1); continue }
          }
          tok = substr(s, RSTART, RLENGTH)
          s = substr(s, RSTART + RLENGTH)
          split(tok, m, /[ \t]+/)
          printf "R\t%s\t%d\t%s\t%s\n", FILENAME, FNR, m[1], m[2]
        }
      }
    ' "$f"
  done
}

# --------------------------------------------------------------------------
# 正規化（N-3.1 / N-3.2 / N-2.4）
# --------------------------------------------------------------------------

# stdin/stdout で 1 パス 1 行を正規化する。
#   - 末尾の . , を落とす（散文中の句読点）
#   - /api/v1 プレフィックスを外す
#   - パスパラメータ /:xxx を /:p に畳む
normalize_path() {
  awk '{
    p = $0
    sub(/[.,]+$/, "", p)
    sub(/^\/api\/v1/, "", p)
    if (p == "") p = "/"
    gsub(/\/:[A-Za-z0-9_]+/, "/:p", p)
    print p
  }'
}

norm_one() { printf '%s\n' "$1" | normalize_path; }

# --------------------------------------------------------------------------
# 宣言の読み取り（§3）
# --------------------------------------------------------------------------

read_declarations() {
  check_spec_dir
  scan_spec_files > "$WORK/raw"

  : > "$WORK/expand"
  : > "$WORK/alias"

  # N-5.5 / E-1.2: 語彙と文法の検査。
  # **語だけでなく文法も見る。** 語が正しく形が壊れた宣言（`=` や `->` の
  # 書き落とし）を黙って捨てると、展開されないプレースホルダが
  # 「仕様にあって実装に無い」として現れ、失敗分類 2（実装）へ誤誘導する。
  # 原因は宣言の書き間違いであり、BUILD に戻すのは誤りである。
  local bad
  bad=$(awk -F'\t' -v root="$ROOT/" '
    function rel(p,   n) { n = length(root); return (substr(p, 1, n) == root) ? substr(p, n + 1) : p }
    function bad(f, l, msg) { printf "%s:%s: %s\n", rel(f), l, msg }
    $1 == "D" {
      split($4, w, /[ \t]+/)
      if (w[1] != "expand" && w[1] != "alias") {
        bad($2, $3, sprintf("未知の宣言語 '\''%s'\''（使える語は expand / alias だけです）", w[1]))
        next
      }
      if (w[1] == "expand") {
        line = $4; sub(/^expand[ \t]+/, "", line)
        eq = index(line, "=")
        if (eq == 0) { bad($2, $3, "expand 宣言に '\''='\'' がありません（expand <placeholder> = <値>, <値>）"); next }
        ph = substr(line, 1, eq - 1); vals = substr(line, eq + 1)
        gsub(/^[ \t]+|[ \t]+$/, "", ph); gsub(/^[ \t]+|[ \t]+$/, "", vals)
        if (ph == "")   bad($2, $3, "expand 宣言のプレースホルダが空です")
        if (vals == "") bad($2, $3, "expand 宣言の値が空です")
        next
      }
      line = $4; sub(/^alias[ \t]+/, "", line)
      arrow = index(line, "->")
      if (arrow == 0) { bad($2, $3, "alias 宣言に '\''->'\'' がありません（alias <METHOD> <実装のパス> -> <仕様のパス>）"); next }
      left = substr(line, 1, arrow - 1); right = substr(line, arrow + 2)
      gsub(/^[ \t]+|[ \t]+$/, "", left); gsub(/^[ \t]+|[ \t]+$/, "", right)
      n = split(left, l, /[ \t]+/)
      if (n != 2)                bad($2, $3, "alias 宣言の左辺が <METHOD> <パス> の形ではありません: '\''" left "'\''")
      else if (l[2] !~ /^\//)    bad($2, $3, "alias 宣言の実装パスが '\''/'\'' で始まっていません: '\''" l[2] "'\''")
      if (right !~ /^\//)        bad($2, $3, "alias 宣言の仕様パスが '\''/'\'' で始まっていません: '\''" right "'\''")
    }
  ' "$WORK/raw")
  if [ -n "$bad" ]; then
    echo 'api-routes: api-routes フェンスの宣言が読めません'
    echo "$bad"
    exit 1
  fi

  # expand <placeholder> = v1, v2, ...  →  "<placeholder>\t<v1,v2,...>"
  awk -F'\t' '
    $1 == "D" && $4 ~ /^expand[ \t]/ {
      line = $4
      sub(/^expand[ \t]+/, "", line)
      eq = index(line, "=")
      if (eq == 0) next
      ph = substr(line, 1, eq - 1)
      vals = substr(line, eq + 1)
      sub(/^[ \t]+/, "", ph);   sub(/[ \t]+$/, "", ph)
      sub(/^[ \t]+/, "", vals); sub(/[ \t]+$/, "", vals)
      printf "%s\t%s\n", ph, vals
    }
  ' "$WORK/raw" > "$WORK/expand"

  # alias <METHOD> <実装パス> -> <仕様パス>  →  "<METHOD> <impl>\t<METHOD> <spec>"（正規化済み）
  awk -F'\t' '
    $1 == "D" && $4 ~ /^alias[ \t]/ {
      line = $4
      sub(/^alias[ \t]+/, "", line)
      arrow = index(line, "->")
      if (arrow == 0) next
      left  = substr(line, 1, arrow - 1)
      right = substr(line, arrow + 2)
      sub(/[ \t]+$/, "", left)
      sub(/^[ \t]+/, "", right); sub(/[ \t]+$/, "", right)
      split(left, l, /[ \t]+/)
      printf "%s\t%s\t%s\n", l[1], l[2], right
    }
  ' "$WORK/raw" > "$WORK/alias_raw"

  : > "$WORK/alias"
  while IFS=$'\t' read -r a_method a_impl a_spec; do
    [ -n "${a_method:-}" ] || continue
    printf '%s %s\t%s %s\n' "$a_method" "$(norm_one "$a_impl")" \
                            "$a_method" "$(norm_one "$a_spec")" >> "$WORK/alias"
  done < "$WORK/alias_raw"
}

# --------------------------------------------------------------------------
# 仕様ルートの構築（N-2.x / N-3.x / N-5.2）
# --------------------------------------------------------------------------

# 結果を $WORK/spec_routes に書く（"<METHOD> <path>\t<file>:<line>"、重複は先勝ち）。
# **関数の stdout はエラーメッセージ専用にする。** 呼び出し側でリダイレクトすると
# 失敗の理由が握り潰されるため、結果は必ずファイルに置く。
build_spec_routes() {
  # N-3.3: * を含むパスは除外する（総称表記）
  awk -F'\t' -v root="$ROOT/" '
    # ROOT を正規表現として使わない。パスにメタ文字が含まれると相対化が壊れる
    function rel(p,   n) { n = length(root); return (substr(p, 1, n) == root) ? substr(p, n + 1) : p }
    $1 == "R" {
      p = $5
      sub(/[.,]+$/, "", p)
      if (index(p, "*") > 0) next
      sub(/^\/api\/v1/, "", p)
      if (p == "") p = "/"
      gsub(/\/:[A-Za-z0-9_]+/, "/:p", p)
      printf "%s %s\t%s:%s\n", $4, p, rel($2), $3
    }
  ' "$WORK/raw" > "$WORK/spec_pre"

  # N-5.2 / N-5.4 / E-1.3: expand 宣言の適用と空振り検査
  cp "$WORK/spec_pre" "$WORK/spec_exp"
  while IFS=$'\t' read -r ph vals; do
    [ -n "${ph:-}" ] || continue
    if ! grep -qF -- "$ph" "$WORK/spec_exp"; then
      echo "api-routes: expand 宣言が空振りしています: '$ph' を含む仕様ルートが 1 件もありません"
      exit 1
    fi
    awk -v ph="$ph" -v vals="$vals" '
      function replace_all(s, from, to,   out, p) {
        out = ""
        while ((p = index(s, from)) > 0) {
          out = out substr(s, 1, p - 1) to
          s = substr(s, p + length(from))
        }
        return out s
      }
      {
        if (index($0, ph) == 0) { print; next }
        n = split(vals, V, ",")
        for (i = 1; i <= n; i++) {
          v = V[i]
          sub(/^[ \t]+/, "", v); sub(/[ \t]+$/, "", v)
          if (v == "") continue
          print replace_all($0, ph, v)
        }
      }
    ' "$WORK/spec_exp" > "$WORK/spec_exp.new" || exit 1
    mv "$WORK/spec_exp.new" "$WORK/spec_exp"
  done < "$WORK/expand"

  LC_ALL=C sort -t$'\t' -k1,1 -k2,2 "$WORK/spec_exp" | awk -F'\t' '!seen[$1]++' > "$WORK/spec_routes"
}

# --------------------------------------------------------------------------
# 実装ルートの構築（N-1.x / N-5.3 / E-1.1 / E-1.4）
# --------------------------------------------------------------------------

# 結果を $WORK/impl_routes に書く。build_spec_routes と同じ理由で stdout は
# エラーメッセージ専用にする（E-1.1 の「原因を出す」が呼び出し側の
# リダイレクトで消えないこと）。
build_impl_routes() {
  local out="$WORK/impl_stdout" err="$WORK/impl_stderr"
  if ! (cd "$REPO_ROOT" && bash -c "$IMPL_CMD") > "$out" 2> "$err"; then
    echo "api-routes: 実装ルートの取得に失敗しました（API_ROUTES_IMPL_CMD）"
    echo "  cmd: $IMPL_CMD"
    cat "$err"
    exit 1
  fi

  if ! jq -e 'type == "array"' "$out" > /dev/null 2>&1; then
    echo "api-routes: 実装ルートの出力が JSON 配列ではありません"
    echo "  cmd: $IMPL_CMD"
    head -c 2000 "$out"
    exit 1
  fi

  jq -r '.[] | "\(.method) \(.path)"' "$out" | awk '{
    p = $2
    sub(/^\/api\/v1/, "", p)
    if (p == "") p = "/"
    gsub(/\/:[A-Za-z0-9_]+/, "/:p", p)
    print $1 " " p
  }' | LC_ALL=C sort -u > "$WORK/impl_pre"

  # E-1.4: alias の実装側パスが実在しないなら fail（互換ルートを消したのに宣言が残る状態）
  cp "$WORK/impl_pre" "$WORK/impl_mapped"
  while IFS=$'\t' read -r from to; do
    [ -n "${from:-}" ] || continue
    if ! grep -qxF -- "$from" "$WORK/impl_pre"; then
      echo "api-routes: alias 宣言が空振りしています: 実装ルートに '$from' がありません"
      exit 1
    fi
    awk -v from="$from" -v to="$to" '$0 == from { print to; next } { print }' \
      "$WORK/impl_mapped" > "$WORK/impl_mapped.new" || exit 1
    mv "$WORK/impl_mapped.new" "$WORK/impl_mapped"
  done < "$WORK/alias"

  LC_ALL=C sort -u "$WORK/impl_mapped" > "$WORK/impl_routes"
}

# --------------------------------------------------------------------------
# サブコマンド
# --------------------------------------------------------------------------

cmd_spec() {
  read_declarations
  build_spec_routes
  cut -d$'\t' -f1 "$WORK/spec_routes"
}

cmd_impl() {
  read_declarations
  build_impl_routes
  cat "$WORK/impl_routes"
}

cmd_verify() {
  read_declarations

  # 実装側を先に取る。取得に失敗したら空集合として扱わず、そこで止める（E-1.1）。
  build_impl_routes
  build_spec_routes

  cut -d$'\t' -f1 "$WORK/spec_routes" | LC_ALL=C sort -u > "$WORK/spec_set"
  LC_ALL=C sort -u "$WORK/impl_routes" > "$WORK/impl_set"

  LC_ALL=C comm -23 "$WORK/spec_set" "$WORK/impl_set" > "$WORK/spec_only"
  LC_ALL=C comm -13 "$WORK/spec_set" "$WORK/impl_set" > "$WORK/impl_only"

  local n_spec_only n_impl_only
  n_spec_only=$(wc -l < "$WORK/spec_only" | tr -d ' ')
  n_impl_only=$(wc -l < "$WORK/impl_only" | tr -d ' ')

  echo "=== 仕様にあって実装に無い（${n_spec_only} 件） ==="
  if [ "$n_spec_only" -gt 0 ]; then
    # N-4.4: 出所のファイル名と行番号を添える
    while IFS= read -r route; do
      local where
      where=$(awk -F'\t' -v r="$route" '$1 == r { print $2; exit }' "$WORK/spec_routes")
      echo "  $route  ($where)"
    done < "$WORK/spec_only"
  fi

  echo "=== 実装にあって仕様に無い（${n_impl_only} 件） ==="
  if [ "$n_impl_only" -gt 0 ]; then
    sed 's/^/  /' "$WORK/impl_only"
  fi

  echo "--- 仕様 $(wc -l < "$WORK/spec_set" | tr -d ' ') 件 / 実装 $(wc -l < "$WORK/impl_set" | tr -d ' ') 件 ---"

  # N-8.3: 実装にあって仕様に無い → 失敗分類 1（仕様）。上流なので優先する
  if [ "$n_impl_only" -gt 0 ]; then exit 1; fi
  # N-8.4: 仕様にあって実装に無い → 失敗分類 2（実装）
  if [ "$n_spec_only" -gt 0 ]; then exit 2; fi
  exit 0
}

case "${1:-}" in
  impl)   cmd_impl ;;
  spec)   cmd_spec ;;
  verify) cmd_verify ;;
  *)      usage ;;
esac
