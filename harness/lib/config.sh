#!/bin/bash
# harness/lib/config.sh — sprint.config.json の読み取り（正本）。
#
# ハーネス本体（lib / tools / gate-tools / hooks / bin）はコンポーネント・配置・タスク・
# 証跡・集合・ゲートをすべてここ経由で読む。技術名と配置を本体に書かない。
# 先に sprint_root（env.sh）が定義されていること。env.sh が本ファイルを読むので、
# 呼び出し側は env.sh だけを読めばよい。
#
# 環境変数:
#   SPRINT_CONFIG   設定ファイルのパス（省略時 <sprint_root>/sprint.config.json）
#
# 関数:
#   sprint_config_path                 設定ファイルのパス
#   sprint_config_check                設定の存在と schemaVersion を検査する。不合格なら理由を 1 行出して 4
#   sprint_config_require              sprint_config_check に失敗したら理由を出して exit 4（bin / gate-tools 用）
#   sprint_config_exists               設定があれば 0（hooks の素通り判定用）
#   sprint_config <jq フィルタ>         jq -r の結果を出す
#   sprint_config_json <jq フィルタ>    jq -c の結果を出す
#   sprint_abs_path <path>             絶対ならそのまま、相対なら <sprint_root>/ を付ける
#   sprint_glob_regex <glob>           glob を正規表現に変換する（** → 任意の階層、* / ? は階層をまたがない）
#   sprint_glob_match <glob> <path>    一致で 0 / 不一致で 1
#   sprint_glob_files [-r <root>] <glob>...   glob に一致するファイルを <root> 相対で列挙する
#                                      （<root>/.gitignore にディレクトリ名（例 `name/`）として書かれた配下は除く）
#   sprint_ignored_dirs [root]         走査から除くディレクトリ名（.gitignore の `name/` 行）
#   sprint_components                  コンポーネント名を設定の並び順で出す
#   sprint_tasks                       動詞を tasks の順で出す
#   sprint_required_tasks              「<component> <task>」を tasks の順 × コンポーネントの順で出す
#   sprint_component_globs <src|tests> [component]   glob を 1 行 1 つで出す（component 省略時は全部）

sprint_config_path() {
  printf '%s\n' "${SPRINT_CONFIG:-$(sprint_root)/sprint.config.json}"
}

sprint_config_check() {
  local p v
  p=$(sprint_config_path)
  [ -f "$p" ] || { echo "sprint.config.json が無い: $p"; return 4; }
  v=$(jq -r '.schemaVersion // "null"' "$p" 2>/dev/null) || v="null"
  [ "$v" = "1" ] || { echo "sprint.config.json の schemaVersion $v は対応外（対応 1）"; return 4; }
  return 0
}

sprint_config_require() {
  local out
  out=$(sprint_config_check) || { echo "$out"; exit 4; }
}

