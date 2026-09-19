# spec-graph.py — 本体。起動は harness/tools/spec-graph.sh 経由（argv[1] = 走査ルート、argv[2:] = サブコマンド）。
# 配置（生きている文書・スプリント文書の置き場・templates・テストファイルの glob）は sprint.config.json から読む。
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True  # lib/ に __pycache__ を作らない
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import config  # noqa: E402

ROOT = sys.argv[1]
ARGS = sys.argv[2:]
CFG = config.load(ROOT)

# ── 定数 ────────────────────────────────────────────────
# layer は任意の注記。書くなら次のいずれか（`layers` の集計表の列を固定するため）。
LAYERS = ("common", "core", "supporting", "generic", "operation", "frontend", "design")

# 生きている文書。定義は sprint.config.json の docs.livingDirs（xref.sh・clause-anchors.py と共有）。
#   条項を持つファイル = この配下で frontmatter に xref-prefix を宣言した md。
#   フォルダも layer も関係ない。README.md も除外しない。
#   参照元として V3 / V8 / V9 / V11 の対象になる。
LIVING_DIRS = tuple(CFG["docs"]["livingDirs"])
# スプリント文書の置き場（SPEC.md を参照元として読む）
SPRINT_ROOT = CFG["docs"]["sprintRoot"]

# 参照は 2 形式ある（18-9 N-3.1）。どちらも ID 形状に一致するものだけを拾う。
# メモリ参照（[[project_*]] 等）は形状が違うため対象外になる。
#   旧記法 [[ID]]        — docs/07_plans の過去スプリント記録に残る。受理を続ける
#   新記法 [ID](path#ID) — GitHub / Obsidian が辿れる。path が空なら同一ファイル参照
REF_RE = re.compile(r"\[\[([A-Z]{2,6}-[0-9]+)\]\]")
REF_LINK_RE = re.compile(r"\[([A-Z]{2,6}-[0-9]+)\]\(([^)#]*)#([A-Z]{2,6}-[0-9]+)\)")
# 明示アンカー（18-9 N-1.1）。V9 が参照先の実在を見る。
ANCHOR_RE = re.compile(r'<a id="([A-Z]{2,6}-[0-9]+)"></a>')
# V8 / V9 の対象外。テンプレートの相対パスはコピー先の深さで書く。置き場は設定の docs.templates。
TEMPLATE_PREFIX = CFG["docs"]["templates"].rstrip("/") + "/"
# 宣言は見出し行または表行の先頭セルにある [ID] だけ。直後に "(" が続く [ID](...) は
# リンク（参照）であり宣言ではない（条項ファイルの表が他ファイルの条項を第 1 列に
# 並べる場合がある）。
DECL_HEAD_RE = re.compile(r"^(#{1,6})\s+.*?\[([A-Z]{2,6}-[0-9]+)\](?!\()")
DECL_ROW_RE = re.compile(r"^\|\s*\*{0,2}\s*\[([A-Z]{2,6}-[0-9]+)\](?!\()")
HEAD_RE = re.compile(r"^(#{1,6})\s+")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
FM_KEY_RE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")
# V11: 節番号参照。第 1 パターン: ファイル名（.md で終わる）の後 8 文字以内に § が来る。
# 第 2 パターン: 識別子の形の語（_ か - でつないだ語・2 字以上の大文字の語・2 桁以上の数字）
# または文書の別名（設定の docs.docAliases。ファイル名から推測できない略称を登録する）の
# 直後に § と数字が来る。
# 普通の語の直後の節番号（「（§3）」「本書 §6」「in §8」の形）はどちらにも一致しない。
# インラインコードの中も対象にする。コードフェンスの中は対象外。
DOC_ALIASES = [a for a in CFG.get("docs", {}).get("docAliases", []) if a]
IDENT_WORD_RE = (
    r"(?<![A-Za-z0-9_-])"
    r"(?:[A-Za-z0-9]+(?:[_-][A-Za-z0-9]+)+|[A-Z][A-Z0-9]+|[0-9]{2,})"
)
SECTION_REF_RE = re.compile(
    r"[A-Za-z0-9_./-]+\.md[^§\n]{0,8}§"
    r"|(" + "|".join([IDENT_WORD_RE] + [re.escape(a) for a in DOC_ALIASES]) + r")\s*§[0-9]"
)

