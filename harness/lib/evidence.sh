#!/bin/bash
# harness/lib/evidence.sh — 実行証跡（証跡契約の JSON）の読み取り（正本）。
#
# 証跡を読む場所はここだけにする。読む側: gate-tools/results.sh・gate-tools/verify.sh・
# gate-tools/tdd-audit.sh・hooks/record-test-fails.sh・bin/sprint status。
# 先に env.sh を読む（sprint_root・sprint_config を使う）。
#
# 証跡ファイル（bin/sprint run がアダプタの convert-evidence の出力を書く）:
#   <evidence.dir>/<component>.<task>.json           1 実行 1 ファイル
#   <evidence.dir>/<component>.<task>.partial.json   追加引数つきの部分実行。ゲートは読まない
#   <evidence.dir>/raw/<component>.<task>/           ランナー固有の出力（本文と JSON）。ここでは読まない
#
# JSON の項目: schemaVersion / component / task / adapter / status(pass|fail) /
#   counts{passed,failed,skipped} / errors / warnings / tests[]{file,name,status} / started_at / finished_at
#
# 関数:
#   evidence_dir                          証跡ディレクトリ（絶対）
#   evidence_file <component> <task>      証跡ファイルのパス
#   evidence_required                     設定の全 (component, task) を「<component> <task>」で出す
#   evidence_status <c> <t>               pass | fail（無ければ空）
#   evidence_counts <c> <t> <key>         counts.<key>（無ければ 0）
#   evidence_errors <c> <t>               errors（無ければ 0）
#   evidence_warnings <c> <t>             warnings（無ければ 0）
#   evidence_finished_at <c> <t>          finished_at（epoch 秒。無ければ 0）
#   evidence_summary <c> <t>              「status failed skipped errors warnings finished_at」を 1 行で出す（無ければ空行）
#   evidence_tests_tsv                    設定の全 (component, test|e2e) の tests[] を「file<TAB>status<TAB>name」で
#                                         出す。証跡が 1 つも無ければ 1 を返す。partial は読まない

evidence_dir() {
  sprint_abs_path "$(sprint_config '.evidence.dir // ".sprint/test-result"')"
}

evidence_file() { # <component> <task>
  printf '%s/%s.%s.json\n' "$(evidence_dir)" "$1" "$2"
}

evidence_required() {
  sprint_required_tasks
}

_evidence_get() { # <component> <task> <jq フィルタ> <既定値>
  local f
  f=$(evidence_file "$1" "$2")
  [ -f "$f" ] || { printf '%s\n' "$4"; return 0; }
  jq -r "$3 // \"$4\"" "$f" 2>/dev/null || printf '%s\n' "$4"
}

evidence_status() { # <c> <t>
  _evidence_get "$1" "$2" '.status' ""
}

evidence_counts() { # <c> <t> <key>
  _evidence_get "$1" "$2" ".counts.$3" 0
}

evidence_errors() { # <c> <t>
  _evidence_get "$1" "$2" '.errors' 0
}

evidence_warnings() { # <c> <t>
  _evidence_get "$1" "$2" '.warnings' 0
}

evidence_finished_at() { # <c> <t>
  _evidence_get "$1" "$2" '.finished_at' 0
}

evidence_summary() { # <c> <t>
  local f
  f=$(evidence_file "$1" "$2")
  [ -f "$f" ] || { echo ""; return 0; }
  jq -r '[(.status // ""), (.counts.failed // 0), (.counts.skipped // 0), (.errors // 0), (.warnings // 0), (.finished_at // 0)] | map(tostring) | join(" ")' "$f" 2>/dev/null || echo ""
}

evidence_tests_tsv() {
  local c t f found=0
  while read -r c t; do
    [ -n "$c" ] || continue
    case "$t" in test|e2e) ;; *) continue ;; esac
    f=$(evidence_file "$c" "$t")
    [ -f "$f" ] || continue
    jq -r '.tests[]? | [.file, .status, .name] | @tsv' "$f" 2>/dev/null
    found=1
  done < <(evidence_required)
  [ "$found" -eq 1 ]
}
