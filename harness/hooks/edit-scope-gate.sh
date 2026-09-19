#!/bin/bash
export PATH="${PATH:+$PATH:}/usr/local/bin:/usr/bin:/bin"   # 呼び出し元の PATH を優先し、hook の最小環境でも基本コマンドを保証する
# PreToolUse hook: edit scope gate
#
# Write/Edit の呼び出し元（agent_type。欠落は main）と編集対象 path の組み合わせで
# 範囲外の編集を deny する。行列は scope-lib.sh（正本）。本ファイル固有なのは
# qa の TEST.md に対する UNSEAL 領域の判定（Edit の old_string / Write の内容ハッシュを見る）だけ。
# Bash 経由の書き込みは判定しない。src / テストは Edit / Write で書く。
# sprint.config.json が無ければ判定せず素通りする（出力なし・exit 0）。

INPUT=$(cat)
HERE=$(readlink -f "$0"); HERE=${HERE%/*}
. "$HERE/../lib/env.sh"
sprint_config_exists || exit 0

# 入力の読み取りは jq 1 回。区切りは US（0x1f）。空欄（agent_type 無し）を落とさないため空白文字を使わない
IFS=$'\x1f' read -r TOOL_NAME AGENT_TYPE FILE_PATH < <(printf '%s' "$INPUT" | jq -r '[.tool_name, (.agent_type // ""), (.tool_input.file_path // "")] | join("\u001f")')
case "$TOOL_NAME" in Write|Edit) ;; *) exit 0 ;; esac

. "$HERE/scope-lib.sh"
SCOPE_TABLE=$(_scope_table)   # 判定表は 1 回だけ作る（scope_* が読む）

ACTOR="${AGENT_TYPE:-main}"

# deny の JSON は bash で組む（jq を 1 回減らす）。理由文の \ と " と改行だけをエスケープする
emit_deny() {
  local r="$1"
  r="${r//\\/\\\\}"; r="${r//\"/\\\"}"; r="${r//$'\n'/\\n}"
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$r"
  exit 0
}

TYPE=$(scope_classify "$FILE_PATH")
DECISION=$(scope_decision "$ACTOR" "$TYPE")

case "$DECISION" in
  allow) exit 0 ;;
  deny)
    case "$TYPE" in
      state)
        case "$FILE_PATH" in
          */spec-hashes.json) emit_deny "spec-hashes.json は生成物です。直接編集せず bash harness/bin/sprint seal で更新してください。" ;;
          *) emit_deny "flags.json は harness/bin/sprint 経由でのみ更新します（bash harness/bin/sprint stage 等）。直接編集はステージ skip 防止のため禁止です。" ;;
        esac ;;
      spec)
        case "$ACTOR" in
          qa) emit_deny "SPEC.md は backend/frontend の実装契約です。qa agent は読み取り専用です。" ;;
          *)  emit_deny "SPEC.md は main が起草する仕様です。${ACTOR} agent は読み取り専用です。" ;;
        esac ;;
      testmd) emit_deny "TEST.md は main が起草する仕様です。${ACTOR} agent は読み取り専用です。" ;;
      *) emit_deny "${ACTOR} は ${TYPE} code を編集できません (${FILE_PATH})。$(scope_owner "$TYPE") に委譲してください。" ;;
    esac ;;
esac

# ── unseal: qa × TEST.md。<!-- UNSEAL --> ブロック内だけ許可 ──
SEAL="$HERE/../tools/spec-seal.sh"
[ -f "$SEAL" ] || exit 0
UNSEALED=$(bash "$SEAL" regions-unsealed "$FILE_PATH" 2>/dev/null || true)
[ -n "$UNSEALED" ] || emit_deny "TEST.md は全体が封印されています。可変領域は <!-- UNSEAL:BEGIN/END --> で指定します。仕様変更は main に依頼してください。"
if [ "$TOOL_NAME" = "Edit" ]; then
  OLD=$(echo "$INPUT" | jq -r '.tool_input.old_string // ""')
  NEW=$(echo "$INPUT" | jq -r '.tool_input.new_string // ""')
  case "$OLD$NEW" in
    *"SEAL:BEGIN"*|*"SEAL:END"*) emit_deny "qa agent は封印マーカー (<!-- (UN)SEAL --> ) を編集できません。" ;;
  esac
  case "$UNSEALED" in
    *"$OLD"*) exit 0 ;;
    *) emit_deny "qa agent は TEST.md の封印領域を編集できません。可変領域 (<!-- UNSEAL --> 内) のみ編集可能です。仕様変更は main に依頼してください。" ;;
  esac
else
  CONTENT=$(echo "$INPUT" | jq -r '.tool_input.content // ""')
  NEWHASH=$(printf '%s\n' "$CONTENT" | bash "$SEAL" hash-stdin 2>/dev/null || true)
  CURHASH=$(bash "$SEAL" manifest-get "$FILE_PATH" 2>/dev/null || true)
  if [ -n "$CURHASH" ] && [ "$NEWHASH" != "$CURHASH" ]; then
    emit_deny "qa agent の Write は TEST.md の封印領域を変更します。可変領域のみ編集してください。"
  fi
fi
exit 0