# hooks の素通り判定。1 呼び出し 1 判定の hook で jq を増やさないよう、ファイルの有無と
# schemaVersion の行だけを見る（値の検査は sprint_config_check）。
sprint_config_exists() {
  local p body
  p=$(sprint_config_path)
  [ -f "$p" ] || return 1
  body=$(<"$p")
  [[ "$body" =~ \"schemaVersion\"[[:space:]]*:[[:space:]]*1[[:space:]]*(,|$|\}) ]]
}

sprint_config() { # <jq フィルタ>
  jq -r "$1" "$(sprint_config_path)"
}

sprint_config_json() { # <jq フィルタ>
  jq -c "$1" "$(sprint_config_path)"
}

sprint_abs_path() { # <path>
  case "$1" in
    /*) printf '%s\n' "$1" ;;
    *)  printf '%s\n' "$(sprint_root)/$1" ;;
  esac
}

# glob → 正規表現。規則は config.py の glob_match と同じ。
#   **/  → (.*/)?   （0 個以上のディレクトリ）
#   **   → .*
#   *    → [^/]*
#   ?    → [^/]
#   .    → \.       （その他の記号もエスケープする）
# 変換結果は変数 SPRINT_GLOB_RE にも置く（hook の判定で毎回サブシェルを作らないため）。
sprint_glob_regex() { # <glob>
  local g="$1" out="" i c
  local n=${#g}
  i=0
  while [ "$i" -lt "$n" ]; do
    c="${g:$i:1}"
    if [ "$c" = "*" ] && [ "${g:$((i+1)):1}" = "*" ]; then
      if [ "${g:$((i+2)):1}" = "/" ]; then
        out+='(.*/)?'; i=$((i+3))
      else
        out+='.*'; i=$((i+2))
      fi
      continue
    fi
    case "$c" in
      '*') out+='[^/]*' ;;
      '?') out+='[^/]' ;;
      '.'|'+'|'('|')'|'['|']'|'{'|'}'|'^'|'$'|'|'|'\') out+="\\$c" ;;
      *) out+="$c" ;;
    esac
    i=$((i+1))
  done
  SPRINT_GLOB_RE="^$out\$"
  printf '%s\n' "$SPRINT_GLOB_RE"
}

sprint_glob_match() { # <glob> <path>
  sprint_glob_regex "$1" >/dev/null
  [[ "$2" =~ $SPRINT_GLOB_RE ]]
}

# glob の固定接頭辞（最初のワイルドカードを含むセグメントの手前まで）。走査の起点に使う。
_sprint_glob_prefix() { # <glob>
  local g="$1" seg out="" IFS='/'
  local -a parts
  read -r -a parts <<<"$g"
  for seg in "${parts[@]}"; do
    case "$seg" in *'*'*|*'?'*|*'['*) break ;; esac
    out+="${seg}/"
  done
  printf '%s\n' "${out%/}"
}

# 版管理から除外したディレクトリ（依存物・生成物の置き場）は走査しない。名前は <root>/.gitignore の
# `name/` 形式の行（ワイルドカードと中間の / を含まない）から取る。ツールが名前を持たない。
sprint_ignored_dirs() { # [root]
  local root="${1:-$(sprint_root)}" line
  [ -f "$root/.gitignore" ] || return 0
  while IFS= read -r line; do
    line="${line%%#*}"; line="${line%"${line##*[![:space:]]}"}"
    case "$line" in ''|'!'*|*'*'*|*'?'*|*'['*|/*) continue ;; esac
    case "$line" in */) line="${line%/}" ;; *) continue ;; esac
    case "$line" in */*) continue ;; esac
    printf '%s\n' "$line"
  done < "$root/.gitignore"
}

sprint_glob_files() { # [-r <root>] <glob>...
  local root
  root=$(sprint_root)
  if [ "${1:-}" = "-r" ]; then root="$2"; shift 2; fi
  local g prefix re base d
  local -a prune=()
  while IFS= read -r d; do [ -n "$d" ] && prune+=(-name "$d" -prune -o); done < <(sprint_ignored_dirs "$root")
  for g in "$@"; do
    prefix=$(_sprint_glob_prefix "$g")
    base="$root${prefix:+/$prefix}"
    [ -d "$base" ] || continue
    re=$(sprint_glob_regex "$g")
    find "$base" \( "${prune[@]}" -type f -print \) 2>/dev/null \
      | sed "s|^$root/||" | grep -E "$re" || true
  done | sort -u
}

sprint_components() {
  sprint_config '.components | keys_unsorted[]'
}

sprint_tasks() {
  sprint_config '.tasks[]'
}

sprint_required_tasks() {
  jq -r '.tasks[] as $t | .components | to_entries[] | select(.value.adapters[$t] != null) | "\(.key) \($t)"' \
    "$(sprint_config_path)"
}

sprint_component_globs() { # <src|tests> [component]
  local kind="$1" c="${2:-}"
  if [ -n "$c" ]; then
    jq -r --arg c "$c" --arg k "$kind" '.components[$c][$k] // [] | .[]' "$(sprint_config_path)"
  else
    jq -r --arg k "$kind" '.components[] | .[$k] // [] | .[]' "$(sprint_config_path)"
  fi
}
