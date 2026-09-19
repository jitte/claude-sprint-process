---
xref-prefix: GATE
---

# ゲートツール

> ステージ遷移時に完了条件を機械で検証するツール群の仕様。
> ステージの意味と遷移規則は `docs/06_process/sprint-process.md`。

---

<a id="GATE-1"></a>
## [GATE-1] 1. 仕組み

| 部品 | 場所 | 役割 |
|------|------|------|
| ランナー | `harness/tools/gate-check.sh` | ステージのツール一覧を読み、順に実行する。1 つでも fail なら全体を fail にする |
| 定義（正本） | `sprint.config.json` の `gates` | `{ "code": {...}, "docs": {...} }`。kind 別にステージ → ツール名の配列を持つ |
| ツールの置き場 | `sprint.config.json` の `gateToolsDirs` | ディレクトリの配列。ランナーはこの順に `<dir>/<tool>.sh` を探し、先に見つかった方を使う。見つからなければ「script not found」で基盤（4） |
| ツール（汎用） | `harness/gate-tools/<tool>.sh`（`gateToolsDirs` の 1 つ目） | ランナーからは引数なしで起動され、終了コードで結果を返す。手動では引数で検査を絞れる。プロジェクトのドメイン・技術名・配置に依存しない（設定から読む） |
| ツール（プロジェクト固有） | `gateToolsDirs` の 2 つ目以降 | 同じ起動規約。プロジェクトのドメインに依存する検査を置く |

`harness/bin/sprint stage <STAGE>` が前進時に自動で呼ぶ。手動実行は `bash harness/bin/sprint gate <STAGE>`。

- kind は `.sprint/flags.json` の `sprints[id].kind`（未設定は `code`）。`gate-check.sh` が kind でゲートセットを選ぶ
- ランナーはループ前に `SPRINT_GATE=1` を export する。ツールは `harness/lib/env.sh` の `sprint_via_gate` でこの有無を読み、手動実行とゲート経由を判別する（例: `size-audit` は手動なら 🟡 を失敗、ゲート経由なら通過にする）
- `sprint.config.json` が無いとき、ランナーとツールは「sprint.config.json が無い: <path>」を 1 行出して基盤（4）を返す
- ツールはステージを知らない。ステージによって厳しさが変わる検査は別のツールにする（`tdd-exists` / `tdd-audit`、`spec-lint` / `spec-seal`）

### 失敗の分類と推奨遷移先

ランナーはゲート失敗を 4 分類し、推奨遷移先を表示する。遷移は実行しない。巻き戻し先の判断は人間が行う。

| 終了コード | 分類 | 意味 | 推奨遷移先 |
|---|------|------|----------|
| 1 | 仕様 | SPEC/TEST の不在・封印の不一致・書式不備・条項参照の破れ | PLAN |
| 2 | 実装 | lint / typecheck / build の失敗、成果物文書の未執筆（docs） | BUILD |
| 3 | テスト | テストの失敗・skip・実行証跡の不足 | BUILD |
| 4 | 基盤 | テスト未実行・結果ファイルの陳腐化・記入漏れ | 据え置き（現ステージで修復） |

失敗内容によって分類が変わるツール（`results` / `impl-sync` / `tdd-audit` / `size-audit`）は自分で 2〜4 を返す。それ以外の非ゼロは `gate-check.sh` の `default_class()` に従う。複数の分類が同時に出た場合は最も上流（数値が小さいもの）を推奨の根拠にする。

## 2. ツール一覧（汎用 12 本）

ステージへの割り当ては `sprint.config.json` の `gates` を読む。ここには写さない。