# テストファイル（参照元。条項は持たない）。テストの名前の [[ID]] を参照として読む（TSTD-6）。
#   集める範囲は設定の components[*].tests の glob。.gitignore のディレクトリ配下は集めない。
TEST_GLOBS = tuple(config.component_globs(CFG, "tests"))
# テスト名の行: 行頭の空白の後に describe( / it( / test( / test.describe( / it.each( の形
# （(describe|it|test) に .識別子 が 0 個以上続き ( が来る）で始まる行。
TEST_NAME_RE = re.compile(r"^\s*(describe|it|test)(\.[A-Za-z_]\w*)*\(")

# 表行の条項は見出し階層を持たない。どの見出しでも範囲が終わるよう最深として扱う。
ROW_LEVEL = 99

errors = []


def err(msg):
    errors.append(msg)


# ── ファイル収集 ────────────────────────────────────────
def _walk_md(root, reldir):
    base = os.path.join(root, reldir)
    if not os.path.isdir(base):
        return []
    out = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames.sort()
        for fn in sorted(filenames):
            if fn.endswith(".md"):
                out.append(os.path.relpath(os.path.join(dirpath, fn), root))
    return out


def _declared_prefix(root, rel):
    """frontmatter の xref-prefix だけを軽く読む（全文解析を避ける）。無ければ ""。"""
    try:
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            head = f.read(4096)
    except OSError:
        return ""
    lines = head.split("\n")
    if not lines or lines[0].strip() != "---":
        return ""
    for ln in lines[1:]:
        if ln.strip() == "---":
            break
        m = FM_KEY_RE.match(ln)
        if m and m.group(1) == "xref-prefix":
            return m.group(2).strip().strip("\"'")
    return ""


def living_files(root):
    out = []
    for d in LIVING_DIRS:
        out.extend(_walk_md(root, d))
    return sorted(set(out))


def target_files(root):
    """条項を持つファイル = 生きている文書のうち frontmatter に xref-prefix を宣言した md。"""
    return [rel for rel in living_files(root) if _declared_prefix(root, rel)]


def sealed_set(root):
    """封印済みファイルの相対パス集合。封印済み SPEC は参照元として検証しない。"""
    path = os.path.join(root, ".sprint", "spec-hashes.json")
    try:
        with open(path, encoding="utf-8") as f:
            return set(json.load(f).keys())
    except (OSError, ValueError):
        return set()


def test_source_files(root):
    """テストファイル（設定の tests glob に一致するファイル）。.gitignore のディレクトリ配下は集めない。"""
    return config.glob_files(root, TEST_GLOBS)


def is_test_file(rel):
    return not rel.endswith(".md")


def ref_source_files(root):
    """参照元として走査するファイル（V3 / V8 / V9 / V11 の対象）。

    生きている文書（テンプレートを含む）＋ <docs.sprintRoot> の SPEC.md ＋ リポジトリ直下の md
    ＋ テストファイル（テストの名前の [[ID]] だけ。V3 のみ適用する）。
    封印済み SPEC は呼び出し側が除く。
    """
    out = living_files(root)
    for rel in _walk_md(root, SPRINT_ROOT):
        if os.path.basename(rel) == "SPEC.md":
            out.append(rel)
    # リポジトリ直下の md（CLAUDE.md 等）も参照元として検証する。
    for fn in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        if fn.endswith(".md") and os.path.isfile(os.path.join(root, fn)):
            out.append(fn)
    out.extend(test_source_files(root))
    return sorted(set(out))


# ── 解析 ────────────────────────────────────────────────
def read_lines(path):
    with open(path, encoding="utf-8") as f:
        return f.read().split("\n")


