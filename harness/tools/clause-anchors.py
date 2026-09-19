# clause-anchors.py — 本体。起動は harness/tools/clause-anchors.sh 経由（argv[1] = 走査ルート、--check で書き込まない）。
# 配置（生きている文書・templates）は sprint.config.json から読む。
import os
import re
import sys

sys.dont_write_bytecode = True  # lib/ に __pycache__ を作らない
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import config  # noqa: E402

ROOT = sys.argv[1]
CHECK = "--check" in sys.argv[2:]
CFG = config.load(ROOT)

# 生きている文書。定義は sprint.config.json の docs.livingDirs（spec-graph.py・xref.sh と共有）。
#   アンカーの設置対象 = この配下で frontmatter に xref-prefix を宣言した md（spec-graph の
#   条項ファイルと同じ定義）。
#   参照 [[ID]] の変換対象 = この配下の md ＋ リポジトリ直下の md。
LIVING_DIRS = tuple(CFG["docs"]["livingDirs"])
# 機械変換の対象外。テンプレートの相対パスはコピー先の深さで書くため
# 参照元の位置から機械計算すると切れる。テンプレートの参照は手で書く。置き場は設定の docs.templates。
TEMPLATE_PREFIX = CFG["docs"]["templates"].rstrip("/") + "/"

FENCE_RE = re.compile(r"^\s*(```|~~~)")
DECL_HEAD_RE = re.compile(r"^(#{1,6})\s+.*?\[([A-Z]{2,6}-[0-9]+)\](?!\()")
REF_RE = re.compile(r"\[\[([A-Z]{2,6}-[0-9]+)\]\]")
CODE_SPAN_RE = re.compile(r"(`[^`]*`)")
FM_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")


def anchor_of(cid):
    return '<a id="%s"></a>' % cid


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read().split("\n")


def declared_prefix(rel):
    """frontmatter の xref-prefix。無ければ ""。"""
    lines = read(rel)
    if not lines or lines[0].strip() != "---":
        return ""
    for ln in lines[1:]:
        if ln.strip() == "---":
            break
        m = FM_KEY_RE.match(ln)
        if m and m.group(1) == "xref-prefix":
            return m.group(2).strip().strip("\"'")
    return ""


def living_files():
    out = []
    for d in LIVING_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames.sort()
            for fn in sorted(filenames):
                if fn.endswith(".md"):
                    out.append(os.path.relpath(os.path.join(dirpath, fn), ROOT))
    return sorted(set(out))


def ref_files():
    """参照の変換対象。テンプレートは変換しない。"""
    out = [rel for rel in living_files() if not rel.startswith(TEMPLATE_PREFIX)]
    if os.path.isdir(ROOT):
        for fn in sorted(os.listdir(ROOT)):
            if fn.endswith(".md") and os.path.isfile(os.path.join(ROOT, fn)):
                out.append(fn)
    return sorted(set(out))


def build_index():
    """条項 ID → 宣言ファイル。フェンス内の擬似見出しは数えない。"""
    index, dups = {}, []
    anchor_files = set()
    for rel in living_files():
        if not declared_prefix(rel):
            continue
        anchor_files.add(rel)
        infence = False
        for ln in read(rel):
            if FENCE_RE.match(ln):
                infence = not infence
                continue
            if infence:
                continue
            m = DECL_HEAD_RE.match(ln)
            if m:
                if m.group(2) in index:
                    dups.append((m.group(2), index[m.group(2)], rel))
                else:
                    index[m.group(2)] = rel
    return index, dups, anchor_files


def link_for(cid, src_rel, index):
    """参照 1 件のリンク文字列。同一ファイルなら相対パスを書かない。"""
    dst = index[cid]
    if dst == src_rel:
        return "[%s](#%s)" % (cid, cid)
    path = os.path.relpath(dst, os.path.dirname(src_rel) or ".")
    return "[%s](%s#%s)" % (cid, path, cid)


def convert(rel, index, add_anchors, missing):
    """1 ファイルを変換した行列を返す。フェンス内・インラインコード内は触らない。"""
    out = []
    infence = False
    for ln in read(rel):
        if FENCE_RE.match(ln):
            infence = not infence
            out.append(ln)
            continue
        if infence:
            out.append(ln)
            continue

        if add_anchors:
            m = DECL_HEAD_RE.match(ln)
            if m and (not out or out[-1].strip() != anchor_of(m.group(2))):
                out.append(anchor_of(m.group(2)))

        # インラインコード内は変換しない。奇数番目が code span。
        parts = CODE_SPAN_RE.split(ln)
        for i in range(0, len(parts), 2):
            def repl(m):
                cid = m.group(1)
                if cid not in index:
                    missing.append((rel, cid))
                    return m.group(0)
                return link_for(cid, rel, index)
            parts[i] = REF_RE.sub(repl, parts[i])
        out.append("".join(parts))
    return out


def main():
    index, dups, anchor_files = build_index()
    for cid, a, b in dups:
        print("条項 ID が重複している: %s (%s / %s)" % (cid, a, b))
    if dups:
        return 1
    print("条項 %d 件を %d ファイルから読んだ" % (len(index), len(set(index.values()))))

    missing = []
    changed, anchors_added, refs_converted = [], 0, 0
    for rel in sorted(set(ref_files()) | anchor_files):
        before = read(rel)
        after = convert(rel, index, rel in anchor_files, missing)
        if before == after:
            continue
        changed.append(rel)
        anchors_added += sum(1 for ln in after if ln.strip().startswith('<a id="')) \
            - sum(1 for ln in before if ln.strip().startswith('<a id="'))
        refs_converted += sum(len(REF_RE.findall(ln)) for ln in before) \
            - sum(len(REF_RE.findall(ln)) for ln in after)
        if not CHECK:
            with open(os.path.join(ROOT, rel), "w", encoding="utf-8") as f:
                f.write("\n".join(after))

    for rel, cid in missing:
        print("参照先の条項が見つからない（変換せず残した）: %s [[%s]]" % (rel, cid))

    verb = "変更が必要" if CHECK else "変更した"
    print("%s: %d ファイル（アンカー +%d / 参照 %d 件をリンク化）"
          % (verb, len(changed), anchors_added, refs_converted))
    for rel in changed:
        print("  %s" % rel)
    if missing:
        return 1
    return 1 if (CHECK and changed) else 0


sys.exit(main())
