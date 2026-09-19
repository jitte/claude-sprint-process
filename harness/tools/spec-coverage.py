#!/usr/bin/env python3
"""spec-coverage.py — ベース仕様の条項参照カバレッジ（cov / rcov / tcov）を数える。

条項 1 件を単位に、参照グラフ（同じディレクトリの spec-graph.py index）の辺の有無で数える。

  cov   条項化率 : 条項の範囲に入る行の割合（非空行。frontmatter を除く）
  hcov  見出し率 : 条項 ID を持つ見出しの割合（##〜####。コードフェンス外）
  rcov  被参照率 : 他から参照される（入る辺を持つ）条項の行の割合。参照元は生きている文書
                   （docs.sprintRoot 以外。条項を持たない消費者ファイルからの参照も数える）
  rcov+ sprint 考慮の被参照率 : 指定 sprint の SPEC.md 全体の参照を入る辺に加えた rcov
  tcov  テスト被参照率 : docs.specDir の各文書について、テストファイル（テストの名前の [[ID]]）
                   から参照される条項の数 / 条項数。specDir 以外の文書は —。rcov / rcov+ / 単独は
                   テストの参照を数えない（参照元が .md の辺だけ）
  solo  単独率   : 規範・共通層（docs.normativeDirs と docs.commonFiles）をひとつも参照しない
                   条項の割合。specDir の末端の仕様だけが対象。規範・共通層の設定が無いときは —

評価指標であり fail させない。層と参照の向きは指標であって制約ではない。

配置は sprint.config.json から読む（docs.sprintRoot・docs.specDir・docs.normativeDirs・
docs.commonFiles）。本体はパスを持たない。

使い方（spec-coverage.sh 経由。ROOT は走査ルート）:
  python3 spec-coverage.py <ROOT>                 # active sprint の SPEC.md を考慮
  python3 spec-coverage.py <ROOT> --sprint 1-2    # sprint ID で指定
  python3 spec-coverage.py <ROOT> --spec <sprintRoot>/.../SPEC.md
  python3 spec-coverage.py <ROOT> --no-sprint     # ベース仕様だけ
  python3 spec-coverage.py <ROOT> --json          # 機械可読
  python3 spec-coverage.py <ROOT> --unreferenced  # 未被参照の条項 ID を末尾に列挙
  python3 spec-coverage.py <ROOT> --untested      # specDir の条項のうちテストから参照されない ID を文書別に列挙
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "lib")))
import config  # noqa: E402

if len(sys.argv) < 2:
    print("usage: spec-coverage.py <ROOT> [options]")
    sys.exit(2)
ROOT = sys.argv[1]
CFG = config.load(ROOT)
DOCS = CFG.get("docs", {})


def _dir(key):
    v = DOCS.get(key, "")
    return v.rstrip("/") + "/" if v else ""


SPRINT_DIR = _dir("sprintRoot")
SPEC_DIR = _dir("specDir")
NORM_PREFIXES = tuple(p.rstrip("/") + "/" for p in DOCS.get("normativeDirs", []))
NORM_FILES = tuple(DOCS.get("commonFiles", []))
NORM_ENABLED = bool(NORM_PREFIXES or NORM_FILES)

# spec-graph.py と同じ 2 記法。ID 形状に一致するものだけを拾う。
REF_RE = re.compile(r"\[\[([A-Z]{2,6}-[0-9]+)\]\]")
REF_LINK_RE = re.compile(r"\[([A-Z]{2,6}-[0-9]+)\]\(([^)#]*)#([A-Z]{2,6}-[0-9]+)\)")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
SPEC_GRAPH_PY = os.path.join(HERE, "spec-graph.py")


def load_index():
    out = subprocess.run(
        [sys.executable, SPEC_GRAPH_PY, ROOT, "index"],
        capture_output=True, text=True, cwd=ROOT,
    )
    if out.returncode != 0:
        sys.stderr.write(out.stderr or out.stdout)
        sys.exit(2)
    return json.loads(out.stdout)


def refs_in_file(path):
    """ファイル中の参照 ID（コードフェンス外・インラインコード外）を集合で返す。"""
    ids = set()
    in_fence = False
    with open(path, encoding="utf-8") as f:
        for ln in f:
            if FENCE_RE.match(ln):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            bare = re.sub(r"`[^`]*`", "", ln)
            ids.update(REF_RE.findall(bare))
            ids.update(m[2] for m in REF_LINK_RE.findall(bare))
    return ids


def resolve_spec(args):
    """考慮する SPEC.md のパス（ROOT 相対）と sprint ID を返す。無ければ (None, None)。"""
    if args.no_sprint:
        return None, None
    if args.spec:
        return args.spec, None
    flags_path = os.path.join(ROOT, ".sprint", "flags.json")
    if not os.path.isfile(flags_path):
        return None, None
    flags = json.load(open(flags_path, encoding="utf-8"))
    sid = args.sprint or flags.get("active")
    entry = (flags.get("sprints") or {}).get(sid)
    if not entry:
        sys.stderr.write("sprint %s が .sprint/flags.json に無い\n" % sid)
        sys.exit(2)
    return os.path.join(entry["sprint_dir"], "SPEC.md"), sid


def _body_start(raw):
    if raw and raw[0] == "---" and "---" in raw[1:]:
        return raw.index("---", 1) + 1
    return 0


def line_coverage(rel, spans):
    """(非空行の数, そのうち条項の範囲に入る数)。frontmatter は数えない。"""
    raw = open(os.path.join(ROOT, rel), encoding="utf-8").read().split("\n")
    start = _body_start(raw)
    inside = set()
    for lo, hi in spans:          # 1 始まり・両端を含む
        inside.update(range(lo - 1, hi))
    body = [i for i in range(start, len(raw)) if raw[i].strip()]
    return len(body), sum(1 for i in body if i in inside)


HEAD_RE = re.compile(r"^(#{2,4})\s+(.*)$")
DECL_ID_RE = re.compile(r"\[[A-Z]{2,6}-[0-9]+\](?!\()")


def is_norm_file(rel):
    return rel.startswith(NORM_PREFIXES) or rel in NORM_FILES


def heading_coverage(rel):
    """(見出しの数, そのうち条項 ID を持つ数)。コードフェンス内と frontmatter は除く。"""
    raw = open(os.path.join(ROOT, rel), encoding="utf-8").read().split("\n")
    total = with_id = 0
    fence = False
    for ln in raw[_body_start(raw):]:
        if FENCE_RE.match(ln):
            fence = not fence
            continue
        if fence:
            continue
        m = HEAD_RE.match(ln)
        if m:
            total += 1
            if DECL_ID_RE.search(m.group(2)):
                with_id += 1
    return total, with_id


def pct(n, d):
    return "%d/%d (%d%%)" % (n, d, round(100.0 * n / d)) if d else "0/0 (-)"


def main():
    ap = argparse.ArgumentParser(prog="spec-coverage")
    ap.add_argument("--sprint", help="sprint ID（既定: .sprint/flags.json の active）")
    ap.add_argument("--spec", help="SPEC.md のパス（--sprint より優先）")
    ap.add_argument("--no-sprint", action="store_true", help="ベース仕様だけを数える")
    ap.add_argument("--unreferenced", action="store_true",
                    help="未被参照の条項 ID を末尾に列挙する（既定は件数だけ）")
    ap.add_argument("--untested", action="store_true",
                    help="specDir の条項のうちテストから参照されない ID を文書別に列挙する")
    ap.add_argument("--json", action="store_true", help="JSON で出す")
    args = ap.parse_args(sys.argv[2:])

    idx = load_index()
    nodes = {n["id"]: n for n in idx["nodes"]}
    has_in = set()
    to_norm = set()
    tested = set()          # テストファイル（.md 以外）から参照される条項
    for e in idx["edges"]:
        if SPRINT_DIR and e["fromFile"].startswith(SPRINT_DIR):
            continue
        if not e["fromFile"].endswith(".md"):
            if e["to"] in nodes:
                tested.add(e["to"])
            continue
        if e["to"] in nodes:
            has_in.add(e["to"])
            if e["from"] in nodes and is_norm_file(nodes[e["to"]]["file"]):
                to_norm.add(e["from"])

    spec_rel, sid = resolve_spec(args)
    spec_refs = set()
    if spec_rel:
        spec_abs = os.path.join(ROOT, spec_rel)
        if not os.path.isfile(spec_abs):
            sys.stderr.write("SPEC.md が無い: %s\n" % spec_rel)
            sys.exit(2)
        spec_refs = {r for r in refs_in_file(spec_abs) if r in nodes}
    has_in_plus = has_in | spec_refs

    files = {}
    for n in sorted(nodes.values(), key=lambda n: (n["file"], n["line"])):
        f = files.setdefault(n["file"], {"prefix": n["prefix"], "ids": [], "spans": []})
        f["ids"].append(n["id"])
        f["spans"].append((n["line"], n["endLine"]))

    rows = []
    for rel in sorted(files):
        ids = files[rel]["ids"]
        spans = dict(zip(ids, files[rel]["spans"]))
        body, covered = line_coverage(rel, files[rel]["spans"])
        _, rcov_l = line_coverage(rel, [spans[i] for i in ids if i in has_in])
        _, rcovp_l = line_coverage(rel, [spans[i] for i in ids if i in has_in_plus])
        heads, heads_id = heading_coverage(rel)
        is_spec = bool(SPEC_DIR) and rel.startswith(SPEC_DIR)
        # 単独率の対象は specDir の末端の仕様だけ。規範・共通層の設定が無ければ数えない。
        is_leaf = NORM_ENABLED and is_spec and not is_norm_file(rel)
        leaf = ids if is_leaf else []
        rows.append({
            "file": rel,
            "prefix": files[rel]["prefix"],
            "clauses": len(ids),
            "lines": body,
            "cov": covered,
            "headings": heads,
            "hcov": heads_id,
            "rcov": rcov_l,
            "rcov_plus": rcovp_l,
            "rcov_clauses": sum(1 for i in ids if i in has_in),
            "leaf_clauses": len(leaf),
            "solo": sum(1 for i in leaf if i not in to_norm),
            "unreferenced": [i for i in ids if i not in has_in],
            "covered_by_sprint": [i for i in ids if i in spec_refs and i not in has_in],
            # tcov は specDir の文書だけ。それ以外は None（表では —）
            "tcov": sum(1 for i in ids if i in tested) if is_spec else None,
            "untested": [i for i in ids if i not in tested] if is_spec else [],
        })
    total = {
        "clauses": len(nodes),
        "lines": sum(r["lines"] for r in rows),
        "cov": sum(r["cov"] for r in rows),
        "headings": sum(r["headings"] for r in rows),
        "hcov": sum(r["hcov"] for r in rows),
        "rcov": sum(r["rcov"] for r in rows),
        "rcov_plus": sum(r["rcov_plus"] for r in rows),
        "rcov_clauses": len(has_in),
        "leaf_clauses": sum(r["leaf_clauses"] for r in rows),
        "solo": sum(r["solo"] for r in rows),
        "clauses_spec": sum(r["clauses"] for r in rows if r["tcov"] is not None),
        "tcov": sum(r["tcov"] for r in rows if r["tcov"] is not None),
    }

    if args.json:
        json.dump({"sprint": sid, "spec": spec_rel, "total": total, "files": rows},
                  sys.stdout, ensure_ascii=False, indent=1)
        print()
        return 0

    head = "| ファイル | prefix | 条項 | cov(行) | cov(見出し) | rcov(行) |"
    sep = "|---|---|---:|---:|---:|---:|"
    if spec_rel:
        head += " rcov+(行) |"
        sep += "---:|"
    head += " tcov | 単独 |"
    sep += "---:|---:|"
    print(head)
    print(sep)
    for r in rows:
        line = "| %s | %s | %d | %s | %s | %s |" % (
            r["file"], r["prefix"], r["clauses"],
            pct(r["cov"], r["lines"]), pct(r["hcov"], r["headings"]),
            pct(r["rcov"], r["lines"]))
        if spec_rel:
            line += " %s |" % pct(r["rcov_plus"], r["lines"])
        line += " %s |" % (pct(r["tcov"], r["clauses"]) if r["tcov"] is not None else "—")
        line += " %s |" % (pct(r["solo"], r["leaf_clauses"]) if r["leaf_clauses"] else "—")
        print(line)
    line = "| **全体** | | %d | %s | %s | %s |" % (
        total["clauses"], pct(total["cov"], total["lines"]),
        pct(total["hcov"], total["headings"]), pct(total["rcov"], total["lines"]))
    if spec_rel:
        line += " %s |" % pct(total["rcov_plus"], total["lines"])
    line += " %s |" % pct(total["tcov"], total["clauses_spec"])
    line += " %s |" % (pct(total["solo"], total["leaf_clauses"]) if NORM_ENABLED else "—")
    print(line)
    print()
    if spec_rel:
        print("rcov+ は %s（%s）の参照 %d 件を入る辺に加えた値。" % (
            spec_rel, sid or "指定パス", len(spec_refs)))
        newly = sorted(i for r in rows for i in r["covered_by_sprint"])
        print("sprint の参照で初めて被参照になる条項: %s" % (
            ", ".join(newly) if newly else "なし"))
        print()
    if not NORM_ENABLED:
        print("単独率は docs.normativeDirs / docs.commonFiles が無いので数えない。")
    if args.untested:
        n_untested = total["clauses_spec"] - total["tcov"]
        print("テストから参照されない %s の条項（%d 件）:" % (SPEC_DIR.rstrip("/"), n_untested))
        for r in rows:
            if r["untested"]:
                print("- %s: %s" % (r["file"], " ".join(r["untested"])))
        print()
    n_unref = total["clauses"] - total["rcov_clauses"]
    if not args.unreferenced:
        print("未被参照の条項は %d 件。ID を見るには --unreferenced を付ける。" % n_unref)
        return 0
    print("未被参照の条項（ベース仕様のどこからも参照されない。%d 件）:" % n_unref)
    for r in rows:
        if r["unreferenced"]:
            print("- %s: %s" % (r["file"], " ".join(
                "%s（%s）" % (i, nodes[i]["title"]) for i in r["unreferenced"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