def unfenced(lines):
    """コードフェンス内を空にした行列（行番号は保つ）。インラインコードは残す。"""
    out = []
    in_fence = False
    for ln in lines:
        if FENCE_RE.match(ln):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else ln)
    return out


def scannable(lines):
    """コードフェンス内・インラインコードを外した行列（行番号は保つ）。"""
    return [re.sub(r"`[^`]*`", "", ln) for ln in unfenced(lines)]


def parse_frontmatter(lines):
    """(dict, 本文開始行) を返す。frontmatter が無い/閉じていなければ (None, 0)。"""
    if not lines or lines[0].strip() != "---":
        return None, 0
    fm = {}
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return fm, i + 1
        m = FM_KEY_RE.match(lines[i])
        if m:
            fm[m.group(1)] = m.group(2).strip()
    return None, 0


def analyze_test(root, rel):
    """テストファイルの解析。テスト名の行（TEST_NAME_RE）の中の [[ID]] だけを参照として読む。

    行が ( で終わるときは次の行を連結して読む（名前が次の行に来る 2 行形）。
    コメント・fixture の文字列・本文は読まない。条項は持たない。V8 / V9 / V11 の対象外
    （refs の path は None、section_refs は空）。
    """
    raw = read_lines(os.path.join(root, rel))
    refs = []
    for i, ln in enumerate(raw):
        if not TEST_NAME_RE.match(ln):
            continue
        text = ln
        if ln.rstrip().endswith("(") and i + 1 < len(raw):
            text += raw[i + 1]
        for m in REF_RE.finditer(text):
            refs.append({"to": m.group(1), "line": i + 1, "path": None})
    return {"rel": rel, "fm": None, "clauses": [], "refs": refs, "section_refs": []}


def analyze(root, rel):
    if is_test_file(rel):
        return analyze_test(root, rel)
    raw = read_lines(os.path.join(root, rel))
    scan = scannable(raw)
    fm, body_start = parse_frontmatter(raw)

    heads = {}
    decls = []
    for i, ln in enumerate(scan):
        if i < body_start:
            continue
        m = HEAD_RE.match(ln)
        if m:
            heads[i] = len(m.group(1))
        m = DECL_HEAD_RE.match(ln)
        if m:
            title = re.sub(r"^#+\s*", "", raw[i]).replace("[%s]" % m.group(2), "").strip()
            decls.append({"id": m.group(2), "start": i, "level": len(m.group(1)), "title": title})
            continue
        m = DECL_ROW_RE.match(ln)
        if m:
            cells = [c.strip() for c in raw[i].strip().strip("|").split("|")]
            title = cells[1] if len(cells) > 1 else ""
            decls.append({"id": m.group(1), "start": i, "level": ROW_LEVEL, "title": title})

    decl_lines = {d["start"] for d in decls}
    for d in decls:
        end = len(raw)
        for j in range(d["start"] + 1, len(raw)):
            if j in decl_lines or (j in heads and heads[j] <= d["level"]):
                end = j
                break
        # 次の条項のアンカー行（<a id=…>）は見出しの前にあるため、ここまでの範囲に入る。
        # 条項を新設しても前の条項のハッシュが変わらないよう、末尾のアンカー行と空行は範囲から外す。
        while end > d["start"] + 1 and (
            not raw[end - 1].strip() or ANCHOR_RE.fullmatch(raw[end - 1].strip())
        ):
            end -= 1
        # 内容ハッシュの範囲は宣言行を含む。
        text = "\n".join(raw[d["start"]:end]).rstrip() + "\n"
        d["hash"] = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        d["end"] = end
        d["line"] = d["start"] + 1

    refs = []
    for i, ln in enumerate(scan):
        for m in REF_RE.finditer(ln):
            refs.append({"to": m.group(1), "line": i + 1, "path": None})
        for m in REF_LINK_RE.finditer(ln):
            refs.append({"to": m.group(3), "line": i + 1, "path": m.group(2)})
    refs.sort(key=lambda r: r["line"])

    # V11 の対象行。インラインコードを残した行で見る。
    section_refs = [i + 1 for i, ln in enumerate(unfenced(raw)) if SECTION_REF_RE.search(ln)]

    return {"rel": rel, "fm": fm, "clauses": decls, "refs": refs, "section_refs": section_refs}


