#!/bin/bash
# spec-check.sh — SPEC.md / TEST.md の構造検査（封印前の自己検査）
#
# 「変更が全ノードに届かない」型の 🔴 を、反映のたびに機械検査して自力で潰すための道具である。
# 対象は active スプリント（引数で sprint_dir を上書きできる）。
#
# 使い方: bash harness/bin/sprint spec-check [sprint_dir]

set -u
. "$(dirname "$(readlink -f "$0")")/../lib/env.sh"
ROOT=$(sprint_root)
DIR="${1:-}"
if [ -z "$DIR" ]; then
  DIR=$(jq -r '.sprints[.active].sprint_dir // ""' "$ROOT/.sprint/flags.json" 2>/dev/null)
fi
[ -z "$DIR" ] && { echo "sprint_dir を特定できません。引数で渡してください。" >&2; exit 2; }

SPEC="$ROOT/$DIR/SPEC.md"
TEST="$ROOT/$DIR/TEST.md"
for f in "$SPEC" "$TEST"; do
  [ -f "$f" ] || { echo "not found: $f" >&2; exit 2; }
done

T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
RC=0
note() { echo "  $*"; }
fail() { echo "  ✗ $*"; RC=1; }

# EARS 定義とマトリクス
grep -oE '^\- \*\*(N|E)-[0-9]+\.[0-9]+[a-z]?[0-9]?\*\*' "$SPEC" \
  | sed -E 's/^- \*\*//; s/\*\*$//' | sort -u > "$T/ears"
awk '/^## 網羅性マトリクス/,/^## 実行手順/' "$TEST" \
  | grep -oE '^\| (N|E)-[0-9]+\.[0-9]+[a-z]?[0-9]? ' | tr -d '| ' | sort -u > "$T/mat"

echo "== 1. EARS ↔ 網羅性マトリクス =="
note "EARS $(wc -l < "$T/ears") / マトリクス $(wc -l < "$T/mat")"
D=$(comm -3 "$T/ears" "$T/mat"); [ -n "$D" ] && fail "差分:"$'\n'"$D"

echo "== 2. 実装単位への帰属 =="
sed -n '/^## 実装単位と依存関係/,/^## EARS 要件/p' "$SPEC" > "$T/units"
python3 - "$T" <<'PY'
import re,sys,io
T=sys.argv[1]
units=io.open(T+'/units',encoding='utf-8').read()
ears=[l.strip() for l in io.open(T+'/ears',encoding='utf-8') if l.strip()]
def expand(spec):
    cov=set()
    for m in re.finditer(r'(N|E)-\d+\.\d+[a-z]?\d?', spec): cov.add(m.group(0))
    for m in re.finditer(r'(N-\d+\.\d+[a-z]?\d?)〜(N-\d+\.\d+[a-z]?\d?)', spec):
        pa=re.match(r'N-(\d+)\.(\d+)',m.group(1)); pb=re.match(r'N-(\d+)\.(\d+)',m.group(2))
        lo=(int(pa.group(1)),int(pa.group(2))); hi=(int(pb.group(1)),int(pb.group(2)))
        for e in ears:
            pe=re.match(r'N-(\d+)\.(\d+)',e)
            if pe and lo<=(int(pe.group(1)),int(pe.group(2)))<=hi: cov.add(e)
    return cov
owner={}; dup=[]
for unit,spec in re.findall(r"^\| ([A-Z]-[0-9a-z']+) \|[^|]*\|[^|]*\| ([^|]*) \|", units, re.M):
    for e in expand(spec):
        if e in ears:
            if e in owner: dup.append((e,owner[e],unit))
            else: owner[e]=unit
miss=[e for e in ears if e not in owner]
print("  未帰属: %d 件 %s" % (len(miss), miss if miss else ""))
print("  二重帰属: %d 件 %s" % (len(dup), dup if dup else ""))
sys.exit(1 if (miss or dup) else 0)
PY
[ $? -ne 0 ] && RC=1

echo "== 3. Test ID の定義 ↔ 参照 =="
# Test ID は新形式 TEST-<sprint_id>-<major>.<minor>（docs/06_process/gate-tools.md §3.1.3）と
# 旧形式 TEST-<major>.<minor> の両方を受ける。PFX は minor を除いた部分。
PFX=$(grep -oE '^\| TEST-[0-9]+(-[0-9]+)*\.' "$TEST" | sed -E 's/^\| //; s/\.$//' \
      | sort | uniq -c | sort -rn | head -1 | awk '{print $2}')
# kind=docs の TEST.md は Test ID を持たない（静的検証項目 S-x だけ）。検査 3・4 を省略して 5 へ進む
if [ -z "$PFX" ]; then
  note "Test ID の定義行なし（kind=docs）。検査 3・4 を省略"
else
awk '/^## テスト仕様/,/^## 既存テストの改修対象/' "$TEST" \
  | grep -oE "^\| ${PFX}\.[0-9]+" | tr -d '| ' | sort -u > "$T/t1"
awk '/^## 網羅性マトリクス/,/^## 実行手順/' "$TEST" \
  | grep -oE "${PFX}\.[0-9]+" | sort -u > "$T/t2"
note "定義 $(wc -l < "$T/t1") / 参照 $(wc -l < "$T/t2")"
D=$(comm -3 "$T/t1" "$T/t2"); [ -n "$D" ] && fail "差分:"$'\n'"$D"
MAX=$(sed -E "s/.*${PFX}\.([0-9]+).*/\1/" "$T/t1" | sort -n | tail -1)
for i in $(seq 1 "${MAX:-0}"); do
  grep -q "${PFX}\.$i " "$TEST" || fail "欠番 ${PFX}.$i"
done

echo "== 4. 表から分離した行（空行による markdown 表の分断） =="
awk -v p="$PFX" '$0 ~ "^\\| *"p"\\." { if (prev ~ /^[[:space:]]*$/) print "  ✗ 分離: 行" NR } { prev=$0 }' "$TEST" \
  | tee "$T/sep"; [ -s "$T/sep" ] && RC=1
fi

echo "== 5. 参照テストファイルの実在 =="
for f in $(grep -oE '`(backend|frontend)/[A-Za-z0-9/_.-]+\.(ts|tsx)`' "$TEST" | tr -d '`' | sort -u); do
  [ -e "$ROOT/$f" ] || note "不在（新規作成なら TEST.md の宣言と一致するか確認）: $f"
done

echo
[ $RC -eq 0 ] && echo "spec-check: OK" || echo "spec-check: 要修正"
exit $RC
