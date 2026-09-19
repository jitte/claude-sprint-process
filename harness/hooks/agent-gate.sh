#!/bin/bash
# PreToolUse hook: Sprint stage-based agent gate
#
# .sprint/flags.json の active スプリントの stage に応じてエージェント起動を許可/拒否。
# 書き込み制約は edit-scope-gate.sh（scope-lib.sh の行列）が判定する。
# sprint.config.json が無ければ判定せず素通りする（出力なし・exit 0）。

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name')

[ "$TOOL_NAME" != "Agent" ] && exit 0

# deny は最初の呼び出しより前に定義する（flags.json 欠損時の早期 deny で使う）
deny() {
  echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"$1\"}}"
  exit 0
}

. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
sprint_config_exists || exit 0
SUBAGENT_TYPE=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // ""')

# 情報収集系エージェントは常に許可
case "$SUBAGENT_TYPE" in
  Explore|general-purpose|claude-code-guide|Plan|statusline-setup|"") exit 0 ;;
esac

FLAGS="$(sprint_root)/.sprint/flags.json"

# flags.json が無い or active 未設定 → エージェント起動不可
if [ ! -f "$FLAGS" ]; then
  deny "スプリントが設定されていません。.sprint/flags.json を作成してください。"
fi

ACTIVE=$(jq -r '.active // ""' "$FLAGS")

if [ -z "$ACTIVE" ]; then
  deny "active スプリントが未設定です。flags.json の active を設定してください。"
fi

STAGE=$(jq -r --arg id "$ACTIVE" '.sprints[$id].stage // ""' "$FLAGS")
STATUS=$(jq -r --arg id "$ACTIVE" '.sprints[$id].status // ""' "$FLAGS")

if [ -z "$STAGE" ]; then
  deny "スプリント ${ACTIVE} の stage が未設定です。"
fi

# ステージ別の許可判定

ALLOWED=""
case "$STAGE" in
  PLAN)
    deny "${STAGE} ステージではエージェントを起動できません。main が直接作業してください。" ;;
  SHIP)
    case "$SUBAGENT_TYPE" in qa) ALLOWED=1 ;; esac
    [ -z "$ALLOWED" ] && deny "SHIP ステージでは qa のみ起動できます。${SUBAGENT_TYPE} は起動できません。" ;;
  REVIEW)
    [ "$STATUS" = "closed" ] && deny "REVIEW は完了済み（status=closed）です。再実行できません。🚧 ゲートでユーザーの指示を待ってください。指摘を反映するなら 'bash harness/bin/sprint stage PLAN' で巻き戻してから作業してください。"
    case "$SUBAGENT_TYPE" in qa) ALLOWED=1 ;; esac ;;
  build-red)
    case "$SUBAGENT_TYPE" in tester) ALLOWED=1 ;; esac
    [ -z "$ALLOWED" ] && deny "build-red フェーズでは tester のみ起動できます。${SUBAGENT_TYPE} は起動できません。" ;;
  BUILD)
    case "$SUBAGENT_TYPE" in frontend|backend|tester) ALLOWED=1 ;; esac ;;
  TEST)
    [ "$STATUS" = "closed" ] && deny "TEST は完了済み（status=closed）です。再実行できません。🚧 ゲートでユーザーの指示を待ってください。修正が必要なら 'bash harness/bin/sprint stage BUILD' 等で巻き戻してから作業してください。"
    case "$SUBAGENT_TYPE" in tester|qa) ALLOWED=1 ;; esac ;;
  DOCS)
    case "$SUBAGENT_TYPE" in qa) ALLOWED=1 ;; esac ;;
  CLOSED)
    ALLOWED=1 ;;
  *)
    ALLOWED=1 ;;
esac

if [ -z "$ALLOWED" ]; then
  deny "${STAGE} ステージでは ${SUBAGENT_TYPE} は起動できません。"
fi

exit 0