def clause_index(root):
    """条項 ID → 定義情報。条項を持つファイルの条項だけがノードになる。"""
    index = {}
    dups = []
    prefixes = {}
    files = {}
    for rel in target_files(root):
        info = analyze(root, rel)
        files[rel] = info
        fm = info["fm"] or {}
        layer = fm.get("layer", "")
        prefix = fm.get("xref-prefix", "")
        if prefix:
            prefixes.setdefault(prefix, []).append(rel)
        for c in info["clauses"]:
            node = dict(c)
            node.update({"file": rel, "layer": layer, "prefix": prefix})
            if c["id"] in index:
                dups.append((c["id"], index[c["id"]], node))
            else:
                index[c["id"]] = node
    return index, dups, prefixes, files


def clause_of(info, line):
    """info（条項を持つファイルの解析結果）で line 行目を範囲に含む条項 ID。無ければ None。"""
    for c in info["clauses"]:
        if c["start"] < line <= c["end"]:
            return c["id"]
    return None


def ref_text(r):
    """参照を原文の形で表す（エラーメッセージ用）。"""
    if r["path"] is None:
        return "[[%s]]" % r["to"]
    return "[%s](%s#%s)" % (r["to"], r["path"], r["to"])


_anchor_cache = {}


def anchor_ids(root, rel):
    """rel が持つ明示アンカーの ID 集合。フェンス内は数えない（scannable と同じ意味論）。"""
    if rel not in _anchor_cache:
        try:
            lines = scannable(read_lines(os.path.join(root, rel)))
        except OSError:
            lines = []
        _anchor_cache[rel] = set(ANCHOR_RE.findall("\n".join(lines)))
    return _anchor_cache[rel]


def check_link(root, rel, r):
    """V8 / V9: 新記法リンクの相対パスとアンカーの実在（18-9 N-3.2 / N-3.3）。

    <docs.templates>/** は両方の対象外にする。テンプレートの
    相対パスはコピー先（<docs.sprintRoot>/<major>_<slug>/<minor>_<slug>/SPEC.md）から解決する深さで
    書くため、テンプレート自身の位置では解決しない。V9 も参照先ファイルの解決に
    同じ相対パスを使うので、V8 だけ外しても同じ件数で落ちる。
    """
    if r["path"] is None or rel.startswith(TEMPLATE_PREFIX):
        return
    if r["path"]:
        target = os.path.normpath(os.path.join(os.path.dirname(rel), r["path"]))
        if not os.path.isfile(os.path.join(root, target)):
            err("V8 リンクの相対パスが存在しない: %s:%d %s" % (rel, r["line"], ref_text(r)))
            return
    else:
        target = rel
    if r["to"] not in anchor_ids(root, target):
        err("V9 参照先にアンカーが無い: %s:%d %s -> %s"
            % (rel, r["line"], ref_text(r), target))


def clause_body(root, node):
    """条項の本文（宣言行を含む）。末尾の空行は落とす。"""
    raw = read_lines(os.path.join(root, node["file"]))
    body = raw[node["start"]:node["end"]]
    while body and not body[-1].strip():
        body.pop()
    return body


def clause_edges(index, tfiles):
    """条項参照グラフのエッジ {from_id: set(to_id)}。

    ノードは条項。エッジは、条項を持つファイルの条項本文の中の参照 → 参照先の条項。
    条項を持たないファイル（消費者）からの参照はエッジにしない（18-14 D-5）。
    """
    adj = {}
    for rel, info in tfiles.items():
        for r in info["refs"]:
            src = clause_of(info, r["line"])
            if src is None or r["to"] not in index:
                continue
            adj.setdefault(src, set()).add(r["to"])
    return adj