| ツール | 目的 | 引数（手動で絞るとき） | 仕様 |
|--------|------|------|------|
| `spec-files-exist` | SPEC.md / TEST.md の存在確認 | — | — |
| `spec-seal` | 封印ハッシュ一致（`bash harness/bin/sprint seal-verify`） | — | [PROC-2](sprint-process.md#PROC-2) |
| `spec-lint` | 条項参照 V1〜V3 / V5 / V6 / V8〜V11・SPEC の「0. 参照する共通条項」節の扱い・Test ID の形式 | `graph` / `refs` / `test-id` | §3.1 |
| `impl-sync` | 実装と仕様の集合の双方向比較（公開ルート） | `routes` | §3.2 |
| `verify` | 設定の tasks（lint / typecheck / build / test / e2e）が通る。ゲートには割り当てない（`results` が証跡で判定する）。手動実行用 | task 名 | §3.3 |
| `results` | 実行証跡の鮮度・green。証跡契約の JSON（§6）だけを読む | `fresh` / `green` | §3.4 |
| `tdd-exists` | TEST.md の Test ID がテストソースに存在する（skip 許容。BUILD 用） | — | §3.5 |
| `tdd-audit` | Test ID が実行証跡で pass している | — | §3.5 |
| `size-audit` | 801〜1200 行は通過して報告、1201 行以上は却下（`SIZE_WARN` / `SIZE_LIMIT` で変更可） | — | — |
| `doc-exists` | README が列挙した成果物文書が実在する（docs） | — | §3.6 |
| `doc-verified` | TEST.md の UNSEAL の判定表で、最新の巡の判定が 🟢（docs） | — | §3.6 |
| `ship-closed` | README の「8. SHIP」節にコミットハッシュが記入済み | — | — |

## 3. ツール仕様

### 3.1 spec-lint — 仕様の機械検査

4 つの検査を全部走らせてから集約する。失敗分類は 1（仕様）。PLAN に巻き戻して直す。

<a id="GATE-2"></a>
#### [GATE-2] 3.1.1 graph — 条項参照の検証

**ベース仕様の共通事項は再記述せず `[ID](<相対パス>#ID)` で参照する。** 同じ規範を複数の仕様書に書くと、書いた箇所は守られ、書き落とした箇所が壊れる。共通する規範は 1 つの条項として一度だけ定義する。記法は [RULE-1](../05_specifications/README.md#RULE-1) に置く。

`harness/tools/spec-graph.sh verify`（本体は `harness/tools/spec-graph.py`）が次を検証する。

| # | 検証 | fail 条件 |
|---|------|----------|
| V1 | prefix の一意性 | 2 ファイルが同じ `xref-prefix` を宣言 |
| V2 | 条項 ID の一意性 | 同一 ID が 2 回宣言される／ID の prefix がファイル宣言と違う |
| V3 | 参照の実在 | 参照の指す条項が無い |
| V5 | impl パスの実在 | frontmatter の `impl` が存在しないパス |
| V6 | frontmatter | `xref-prefix` が英大文字 2〜6 字でない／`layer` があり値が 7 値以外／条項の見出し `[ID]` を持つ md に `xref-prefix` が無い |
| V8 | リンクの相対パスの実在 | 参照リンクの相対パスが指すファイルが無い |
| V9 | アンカーの実在 | 参照先ファイルに対応する `<a id>` が無い |
| V10 | 参照の循環 | 条項参照グラフ（ノード = 条項、エッジ = 条項本文の中の参照 → 条項）に強連結成分がある。自己参照も循環。成分ごとに 1 行 `A -> B -> A` |
| V11 | 節番号参照 | コードフェンスの外の行で、ファイル名（`.md`）の後 8 文字以内に § が来る（第 1 パターン）、または識別子の形の語（`_` か `-` でつないだ語・2 字以上の大文字の語・2 桁以上の数字）か設定 `docs.docAliases` の別名の直後に § と数字が来る（第 2 パターン。略称での参照）。普通の語の直後の節番号と、同一ファイル内の節番号は対象外。`ファイル:行` で出す |

- 検証範囲: 条項を持つファイル = 生きている文書（ディレクトリの一覧は `sprint.config.json` の `docs.livingDirs` が正本で、`xref.sh` と `clause-anchors.py` も同じ一覧を読む）のうち frontmatter に `xref-prefix` を宣言した md（README.md を含む）。フォルダも `layer` も関係ない。手順書に相当するディレクトリの md は `xref-prefix` を宣言しない（参照元としては走査する）。V1/V2/V5/V6/V10 はこの集合を見る。V3/V8/V9/V11 は生きている文書（テンプレートを含む）＋ 未封印のスプリント SPEC ＋ リポジトリ直下の md を参照元として検証する。V8/V9 は `docs.templates` 配下を除く（相対パスをコピー先の深さで書くため、テンプレート自身の位置では解決しない）。`xref-prefix` を宣言しない md は消費者として扱い、全条項を参照できる（V10 のエッジにしない）
- **V3 はテストの名前（[TSTD-6](../04_standards/02_testing.md#TSTD-6)）も参照元とする。V8 / V9 / V11 はテストに適用しない。** テストファイルは `sprint.config.json` の `components[*].tests` の glob に一致するファイル（`.gitignore` にディレクトリ名として書かれた配下を除く）。読むのは、行頭の空白の後に `describe(` / `it(` / `test(`（`.識別子` が 0 個以上続く形。`test.describe(` / `it.each(`）で始まる行の `[[ID]]` だけで、その行が `(` で終わるときは次の行を連結して読む。コメント・fixture の文字列・本文は読まない。`index` / `reverse` / `diff` / `files` / `deps` はテストの参照を文書の参照と同じ形で出す（`index` の edges は `from` が null）。`layers` は条項を持つファイル間だけを数える
- **封印済みスプリント SPEC は参照元として検証しない**（歴史記録のため書き換えない）
- スプリント SPEC は SPEC.md の「0. 参照する共通条項」節で従う条項を宣言する（テンプレート）
- 走査ルートは `SPEC_GRAPH_ROOT` で差し替えられる。設定は `SPRINT_CONFIG`（省略時 `<走査ルート>/sprint.config.json`）から読む（fixture テスト `harness/tests/test_runner.py`）

補助コマンド（ゲートには含めない）:

| コマンド | 出力 |
|---------|------|
| `spec-graph.sh files` | 条項を持つファイルを相対パス・prefix・layer（無ければ `-`）・条項数・被参照数で 1 行ずつ出す |
| `spec-graph.sh layers` | 参照元の layer × 参照先の layer の参照エッジ数の表。方向は指標であり、fail させない |
| `spec-graph.sh reverse <ID>` | 参照元の逆引き（影響範囲） |
| `spec-graph.sh deps <FILE>` | そのファイルが参照する条項 |
| `spec-graph.sh resolve <FILE>` | 原文と、そこから到達する条項の本文を 1 件 1 回ずつ出す。qa が §0 の「扱い」の妥当性を判定するときに使う。循環は終端し、注記（`<!-- resolve: cycle ... -->`）が付く |
| `spec-graph.sh diff <git-ref>` | 内容の変わった条項とその参照元（陳腐化検出。fail させない通知）。条項の範囲は宣言行から、次の条項の宣言行（または同じか浅い階層の見出し行）の手前までで、末尾のアンカー行（`<a id=…>`）と空行は含めない。条項を新設しても、その前の条項は changed に現れない |

**機械検査の限界**: グラフは参照構造の抜け漏れを止める。条項本文の意味の誤り（存在しない識別子・向きの反転）は止めない。本文の突合は qa が読んで行う（[TSTD-2](../04_standards/02_testing.md#TSTD-2)）。

<a id="GATE-3"></a>
#### [GATE-3] 3.1.2 refs — 参照した条項のテストの扱い

**参照した条項ごとに、テストをどう扱うかを宣言する。** 参照 1 件につきテスト 1 件を要求すると、テストがノルマになり、必ず pass する分岐や重箱の隅の検証が生まれる。さらに参照を避けて転記する動機を作る。転記は条項参照が解こうとしている問題である。よって強制するのは判断の記録であって、テストではない。

active スプリントの SPEC.md の「0. 参照する共通条項」節（`## 0. 参照する共通条項`）を検査する。

| # | fail 条件 |
|---|----------|
| 1 | §0 の見出しが無い（節ごと省略して迂回できない） |
| 2 | §0 に条項参照の表行も `（参照なし）` 行も無い（受理するのは新記法だけ。二重括弧の旧記法は表行として拾わない） |
| 3 | 「テストの扱い」列または「Test ID / 理由」列が空である（空 = 空文字・空白のみ・`—`・`-`・`TBD`） |
| 4 | 「テストの扱い」列の値が 4 値（新規 / 改修 / 流用 / 不要）以外である |

- **機械は形だけを見る。** 扱いの妥当性は qa が REVIEW で `resolve` を使って判定し、README の「4. REVIEW」節「参照条項の監査」に記録する。DOCS では `diff` で宣言と実績を突合する（qa.md の R10 / D4）
- **fail 条件を後から緩めない**
- 参照が無いスプリントは `| （参照なし） | — | 不要 | 共通条項に依存しない |` の 1 行を書く。第 1 列が条項参照の形式でないため 3・4 の対象外になり、判断を記録したことだけが残る
- 読むのは active スプリントの `SPEC.md` 1 本だけで、封印済みの過去 SPEC は読まない。過去スプリントを巻き戻して未封印にしたときは、その §0 を新記法に直す
- `spec-check.sh` の検査 3（Test ID の定義 ↔ 参照）は §0 の表を対象外にする。§0 には他スプリントの Test ID が恒常的に載るため、対象に含めると照合が壊れる
- 旧スプリントの Test ID は非一意である（封印済みは旧形式 `TEST-x.x`）。引用は `<sprint_id> TEST-x.x` の形で書く
- 対象は `SPEC_REFS_TARGET` で差し替えられる（fixture テスト `harness/tests/test_spec_graph.py`）

<a id="GATE-4"></a>
#### [GATE-4] 3.1.3 test-id — Test ID の形式

**Test ID は `TEST-<sprint_id>-<major>.<minor>` の形で書く。** 例: `TEST-3-1.1`。

`<sprint_id>` は `.sprint/flags.json` の active。`<major>` / `<minor>` はスプリント内で 1 から振ってよい。前置により ID は全スプリントで一意になり、長命なテストファイル上での衝突が起きない。

active スプリントの TEST.md のテスト定義行（先頭セルが Test ID の行）の ID がすべてこの形式かを検査する。

- **旧形式（前置なし）の ID は書き換えない。** 形が違うため新形式と衝突しない
- `TDD_ID_PATTERN` は新旧どちらにも一致する（`TEST-[0-9]+(-[0-9]+)*\.[0-9]+[a-z]?`）
- kind=docs の `DOC-x.x` は対象外（テスト定義行なしとして通過する）
- 対象は `TID_TEST_MD` / `TID_SPRINT_ID` で差し替えられる

### 3.2 impl-sync — 実装と仕様の集合の双方向比較

**実装 → 仕様の方向の陳腐化を機械で検出する。** `spec-lint` は条項側の変化しか見ず、V5 はパスの実在しか見ない。公開ルートが増減しても仕様は黙って古くなる。

検査は `routes`（§3.2.1）。失敗分類は検査が返す（1 = 仕様 / 2 = 実装 / 4 = 基盤）。同じ枠組みで実装 ↔ 仕様の集合を比べるプロジェクト固有の検査は `gateToolsDirs` の 2 つ目以降に置き、`sprint.config.json` の `gates` が別のツールとして呼ぶ。

- 実行タイミングは TEST ゲートだけ。REVIEW 時点では実装が無く、実装側の集合を取れない。DOCS / SHIP に重ねて置かない（二重に置くと片方だけ更新される）
- **実装側の集合を正規表現で読まない。** 実装を import して出させる。TypeScript のオブジェクトキーは `'x':` / `"x":` / `x:` の 3 通りで書け、コメント・文字列・正規表現リテラルの中にも波括弧が現れる。正規表現では変種を列挙しきれず、拾えなかった要素が集合から黙って消える。**集合が縮む方向の失敗を黙って通さない。** このゲートが検出すべき「実装が増えたのに仕様が追随していない」状態を、ゲート自身が隠すためである
- 別の言語・フレームワークで再実装しても、差し替えるのは取得コマンドだけである

<a id="GATE-5"></a>
#### [GATE-5] 3.2.1 routes — 公開ルート集合

`bash harness/bin/sprint api-routes`（= `harness/tools/api-routes.sh verify`）が、実装の公開ルート集合と `docs.specDir` が書くルート集合を双方向に比較する。記法は [RULE-1](../05_specifications/README.md#RULE-1)「API ルートの書き方と `api-routes` 宣言」に置く。

| 側 | 取り方 |
|----|-------|
| 実装 | 取得コマンドの既定値は `sprint.config.json` の `sets.routes.implCmd`（プロジェクトルートで `bash -c` する）。実装のルーティング定義を import してルート一覧を出力するコマンドを設定する。入れ子のルート登録やファクトリ関数を正規表現では辿れない |
| 仕様 | `docs.specDir` 配下の Markdown から `<METHOD> <path>` を抽出する。`README.md` は対象外 |

除外・展開の規則は仕様側の ` ```api-routes ` フェンス宣言（`expand` / `alias`）と、ルート名に依存しない正規化規則だけで表現する。**スクリプトはルート名を一切持たない。**

| # | 正規化・除外 | 理由 |
|---|------------|------|
| 1 | メソッドとパスの間の空白 1 文字以上を許容する | コードブロック内の桁揃え |
| 2 | パスのトークンを `A-Z a-z 0-9 / : { } _ . - *` の最長一致で切る | 仕様は全角括弧・中黒・角括弧を含む散文の中にパスを書く。空白まで読むと偽陽性が出る |
| 3 | `/api/v1` の有無を問わず抽出し、外した形に揃える | 画面仕様の「使用 API」表は省略形で書く |
| 4 | パスパラメータを `/:p` に畳む | 仕様の `:id` と実装の `:transactionId` を同一視する |
| 5 | `*` を含むパスを仕様側から除外する | `GET /masters/*` は総称表記であり単一のルートを指さない |
| 6 | ` ```mermaid ` フェンス内を除外する | 図の participant 名は API の定義ではない |
| 7 | ` ```api-routes ` フェンス内を除外する | 宣言であって定義ではない |

- 失敗分類: **1 = 実装にあって仕様に無い** → PLAN に巻き戻して条項を書く。**2 = 仕様にあって実装に無い** → BUILD に戻して実装する。両方向に差がある時は 1 を優先する（仕様が上流）
- `仕様にあって実装に無い` の各行には出所のファイル名と行番号を添える
- **未実装・未記述を許容する語彙を宣言に足さない。** 空振りする宣言（使われないプレースホルダ・実在しない実装パス）も fail させる
- **宣言を実装側（コード・コメント・設定）に置かない。** 読み取り範囲は `docs.specDir` 配下に限る
- 取得手順は `API_ROUTES_IMPL_CMD`（実装ルートの取得コマンド。無いとき `sets.routes.implCmd`）と `API_ROUTES_ROOT`（仕様スキャンの起点。無いときプロジェクトルート。`docs.specDir` はこの起点からの相対）で差し替えられる。環境変数は設定より優先する（fixture テスト `harness/tests/test_api_routes.py`・`harness/tests/test_runner.py`）

### 3.3 verify — 実装とテストが通る

設定の `tasks` の順（lint → typecheck → build → test → e2e）に `bash harness/bin/sprint run <task>` を実行し、証跡契約の JSON（§6）で判定して、最初に失敗した task で止める。失敗分類は 2（実装）。

| task | errors / failed | warnings / skipped | 結果 |
|---|---|---|---|
| lint / typecheck / build | errors > 0 | — | fail（修正必須・override 不可） |
| lint / typecheck / build | 0 | warnings > 0 | fail。`GATE_ALLOW_WARN=1`（ユーザが go と判断）のときだけ通過 |
| test / e2e | failed > 0 | — | fail |
| test / e2e | 0 | skipped > 0 | fail |
| どれも 0 かつ status = pass | | | pass |

- `bash harness/bin/sprint run all` は BUILD の完了条件で、tasks の順に全部を回す（動詞単位で fail-fast）
- 本ツールはゲートに割り当てない。全部を実行し直すと遷移 1 回に 3〜5 分かかり、直後の `results` が同じ証跡を検査するので二重になる。TEST ゲートは `results` が実行証跡（鮮度・green・skip）で判定する

### 3.4 results — 実行証跡

2 つの検査を全部走らせてから集約する。失敗分類は検査が返す（複数なら最も上流）。

| 検査 | 見るもの | 失敗分類 |
|------|---------|---------|
| `fresh` | 設定の全 `(component, task)` について証跡ファイル `<evidence.dir>/<component>.<task>.json` があり、その `finished_at` が全コンポーネントの `src` ∪ `tests` に一致するファイルの最終更新以上である | 4（基盤。再実行で解消） |
| `green` | 証跡の `status` が `pass`。test / e2e は `counts.failed` = 0 かつ `counts.skipped` = 0。lint / typecheck / build は `errors` = 0 かつ `warnings` = 0（`GATE_ALLOW_WARN=1` のときは warnings を見ない）。`.sprint/test-fails.json` は読まない（hook が main の Bash 直後にしか書かず、ゲート内の再実行で古くなる。`bash harness/bin/sprint status` の表示にだけ使う） | 2（lint / typecheck / build）/ 3（test / e2e の失敗・skip）/ 4（証跡が無い） |

`.partial.json`（部分実行の証跡。§5）は読まない。`bash harness/bin/sprint status` の「証跡の鮮度」は `fresh` と同じ判定を使う。

証跡の読み取りは `harness/lib/evidence.sh` にだけ置く。読むのは証跡契約の JSON（§6）だけで、ランナーの出力文字列は読まない。`results` / `verify` / `tdd-audit` / `record-test-fails.sh` / `sprint status` はそれを呼ぶ。

<a id="GATE-7"></a>
### [GATE-7] 3.5 tdd-exists / tdd-audit — テスト実行証跡

計画したテスト（TEST.md の Test ID）が無視されず、必ず実行され、pass したことを保証する。テストコードが「どう書かれているか」（grep による静的照合）ではなく、「実行されて何が起きたか」（証跡契約の JSON の `tests[]`。§6）だけを判定根拠にする。

静的照合は書き方の変種に対していたちごっこになる。skip 構文の変更・コメントアウト・`.only` による暗黙無効化・コメント内への ID 記載・過去スプリントの同名 Test ID への相乗り。いずれも grep では検出漏れ・誤検出が発生する。実行証跡ベースでは、これらすべてが「実行結果に要求を満たす記録がない」という単一の判定で fail する。

**仕組み:**

1. 実行証跡の常時出力: `bash harness/bin/sprint run test` / `run e2e` が、アダプタの `convert-evidence` を通して証跡契約の JSON（`<evidence.dir>/<component>.<task>.json`。`tests[]` に全テストのファイル・名前・ステータス）を書く（§5 / §6）
2. 照合（`tdd-audit.sh`）: 設定の全 `(component, test|e2e)` の証跡の `tests[]` を集め、TEST.md のテスト定義行（表の先頭セルが Test ID の行）ごとに、行に記載されたテストファイル（basename で照合）内で「テスト名に ID を含み status=passed」の記録があることを要求する。`.partial.json` は読まない。証跡が 1 つも無ければ基盤（4）
3. fail 条件: 記録なし（MISSING）／skipped・todo・failed・flaky（NOT-PASS）／行にテストファイル記載なし（FORMAT）

`tdd-exists.sh` は BUILD 用の緩い版で、Test ID がテストソース（`components[*].tests` の glob に一致するファイル）に存在するかだけを見る（skip 許容）。厳しさが違うので別ツールにする。

**TEST.md 規約**（テンプレートに反映済み）:

- テスト定義行にはテストファイル列が必須。ID はそのファイル内でのみ照合される（過去スプリントの同名 ID と衝突しない）
- テストの実行名（`describe` と `it`/`test` の連結名 = レポーターの fullName）に Test ID を含める。`it()` 名に直接書くのが基本形だが、`describe('TEST-x.y ...')` で囲む形でも照合される。**コメント内の ID は照合されない**
- 実テストを持たない検証項目（行数確認・集合確認・手動確認）には Test ID を振らず、表の外に記載して qa が TEST ステージで実測する

**他プロジェクトへの展開**: `tdd-audit.sh` / `tdd-exists.sh` はランナーの出力形式を知らない。ランナー固有の JSON を証跡契約に直すのはアダプタの `convert-evidence`（§5）である。環境変数: `TDD_TEST_MD`（TEST.md のパス。省略時 `.sprint/flags.json` の active sprint から解決）／`TDD_ID_PATTERN`（Test ID の正規表現。省略時 §3.1.3 の形）。

### 3.6 doc-exists / doc-verified — 文書スプリント用

- `doc-exists.sh`: README 内の `docs/…\.md` パス（自スプリント 07_plans を除く）がすべて実在するか。失敗分類 2（docs では執筆 = 実装相当）
- `doc-verified.sh`: TEST.md の UNSEAL ブロックの判定表（見出し行に「判定」列を持つ最初の表）を読み、判定が記入された最後の行（最新の巡）が 🟢 か。失敗分類 3。表のセルだけを見る。散文の 🔴 / 🟢 は判定に使わない。記入前の雛形の行（🔴🟡🟢）は未記入として飛ばす

---

## 4. 実装上の規則

- **ツールはステージを知らない。** 厳しさがステージで変わる検査は別ツールに分ける
- **実装側の集合を正規表現で取らない。** 実装を import して集合を出させる（§3.2）
- **検査を通すために検査を弱めない。** fail 条件を緩める変更、乖離を許容する宣言語彙の追加は禁止する
- **同じ検査を複数のステージに置かない。** 二重に置くと片方だけ更新される
- **bash の中に Python を書かない。** 本体は `.py` に出し、bash は薄いラッパーにする（`spec-graph.py` / `clause-anchors.py`）。単体で起動でき、fixture テストが書ける
- ツールは終了コードで分類を返す（§1）。出力が空だとランナーが終了コードを添える
- **`set -o pipefail` の下で「生成 `| grep -q`」を書かない。** `grep -q` は一致で読み終わり、書き手が続きを書くと SIGPIPE（141）でパイプラインが失敗する。集合の所属判定は `grep -qx "$x" <<<"$(生成)"` の here-string で読む
- **ハーネス本体（`harness/` の lib・tools・gate-tools・hooks・bin）は技術名（ランナー・パッケージマネージャ）とプロジェクトの配置を持たない。** 配置・コンポーネント・タスク・証跡・集合・ゲートは `sprint.config.json` から読む。技術名を持つのは `harness/adapters/` だけ

---

## 5. タスク契約とアダプタ

**動詞**は `lint` `typecheck` `build` `test` `e2e` の 5 つ。`sprint.config.json` の `tasks` の並びがゲートと `sprint run all` の実行順である。コンポーネントは `adapters` に持つ動詞だけを実行する。持たない動詞は「対象外」であり失敗ではない。

**アダプタ**は `harness/adapters/<name>/` のディレクトリで、次の実行ファイルを持つ。技術名（ランナーの起動方法・出力形式）を知るのはアダプタだけである。

| ファイル | 引数 | 役割 |
|---|---|---|
| `run-lint` / `run-typecheck` / `run-build` / `run-test` | `[<ランナーへの追加引数>...]` | コンポーネントのディレクトリ（`SPRINT_COMPONENT_DIR`）で cwd を取り、ランナーを起動する。標準出力・標準エラーをそのまま流す。終了コードはランナーのもの。ランナー固有の結果（JSON 等）は `SPRINT_RAW_DIR` に書く |
| `convert-evidence` | `<verb>` | `SPRINT_RAW_DIR` のランナー固有の出力（本文 `stdout.txt` と JSON）を読み、証跡契約の JSON（§6）を標準出力に書く |

- 動詞 `e2e` はアダプタの `run-test` に対応する（E2E のランナーはテストランナーである。区別はゲートのためであってランナーのためではない）
- アダプタが受け取る環境変数: `SPRINT_ROOT`（プロジェクトルート）・`SPRINT_COMPONENT`・`SPRINT_COMPONENT_DIR`（絶対）・`SPRINT_TASK`（動詞。`e2e` を含む）・`SPRINT_RAW_DIR`（ランナー固有の出力先。`<evidence.dir>/raw/<component>.<task>/`）・`SPRINT_RUN_EXIT`（`convert-evidence` にだけ渡す。`run-<verb>` の終了コード）
- アダプタは `package.json` の `scripts` を経由せず、ランナーの実体を直接起動する。パッケージマネージャの別を持たない
- reporter の指定はアダプタが CLI で渡す。プロジェクトのランナー設定に reporter 設定は要らない。アダプタを書く前に、そのランナーで CLI の指定が設定ファイルの同名 reporter のオプションに勝つかを 1 回試走して確かめる（勝たないランナーがある）
- 同梱するアダプタ: `node-vitest`（test）・`eslint-tsc`（lint / typecheck）・`vite-build`（build）・`playwright`（test）。置き場は `SPRINT_ADAPTERS_DIR`（省略時 `harness/adapters`）で差し替えられる（fixture テストの入口）

**ランナー** `bash harness/bin/sprint run <task>|all [<component>] [-- <追加引数>...]`:

1. `tasks` の順に、`<task>` を `adapters` に持つコンポーネントを設定の並び順で処理する。`<component>` を渡したときはそれだけ
2. コンポーネントごとに: `pre.<task>` があればプロジェクトルートで `bash -c` し、非ゼロなら「`<component>.<task>`: pre が失敗（exit n）」を出して 4 で止める。次にアダプタの `run-<verb>` を起動し、標準出力と標準エラーを `<raw>/stdout.txt` に書きながら端末にも流す。次に `convert-evidence <verb>` の出力を `<evidence.dir>/<component>.<task>.json` に書く
3. 追加引数がある実行は部分実行である。証跡は `<component>.<task>.partial.json` に書き、ゲートと `sprint status` は読まない
4. 終了コード: 全コンポーネントの `run-<verb>` が 0 なら 0。1 つでも非ゼロなら、最後まで走らせてから 2。`run all` は動詞単位で fail-fast する（ある動詞で 2 が出たら次の動詞に進まない）。アダプタが無い（`harness/adapters/<name>/` が存在しない）は「アダプタが無い: <name>（<component>.<task>）」を 1 行出して 4 で止め、他のコンポーネントは処理しない
5. `sprint run` の直後に `harness/hooks/record-test-fails.sh` が証跡から `.sprint/test-fails.json` を書く

### 5.1 アダプタの開発

同梱の 4 つに無いランナーを使うときは、**取り込み先のリポジトリでアダプタを書く。** ハーネス本体には足さない。本体は技術名を持たない。

1. **ランナーの CLI を 1 回試走する。** reporter の指定と結果ファイルの出力先を CLI から指定できるかを確かめる。設定ファイルの reporter が CLI に勝つランナーがある
2. `harness/adapters/<name>/run-<verb>` を書く。`SPRINT_COMPONENT_DIR` で cwd を取り、ランナーを直接起動する。標準出力と標準エラーはそのまま流す。終了コードはランナーのものを返す。ランナー固有の結果は `SPRINT_RAW_DIR` に書く
3. `harness/adapters/<name>/convert-evidence` を書く。`SPRINT_RAW_DIR` の結果と `SPRINT_RUN_EXIT` を読み、証跡契約の JSON（§6）を標準出力に書く。`test` と `e2e` は `tests[]` に全テストの `file`・`name`・`status` を入れる（`tdd-audit` がこれで Test ID を照合する）
4. `sprint.config.json` の `components[].adapters.<verb>` に `<name>` を書く
5. `bash harness/bin/sprint run <task> <component>` で走らせ、`<evidence.dir>/<component>.<task>.json` を `jq` で読み、証跡契約の形と一致するかを確かめる
6. `bash harness/bin/sprint gate TEST` を通す。`results` が鮮度と green を判定する

- 置き場は `harness/adapters/` である。再取り込み（README の「2.6 再取り込み（更新）」）は `harness/` を上書きで写す。書いたアダプタは版管理に入れ、再取り込みの後に残っているかを確かめる
- `SPRINT_ADAPTERS_DIR` は置き場そのものを差し替える。同梱の 4 つは見えなくなる。fixture テストの入口であり、プロジェクトの 2 つ目の置き場ではない
- ランナーの出力文字列を読むのは `convert-evidence` だけである。ゲートと `bash harness/bin/sprint status` は証跡契約の JSON しか読まない

## 6. 証跡契約

`<evidence.dir>/<component>.<task>.json`。1 実行 1 ファイル。読む側は `harness/lib/evidence.sh` だけで、ランナーの出力文字列を読む関数は無い。

```json
{
  "schemaVersion": 1,
  "component": "backend", "task": "test", "adapter": "node-vitest",
  "status": "pass",
  "counts": { "passed": 412, "failed": 0, "skipped": 0 },
  "errors": 0, "warnings": 0,
  "tests": [ { "file": "src/x.test.ts", "name": "TEST-3-1.1 [[GATE-1]] ...", "status": "passed" } ],
  "started_at": 1788948000, "finished_at": 1788948120
}
```

| 項目 | 意味 | 動詞 |
|---|---|---|
| `status` | `pass` / `fail`。`run-<verb>` の終了コードが 0 かつ `counts.failed` = 0 かつ `errors` = 0 なら `pass` | 全部 |
| `counts` | テストの件数（`passed` / `failed` / `skipped`）。E2E は `flaky` を別に数える | test / e2e |
| `errors` / `warnings` | lint の error / warning の合計、typecheck の error 行数。build は失敗のとき errors = 1 | lint / typecheck / build |
| `tests[]` | 1 テスト 1 要素。`file` はコンポーネントのディレクトリからの相対、`name` は実行名（describe と it の連結）、`status` は `passed` / `failed` / `skipped` / `flaky` / `todo` | test / e2e |
| `started_at` / `finished_at` | epoch 秒。鮮度判定は `finished_at` を使う | 全部 |

- 単体テストのランナーの `pending` は `skipped` に、`todo` はそのまま `todo` に写す。`counts.skipped` は `skipped` だけを数える（`todo` は `tests[]` に残り、`tdd-audit` が NOT-PASS にする）
- E2E は spec 単位に集約する。`unexpected` を含めば `failed`、`flaky` を含めば `flaky`、`skipped` を含めば `skipped`、それ以外は `passed`。retry で通った flaky は `pass` にしない（`status` が `fail` になる）
- `.sprint/test-fails.json` は `{ "total": n, "tasks": { "<component>.<task>": n, ... }, "recorded_at": "..." }`。n は test / e2e なら `counts.failed`、lint / typecheck なら `errors`、build なら status が fail のとき 1

## 7. 同梱単位の見出し

templates（`harness/templates/`。取り込み時に `docs.templates` へ写す）と検査は同梱単位として固定する。検査が読む見出し文字列は設定にしない。取り込み時に埋めるのはプレースホルダ（`{{spec_docs}}` / `{{common_clauses}}` / `{{static_check_example}}` / `{{run_commands}}`）だけで、見出しは変えない。

| 文字列 | 場所 | 読む検査 |
|---|---|---|
| `## 0. 参照する共通条項` | SPEC.md | `spec-lint refs`（[GATE-3](#GATE-3)） |
| `## 実装単位と依存関係` | SPEC.md | `spec-check`（検査 2） |
| `## EARS 要件` | SPEC.md | `spec-check`（検査 1・2） |
| `## テスト仕様` | TEST.md | `spec-check`（検査 3。テスト定義行の範囲の始点） |
| `## 既存テストの改修対象` | TEST.md（任意） | `spec-check`（検査 3。テスト定義行の範囲の終端） |
| `## 網羅性マトリクス` | TEST.md | `spec-check`（検査 1・3） |
| `## 実行手順` | TEST.md | `spec-check`（検査 1・3。網羅性マトリクスの範囲の終端）。`{{run_commands}}` の置き場 |
| `コミットハッシュ:` | README.md「8. SHIP」 | `ship-closed` |
| `<!-- UNSEAL:BEGIN -->` / `<!-- UNSEAL:END -->` | SPEC.md / TEST.md | `spec-seal`（[PROC-2](sprint-process.md#PROC-2)）・`edit-scope-gate.sh`・`doc-verified` |
| 判定表（見出しに `判定` 列を持つ表）の判定セル 🟢 / 🟡 / 🔴 | TEST.md の UNSEAL | `doc-verified` |
