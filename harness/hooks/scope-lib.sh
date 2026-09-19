#!/bin/bash
# scope-lib.sh — 書き込み範囲の行列（正本）。edit-scope-gate.sh（Write / Edit）が source する。
# 行列を変えるときはここだけを変える。配置（スプリント文書の置き場・テスト・コンポーネントの src）は
# sprint.config.json から読む。文書上の正本は sprint-process.md の PROC-1。
#
#   scope_classify <path>          → state | spec | testmd | test | <component> | other
#   scope_decision  <actor> <type>  → deny | allow | unseal
#
# path は絶対でも作業ツリー相対でもよい。絶対パスはプロジェクトルート（`sprint_root`。呼び出し側が
# lib/env.sh を先に読む）の接頭辞を外してから判定する。外した後も絶対のまま（作業ツリー外。/tmp 等）なら other。
# 「/tmp/」の部分一致で作業ツリー外と見なさない。作業ツリー内の `<src>/tmp/x` を other に
# 誤判定し、fixture（/tmp 配下）に向けた hook が全パスを other と判定するためである。
# actor は agent_type（欠落・不明は main 扱い）。
# unseal は「TEST.md の <!-- UNSEAL --> ブロックだけ可」。edit-scope-gate.sh が引数で領域を判定する。
#
# 判定の順（D-5）: state → spec / testmd → other（docs/**）→ test（いずれかの tests に一致）
#   → <component>（いずれかの src に一致。コンポーネント名を返す）→ other

# 設定から判定表を 1 回の jq で取る（hook は 1 呼び出し 1 判定なので、jq の回数がそのまま遅延になる）。
# 呼び出し側は SCOPE_TABLE=$(_scope_table) を 1 回だけ実行して保持する。
#   行の形: <種別>\t<glob>   種別 = spec | testmd | test | <component>
#           role\t<component>\t<role>
# 表は <root>/.sprint/scope-table.cache に置き、設定より新しければそれを読む（jq の起動 1 回分を省く。
# hook は編集のたびに走る）。.sprint/ が無ければキャッシュしない。
_scope_table() {
  if [ -n "${SCOPE_TABLE:-}" ]; then printf '%s\n' "$SCOPE_TABLE"; return 0; fi
  local cfg cache
  cfg=$(sprint_config_path)
  cache="$(sprint_root)/.sprint/scope-table.cache"
  if [ -f "$cache" ] && [ "$cache" -nt "$cfg" ]; then printf '%s\n' "$(<"$cache")"; return 0; fi
  _scope_table_build "$cfg" | { if [ -d "${cache%/*}" ]; then tee "$cache"; else cat; fi; }
}

_scope_table_build() { # <config>
  jq -r '
    (.docs.sprintRoot) as $sr
    | ["spec\t\($sr)/**/SPEC.md", "testmd\t\($sr)/**/TEST.md"]
    + [ .components[] | (.tests // [])[] | "test\t\(.)" ]
    + [ .components | to_entries[] | .key as $c | (.value.src // [])[] | "\($c)\t\(.)" ]
    + [ .components | to_entries[] | "role\t\(.key)\t\(.value.role // "")" ]
    | .[]' "$1"
}

scope_classify() {
  local p="$1" root line kind glob
  root=$(sprint_root)
  case "$p" in "$root"/*) p="${p#"$root"/}" ;; esac
  case "$p" in
    /*) echo other; return ;;
    .sprint/flags.json|.sprint/spec-hashes.json) echo state; return ;;
  esac
  local table
  table=$(_scope_table)
  # 1. spec / testmd
  while IFS=$'\t' read -r kind glob; do
    case "$kind" in spec|testmd) sprint_glob_match "$glob" "$p" && { echo "$kind"; return; } ;; esac
  done <<<"$table"
  # 2. docs 配下の他のファイルはテストの拡張子でも other
  case "$p" in docs/*) echo other; return ;; esac
  # 3. test（いずれかのコンポーネントの tests に一致）
  while IFS=$'\t' read -r kind glob; do
    [ "$kind" = "test" ] && sprint_glob_match "$glob" "$p" && { echo test; return; }
  done <<<"$table"
  # 4. <component>（いずれかの src に一致）
  while IFS=$'\t' read -r kind glob; do
    case "$kind" in spec|testmd|test|role) continue ;; esac
    sprint_glob_match "$glob" "$p" && { echo "$kind"; return; }
  done <<<"$table"
  echo other
}

_scope_role() { # <component>
  local kind comp role
  while IFS=$'\t' read -r kind comp role; do
    [ "$kind" = "role" ] && [ "$comp" = "$1" ] && { echo "$role"; return 0; }
  done < <(_scope_table)
  echo ""
}

scope_decision() {
  local actor="$1" type="$2" role
  case "$type" in
    state)    echo deny ;;
    other)    echo allow ;;
    spec)     case "$actor" in main|"") echo allow ;; *) echo deny ;; esac ;;
    testmd)   case "$actor" in main|"") echo allow ;; qa) echo unseal ;; *) echo deny ;; esac ;;
    test)     case "$actor" in tester) echo allow ;; *) echo deny ;; esac ;;
    *)
      # コンポーネントの src: role が一致する呼び出し元だけ allow
      role=$(_scope_role "$type")
      if [ -n "$role" ] && [ "$actor" = "$role" ]; then echo allow; else echo deny; fi ;;
  esac
}

# 種別ごとの担当（deny 文で委譲先を示す）
scope_owner() {
  local role
  case "$1" in
    test)        echo "tester agent" ;;
    spec|testmd) echo "main" ;;
    state|other) echo "" ;;
    *)
      role=$(_scope_role "$1")
      [ -n "$role" ] && echo "$role agent" || echo "" ;;
  esac
}