def strongly_connected(adj):
    """Tarjan。大きさ 2 以上、または自己参照を持つ成分だけを返す（ID 昇順に整列）。"""
    sys.setrecursionlimit(10000)
    idx, low, stack, on, out, counter = {}, {}, [], set(), [], [0]

    def dfs(v):
        idx[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in sorted(adj.get(v, ())):
            if w not in idx:
                dfs(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], idx[w])
        if low[v] == idx[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1 or v in adj.get(v, ()):
                out.append(sorted(comp))

    for v in sorted(adj):
        if v not in idx:
            dfs(v)
    return sorted(out)


def cycle_path(adj, comp):
    """成分の中の閉路を 1 本、始点に戻る形（A -> B -> A）で返す。"""
    start = comp[0]
    members = set(comp)
    if start in adj.get(start, ()):
        return [start, start]
    # 幅優先で start から start へ戻る最短の経路を探す。
    parent = {}
    queue = [start]
    seen = {start}
    while queue:
        v = queue.pop(0)
        for w in sorted(adj.get(v, ())):
            if w not in members:
                continue
            if w == start:
                path = [v]
                while path[-1] != start:
                    path.append(parent[path[-1]])
                path.reverse()
                return path + [start]
            if w not in seen:
                seen.add(w)
                parent[w] = v
                queue.append(w)
    return comp + [start]


# ── サブコマンド ────────────────────────────────────────
def cmd_verify():
    index, dups, prefixes, tfiles = clause_index(ROOT)
    sealed = sealed_set(ROOT)

    # V6: frontmatter の宣言
    for rel, info in sorted(tfiles.items()):
        fm = info["fm"] or {}
        prefix = fm.get("xref-prefix", "")
        if not re.fullmatch(r"[A-Z]{2,6}", prefix):
            err("V6 xref-prefix は英大文字 2〜6 字: %s (%s)" % (rel, prefix))
        layer = fm.get("layer", "")
        if layer and layer not in LAYERS:
            err("V6 layer の値が不正: %s (%s) — 書くなら %s のいずれか" % (rel, layer, "/".join(LAYERS)))
    # V6: 条項を宣言する見出しを持つのに xref-prefix が無いファイル（条項が黙って対象外になる）
    for rel in living_files(ROOT):
        if rel in tfiles:
            continue
        info = analyze(ROOT, rel)
        heads_with_id = [c for c in info["clauses"] if c["level"] != ROW_LEVEL]
        if heads_with_id:
            err("V6 xref-prefix が無い: %s（条項の見出し %s:%d）"
                % (rel, heads_with_id[0]["id"], heads_with_id[0]["line"]))

    # V1: prefix の一意性
    for prefix, rels in sorted(prefixes.items()):
        if len(rels) > 1:
            err("V1 xref-prefix %s が重複: %s" % (prefix, ", ".join(sorted(rels))))

    # V2: 条項 ID の一意性
    for cid, first, second in dups:
        err("V2 条項 ID %s が重複: %s:%d / %s:%d"
            % (cid, first["file"], first["line"], second["file"], second["line"]))

    # V2 の前提: 条項 ID はファイルが宣言した prefix を使う
    for rel, info in sorted(tfiles.items()):
        prefix = (info["fm"] or {}).get("xref-prefix", "")
        if not prefix:
            continue
        for c in info["clauses"]:
            if c["id"].rsplit("-", 1)[0] != prefix:
                err("V2 条項 ID の prefix がファイル宣言と違う: %s:%d %s (宣言 %s)"
                    % (rel, c["line"], c["id"], prefix))

    # V5: impl パスの実在
    for rel, info in sorted(tfiles.items()):
        impl = (info["fm"] or {}).get("impl", "")
        if impl and not os.path.exists(os.path.join(ROOT, impl)):
            err("V5 impl パスが存在しない: %s (impl: %s)" % (rel, impl))

    # V3 / V8 / V9 / V11: 参照の実在・リンクの解決・節番号参照
    for rel in ref_source_files(ROOT):
        if rel in sealed:
            continue
        info = tfiles.get(rel) or analyze(ROOT, rel)
        for r in info["refs"]:
            check_link(ROOT, rel, r)
            if r["to"] not in index:
                # テストの名前の参照は素の ID で出す（N-1.3）。文書は原文の記法で出す。
                shown = r["to"] if is_test_file(rel) else ref_text(r)
                err("V3 参照先の条項が無い: %s:%d %s" % (rel, r["line"], shown))
        for line in info["section_refs"]:
            err("V11 節番号で参照している: %s:%d" % (rel, line))

    # V10: 条項参照グラフの循環
    adj = clause_edges(index, tfiles)
    for comp in strongly_connected(adj):
        err("V10 参照が循環している: %s" % " -> ".join(cycle_path(adj, comp)))

    if errors:
        for e in errors:
            print(e)
        print("verify: NG (%d 件)" % len(errors))
        return 1
    ref_count = sum(len(analyze(ROOT, rel)["refs"])
                    for rel in ref_source_files(ROOT) if rel not in sealed)
    print("verify: OK (%d clauses, %d refs, %d files)"
          % (len(index), ref_count, len(tfiles)))
    return 0


def build_graph(root):
    index, _, _, tfiles = clause_index(root)
    nodes = []
    for cid, c in sorted(index.items()):
        nodes.append({
            "id": cid,
            "file": c["file"],
            "line": c["line"],
            "layer": c["layer"],
            "prefix": c["prefix"],
            "title": c["title"],
            "hash": c["hash"],
            # 条項の範囲（1 始まり・両端を含む）。条項化率の集計が範囲の計算を写さずに済む。
            "endLine": c["end"],
        })
    sealed = sealed_set(root)
    edges = []
    for rel in ref_source_files(root):
        if rel in sealed:
            continue
        info = tfiles.get(rel)
        # from は条項を持つファイルの条項の範囲に入る参照だけに付く（18-14 N-1.8）。
        # 消費者ファイルの表行は条項ではない。
        refs = info["refs"] if info else analyze(root, rel)["refs"]
        for r in refs:
            src = clause_of(info, r["line"]) if info else None
            edges.append({"from": src, "fromFile": rel, "line": r["line"], "to": r["to"]})
    return {"nodes": nodes, "edges": edges}


def cmd_index():
    print(json.dumps(build_graph(ROOT), ensure_ascii=False, indent=2))
    return 0


def references_to(root, cid):
    sealed = sealed_set(root)
    hits = []
    for rel in ref_source_files(root):
        info = analyze(root, rel)
        for r in info["refs"]:
            if r["to"] == cid:
                hits.append((rel, r["line"], rel in sealed))
    return hits


def cmd_reverse(cid):
    for rel, line, is_sealed in references_to(ROOT, cid):
        print("%s:%d%s" % (rel, line, "  (封印済み)" if is_sealed else ""))
    return 0


def cmd_deps(path):
    rel = os.path.relpath(os.path.abspath(path), ROOT)
    full = os.path.join(ROOT, rel)
    if not os.path.isfile(full):
        print("ファイルが見つかりません: %s" % path)
        return 1
    index, _, _, _ = clause_index(ROOT)
    for r in analyze(ROOT, rel)["refs"]:
        dst = index.get(r["to"])
        where = "%s:%d" % (dst["file"], dst["line"]) if dst else "(参照先なし)"
        print("%s:%d -> %s  %s" % (rel, r["line"], r["to"], where))
    return 0


def cmd_diff(ref):
    rev = subprocess.run(["git", "-C", ROOT, "rev-parse", "--verify", "%s^{commit}" % ref],
                         capture_output=True, text=True)
    if rev.returncode != 0:
        print("git-ref を解決できません: %s" % ref)
        return 1

    listing = subprocess.run(["git", "-C", ROOT, "ls-tree", "-r", "--name-only", ref, "--", "docs"],
                             capture_output=True, text=True)
    with tempfile.TemporaryDirectory() as tmp:
        for p in listing.stdout.split("\n"):
            if not p.endswith(".md"):
                continue
            blob = subprocess.run(["git", "-C", ROOT, "show", "%s:%s" % (ref, p)],
                                  capture_output=True, text=True)
            if blob.returncode != 0:
                continue
            dest = os.path.join(tmp, p)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8") as f:
                f.write(blob.stdout)
        old, _, _, _ = clause_index(tmp)

    new, _, _, _ = clause_index(ROOT)

    changed = [cid for cid in sorted(set(old) & set(new)) if old[cid]["hash"] != new[cid]["hash"]]
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))

    def show(kind, cid, node):
        print("%s: %s  %s:%d" % (kind, cid, node["file"], node["line"]))
        for rel, line, is_sealed in references_to(ROOT, cid):
            print("    ← %s:%d%s" % (rel, line, "  (封印済み)" if is_sealed else ""))

    for cid in changed:
        show("changed", cid, new[cid])
    for cid in added:
        show("added", cid, new[cid])
    for cid in removed:
        show("removed", cid, old[cid])

    print("diff %s: changed %d / added %d / removed %d"
          % (ref, len(changed), len(added), len(removed)))
    return 0


def refs_in_counts(root, index, tfiles):
    """ファイル別の被参照数（封印済みを除く全参照元から、参照先の条項のファイルへ）。"""
    counts = {rel: 0 for rel in tfiles}
    sealed = sealed_set(root)
    for rel in ref_source_files(root):
        if rel in sealed:
            continue
        info = tfiles.get(rel) or analyze(root, rel)
        for r in info["refs"]:
            dst = index.get(r["to"])
            if dst:
                counts[dst["file"]] = counts.get(dst["file"], 0) + 1
    return counts


def cmd_files():
    """条項を持つファイルの一覧。相対パス・prefix・layer（無ければ -）・条項数・被参照数。"""
    index, _, _, tfiles = clause_index(ROOT)
    clauses = {rel: 0 for rel in tfiles}
    for node in index.values():
        clauses[node["file"]] = clauses.get(node["file"], 0) + 1
    counts = refs_in_counts(ROOT, index, tfiles)
    for rel in sorted(tfiles):
        fm = tfiles[rel]["fm"] or {}
        print("%s  %s  %s  clauses=%d  refs-in=%d"
              % (rel, fm.get("xref-prefix", "-"), fm.get("layer", "") or "-",
                 clauses.get(rel, 0), counts.get(rel, 0)))
    return 0


def cmd_layers():
    """条項を持つファイル間の参照エッジを 参照元の layer × 参照先の layer で数えた表。

    方向は依存構造の評価指標であって制約ではない（18-14 D-2）。layer の無いファイルは
    `-` として数える。1 行 1 組（参照元 layer・参照先 layer・参照数）。出現する組だけを出す。
    """
    index, _, _, tfiles = clause_index(ROOT)
    table = {}
    for rel, info in tfiles.items():
        src_layer = (info["fm"] or {}).get("layer", "") or "-"
        for r in info["refs"]:
            dst = index.get(r["to"])
            if dst is None:
                continue
            dst_layer = dst["layer"] or "-"
            table[(src_layer, dst_layer)] = table.get((src_layer, dst_layer), 0) + 1
    order = {l: i for i, l in enumerate(LAYERS + ("-",))}
    print("| 参照元 layer | 参照先 layer | 参照数 |")
    print("|---|---|---:|")
    for (src, dst), n in sorted(table.items(), key=lambda kv: (order[kv[0][0]], order[kv[0][1]])):
        print("| %s | %s | %d |" % (src, dst, n))
    return 0


def refs_in(lines):
    """行の並びに現れる参照 ID を出現順に返す。コードフェンス内は走査しない。"""
    out = []
    in_fence = False
    for ln in lines:
        if FENCE_RE.match(ln):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        bare = re.sub(r"`[^`]*`", "", ln)
        for rid in REF_RE.findall(bare) + [m[2] for m in REF_LINK_RE.findall(bare)]:
            if rid not in out:
                out.append(rid)
    return out


def cmd_resolve(path):
    """原文を無改変で出し、到達する条項を 1 件 1 回ずつ列挙する。"""
    rel = os.path.relpath(os.path.abspath(path), ROOT)
    full = os.path.join(ROOT, rel)
    if not os.path.isfile(full):
        print("ファイルが見つかりません: %s" % path)
        return 1

    index, _, _, _ = clause_index(ROOT)
    source = read_lines(full)

    # 幅優先で推移閉包を作る。訪問済みは再展開しないので循環は終端する。
    order = []
    seen = set()
    missing = []
    origin = {}
    queue = [(rid, [rel]) for rid in refs_in(source)]
    cycles = []
    while queue:
        rid, path_ids = queue.pop(0)
        node = index.get(rid)
        if node is None:
            if rid not in missing:
                missing.append(rid)
            continue
        if rid in seen:
            if rid in path_ids:
                cycles.append((rid, path_ids))
            continue
        seen.add(rid)
        order.append(rid)
        origin[rid] = path_ids
        for nxt in refs_in(clause_body(ROOT, node)):
            if nxt in path_ids or nxt == rid:
                cycles.append((nxt, path_ids + [rid]))
                if nxt in seen:
                    continue
            queue.append((nxt, path_ids + [rid]))

    if missing:
        for rid in missing:
            print("resolve: 参照先の条項が無い: %s [[%s]]" % (rel, rid))
        return 1

    for line in source:
        print(line)

    print("")
    print("---")
    print("")
    print("## 参照した条項（`spec-graph.sh resolve` による展開）")
    print("")
    if not order:
        print("参照なし。")
        return 0
    print("到達した条項 %d 件。同じ条項は 1 回だけ出す（循環は終端する）。" % len(order))
    print("")
    reported = set()
    for rid in order:
        node = index[rid]
        print("### %s — %s" % (rid, node["title"] or "(無題)"))
        print("")
        print("出典: `%s:%d`（%s）" % (node["file"], node["line"], node["layer"] or "-"))
        for cid, path_ids in cycles:
            key = (cid, tuple(path_ids))
            if cid == rid and key not in reported:
                reported.add(key)
                print("")
                print("<!-- resolve: cycle %s -> %s -->"
                      % (" -> ".join(p for p in path_ids if p != rel), cid))
        print("")
        for line in clause_body(ROOT, node):
            print(line)
        print("")
    return 0


USAGE = ("Usage: spec-graph.sh "
         "{verify|index|diff <git-ref>|reverse <ID>|deps <FILE>|files|layers|resolve <FILE>}")

if not ARGS:
    print(USAGE)
    sys.exit(2)

cmd, rest = ARGS[0], ARGS[1:]
if cmd == "verify":
    sys.exit(cmd_verify())
if cmd == "index":
    sys.exit(cmd_index())
if cmd == "reverse":
    if not rest:
        print(USAGE)
        sys.exit(2)
    sys.exit(cmd_reverse(rest[0]))
if cmd == "deps":
    if not rest:
        print(USAGE)
        sys.exit(2)
    sys.exit(cmd_deps(rest[0]))
if cmd == "diff":
    if not rest:
        print(USAGE)
        sys.exit(2)
    sys.exit(cmd_diff(rest[0]))
if cmd == "files":
    sys.exit(cmd_files())
if cmd == "layers":
    sys.exit(cmd_layers())
if cmd == "resolve":
    if not rest:
        print(USAGE)
        sys.exit(2)
    sys.exit(cmd_resolve(rest[0]))

print(USAGE)
sys.exit(2)
