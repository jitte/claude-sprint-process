---
xref-prefix: PROC
---

# スプリントプロセス

> エージェント起動制御を主目的とした簡易プロセス。
> ベース仕様（docs/05_specifications）は確定済み。
> ゲートツールの仕様は `docs/06_process/gate-tools.md`、フック・スクリプトの解説は `docs/90_deliverables/hooks-and-scripts.md`。

---

## 1. ステージ定義

```mermaid
flowchart LR
    PLAN --> REVIEW --> build-red --> BUILD --> TEST --> DOCS --> SHIP --> CLOSED
```

| ステージ | 目的 | 起動可能エージェント | main の役割 |
|---------|------|-------------------|------------|
| PLAN | タスク分解・実装方針決定。ベース仕様の更新もここで行う | なし | README / SPEC / TEST 起草 |
| REVIEW | 仕様・方針の整合性確認 | qa | qa の報告を確認し BUILD 可否を判断 |
| build-red | テストスケルトン作成（RED） | tester | 封印・`make test` FAIL 確認 |
| BUILD | 実装 + テスト作成（GREEN + VERIFY） | backend, frontend, tester | エージェント起動・進捗管理 |
| TEST | テスト実行・品質評価 | tester, qa | テスト結果の確認 |
| DOCS | 仕様書へのフィードバック反映 | qa | ドキュメント更新の確認・本体 commit |
| SHIP | 実装品質検証・コミット | qa | qa の実装チェック後に git commit + ブランチ push |
| CLOSED | SHIP 後のメンテナンス | 全て | バグ修正・微調整。main の src 直接編集は不可 |

**プロセス遵守は実装より優先する。** Auto Mode であってもステージ境界のルールは破らない。

---

## 2. Human-in-the-Loop ゲート

以下のステージ遷移は**ユーザーの明示的な指示なしに通過してはならない**。

| ゲート | タイミング | 理由 |
|-------|----------|------|
| **REVIEW → build-red** | REVIEW 完了後 | ユーザーが仕様の妥当性を判断する |
| **TEST → DOCS** | TEST 完了後 | ユーザーがテスト結果と品質を評価する |

`/sprint to <STAGE>` で目標ステージに到達したら、**そのステージの作業完了を報告して停止する**。後続ステージには進まない。Auto Mode であっても同様。

ゲート以外のステージ遷移は main が自律的に実行してよい。

---

## 3. ステージ遷移

main が `bash harness/bin/sprint stage <STAGE>` でステージを遷移する。**flags.json の直接編集は `edit-scope-gate.sh` が deny する。** これによりステージ skip と手書きミスを防ぐ。

`.sprint/flags.json` は `active`（作業中のスプリント ID）と `sprints[id]`（`stage` / `status` / `kind` / `sprint_dir` / `updated_at`）を持つ。`agent-gate.sh` は `active` のステージを参照する。スプリントの中断・再開は `active` の切り替えで行う。

### 遷移ルール

完了条件（人間／main が判断）:

- **PLAN → REVIEW**: タスク定義が完了
- **REVIEW → build-red**: qa が 🔴 = 0 を報告。`bash harness/bin/sprint seal` で封印済み
- **build-red → BUILD**: `make test` が FAIL（RED 確認）
- **BUILD → TEST**: 全 build サブフェーズ完了、`make verify` green
- **TEST → DOCS**: テスト pass、qa の品質評価 OK
- **DOCS → SHIP**: 仕様書が更新済み、本体 commit 済み
- **SHIP → CLOSED**: commit + push 完了

順序の強制（`harness/bin/sprint` が機械的に検証）:

- **前進は次の許可遷移のみ**: PLAN→REVIEW→build-red→BUILD→TEST→DOCS→SHIP→CLOSED
- **後退（前ステージへの巻き戻し）は常に許可**
- **skip は拒否**（例: PLAN→BUILD、REVIEW→TEST）。非ゼロ終了して理由を表示する
- 🚧 ゲート（§2）は人間の承認事項。スクリプトは順序のみを保証し、🚧 の通過可否は main がユーザー指示に従って判断する

### ステージゲート

`harness/bin/sprint` はステージ前進時に `harness/tools/gate-check.sh` 経由でゲートを実行する。**ステージ → ツールの割り当ては `sprint.config.json` の `gates` が正本**（kind 別）。各ツールの仕様は `docs/06_process/gate-tools.md`。

ゲート失敗は 4 分類（仕様 / 実装 / テスト / 基盤）され、推奨遷移先が表示される。遷移は実行しない。巻き戻し先の判断は人間が行う。分類の定義は [GATE-1](gate-tools.md#GATE-1)。

### 巻き戻し

問題が見つかった場合、main が `bash harness/bin/sprint stage <前のステージ>` で前のステージに戻す。

- TEST で不具合 → BUILD に戻す
- DOCS で仕様矛盾 → REVIEW に戻す
- **仕様不備が判明 → PLAN に戻す。** main が SPEC.md / TEST.md を修正 → 再度 REVIEW → build-red 直前に `bash harness/bin/sprint seal` で再封印。封印後の巻き戻しは封印ハッシュが変わるため、REVIEW 以降は再実施対象になる

### 状態の集約と遷移ログ

`bash harness/bin/sprint status` が散在する状態を 1 コマンドで表示する。情報源は `flags.json`（stage / status / kind / dir）・`spec-hashes.json`（封印）・`test-fails.json`（テスト失敗数。`{ "total": n, "tasks": { "<component>.<task>": n }, "recorded_at": "..." }` の形で、`harness/hooks/record-test-fails.sh` が `sprint run` の直後に証跡から書く）・`results` ゲートの fresh（証跡の鮮度）・`.sprint/logs/stage-transitions.jsonl`（直近の遷移）。**新しい状態ファイルは作らない。** README の「3. タスク・進捗」節のタスク表は引き続き唯一の情報源であり、ここに複製しない。

`bash harness/bin/sprint status --json` は同内容を JSON で返す（`/sprint resume` が使う）。`bash harness/bin/sprint list` が全スプリント一覧。

`sprint stage` は遷移を `stage-transitions.jsonl` に追記する（sprint / from / to / direction / gate）。`bash harness/bin/sprint log` が「どのステージで何回巻き戻したか」「どのゲートが何回落ちたか」を集計する。記録の失敗が `sprint` を止めることはない。

### BUILD サブフェーズ

| フェーズ | 許可エージェント | 目的 | 完了条件 |
|---------|---------------|------|---------|
| `build-red` | tester | テストスケルトン作成 | `make test` が FAIL |
| `BUILD` | backend, frontend, tester | 実装・テスト保守・skip 解除 | `make verify` が GREEN、`test.skip()` 残りなし |

`make verify` = `lint` → `typecheck` → `test` → `test-frontend` → `build` の fail-fast 連結（e2e は重いため含めない。TEST ステージで `make test-e2e`）。

**手順:**

1. main: `bash harness/bin/sprint seal` → `bash harness/bin/sprint stage build-red`
2. main: tester を起動 → TEST.md に基づきテストスケルトン作成 → `make test` で FAIL を確認
3. main: `bash harness/bin/sprint stage BUILD`
4. main: SPEC.md「実装単位と依存関係」に従ってエージェントを起動する。依存のない単位は並列、依存のある単位は依存先の完了を待つ（例: frontend の画面実装は、型定義を持つ backend の単位に依存する）
5. main: 合流点。全単位の完了後に `make verify` で GREEN 確認 → TEST へ遷移

**同じテストランナーを使う単位は並列にしない。** 同じ `(component, task)` の実行は同じ実行証跡（`<evidence.dir>/<component>.<task>.json`）へ書く。同じランナーを使うエージェントを 2 体同時に走らせると、後から書いた側が先の証跡を上書きし、`results` / `tdd-audit` が読む内容が壊れる。

| 組み合わせ | 並列 |
|-----------|------|
| backend × frontend | 可（証跡が分かれる） |
| backend × backend / frontend × frontend | **不可**。担当ファイルが重ならなくても直列にする |
| tester × 任意 | tester が検証で走らせるランナーを見て判断する |

**自己修正ループ:** 各エージェントは `make verify` が green になるまで、自分がそのスプリントで書いた・変更したコードに起因する失敗を自分で修正する（**上限 3 回**）。3 回で green にならなければ停止し、原因の分析と試した修正を main に報告する。**既存機能のバグを発見した場合は自己修正しない。** 報告して指示を待つ。テストの削除・skip・条件緩和による green 化は禁止（`tdd-audit` が実行証跡で検出する）。tester は build-red では FAIL が正しい状態なので自己修正しない。

### REVIEW 作業内容

REVIEW ステージは SPEC / TEST / README の独立監査を行う。評価項目（R1〜R10）は `.claude/agents/qa.md` に記載。qa は未封印の草案を読むだけで編集しない（所見は README の「4. REVIEW」節）。

**qa は毎ラウンド次の 3 つを数えて README の「4. REVIEW」節に記録する。** 3 者が一致しないラウンドは、不一致を 🟡 以上で報告する。

| 数えるもの | 取り方 |
|-----------|-------|
| MUST 件数 | SPEC の MUST 要件（タスク ID）の全数 |
| タスク行が受ける件数 | README の「3. タスク・進捗」節のタスク一覧の各行が挙げるタスク IDの合計 |
| EARS 件数 | SPEC の EARS 要件の全数 |

REVIEW で指摘を反映するたびに `bash harness/bin/sprint spec-check` を実行し、封印前に OK にする（§4）。

### DOCS 作業内容

DOCS ステージはベース仕様書への実装結果の反映を行う。評価項目（D1〜D4）は `.claude/agents/qa.md` に記載。反映の際は以下を守る。

- 図・例示に使う値（`command` / シナリオ ID / ビュー ID 等のドメイン識別子）は、カタログの実値と grep で照合する。照合していない値を書かない
- EARS 要件の語彙は、Interface Contracts のフィールド名にそろえる

**条項の宣言と実績を件数で突合する。** qa が `bash harness/bin/sprint spec-graph diff <スプリント開始 commit>` を実行し、changed の条項一覧と SPEC の「0. 参照する共通条項」節・ベース仕様参照表が宣言した条項を件数で照合する。差は宣言外の変更である。条項 ID と変更内容を README の「7. DOCS」節「参照条項の突合」に記録する。

**検査を新設するスプリントは、PLAN で本番文書に対して検査を試走し、検出件数を SPEC の「ベース仕様参照」に宣言する。** 試走できない（検査が未実装）なら「検出した誤りは是正し、条項を README の「7. DOCS」節に記録する」と宣言する。新設した検査が BUILD で本番文書の誤りを検出すると、その是正は宣言外の条項変更になる。

**DOCS の最後に本体を commit する。** 実装・テスト・ベース仕様・SPEC/TEST/README（「7. DOCS」節まで）を 1 コミットにまとめる。commit したハッシュを README の「8. SHIP」節「コミットハッシュ」に記録する。

- **SHIP で本体を commit しない。** SHIP のコミット（§6 RETRO と §8 の記録分）は README に記録しない。記録すると、その記録のためにまた commit が要り、終わらない
- **`git commit --amend` で 1 コミットにまとめない。** amend は新しいコミットオブジェクトを作り、ハッシュが変わる。記録した値が別のコミットを指す

### SHIP 作業内容

1. main: qa を起動 → 実装コードの品質検証（評価項目 S1〜S6 は `qa.md`）
2. qa: REVIEW で「別 issue として起票する」と書いた観察を `gh issue list` と突合する。未起票をユーザーに報告する
3. main: README の「6. RETRO」節を記入。恒久化する規則は §6「恒久化の手順」に従う
4. main: README の「8. SHIP」節のチェックリストを確認。「コミットハッシュ」には DOCS の本体コミットが記録済みである（SHIP で書き足さない）
5. main: git commit（RETRO と SHIP での修正分）→ ブランチ push。このコミットのハッシュは README に記録しない

**SHIP 判定ルール:**

| 結果 | main の対応 |
|------|-----------|
| 🟢 全 green + qa 🟢 | commit + push |
| 🟡 qa 指摘あり | main が修正して続行 |
| 🔴 いずれか fail / qa 🔴 | **即停止。** 原因を分析してユーザーに報告する。修正はユーザーの指示後に BUILD に戻して行う。ワークアラウンドで突破しない |

### qa の評価対象

qa は 4 ステージで起動される。各ステージで評価対象が異なる。他ステージの対象に踏み込まない。

| ステージ | 見る | 見ない |
|---------|------|--------|
| REVIEW | SPEC / TEST / README の「1. 背景・目的」〜「3. タスク・進捗」節の記述内容 | 実装コード |
| TEST | テスト実行結果 + テストコード + 成果物 | 実装コードの品質 |
| DOCS | 実装結果とベース仕様書の差分 | — |
| SHIP | 実装コード | テストコード（TEST で済み）、仕様書（DOCS で済み） |

**qa の評価対象は SPEC の契約と成果物である。README の「4. REVIEW」〜「8. SHIP」節は記録であり、評価しない。** 記録の記述を監査対象にすると、是正の記録が次の巡の指摘になり収束しない。記録の正確さは main が担う。

**qa への起動プロンプトは 40 行以内に書く。** 評価項目は `qa.md` にあるので、プロンプトには対象ファイル・ステージ・スプリント固有の観点だけを書く。

**共通判定ルール:**

| 重大度 | 意味 | main の対応 |
|-------|------|-----------|
| 🟢 | 問題なし | そのまま進行 |
| 🟡 | 軽微な欠落 | main が修正して続行（ユーザー確認不要） |
| 🔴 | 重大な矛盾・方針判断が必要 | 停止してユーザーに確認を求める |

ステージ遷移の条件: 🔴 = 0（🟡 は修正済みであること）。🔴 は SHIP を停止できる。SHIP を許可する判断は人間が行う。

---

## 4. エージェント起動制御

### agent-gate.sh フック

`PreToolUse` フックで Agent ツールの呼び出しを監視し、現在のステージに応じてエージェントの起動を許可／拒否する。

| エージェント | PLAN | REVIEW | build-red | BUILD | TEST | DOCS | SHIP | CLOSED |
|------------|------|--------|-----------|-------|------|------|------|--------|
| frontend   | -    | -      | -         | ✓     | -    | -    | -    | ✓      |
| backend    | -    | -      | -         | ✓     | -    | -    | -    | ✓      |
| tester     | -    | -      | ✓         | ✓     | ✓    | -    | -    | ✓      |
| qa         | -    | ✓      | -         | -     | ✓    | ✓    | ✓    | ✓      |

情報収集用エージェント（Explore, Plan, general-purpose 等）はステージに関係なく常に許可。

**🚧 ゲートの再実行を機械的に禁じる。** `stage=REVIEW` かつ `status=closed`、および `stage=TEST` かつ `status=closed` では、上表で ✓ のエージェントも起動できない。どちらも「作業が完了し、ユーザーの指示を待つのが正しい状態」だからである。この強制が無いと、`/clear` 後の `/sprint resume` で完了済みの REVIEW / TEST がもう一度走る。指摘を反映する必要があるときは `bash harness/bin/sprint stage PLAN`（TEST なら `stage BUILD`）で巻き戻してから作業する。

### spec-check — 封印前の構造検査

`bash harness/bin/sprint spec-check [sprint_dir]`（既定は active スプリント）。SPEC.md / TEST.md の構造を機械検査する。

| # | 検査 | 検出する事故 |
|---|------|------------|
| 1 | EARS ↔ 網羅性マトリクスの双方向差分 | 要件を足してマトリクスに書き忘れる |
| 2 | 全 EARS の実装単位への帰属（範囲指定を展開）・二重帰属 | 新設 EARS が誰の担当でもない／範囲指定が隣の単位を巻き込む |
| 3 | Test ID の定義 ↔ 参照の差分・欠番 | テストを足してマトリクスに載せ忘れる |
| 4 | 空行による markdown 表の分断 | 表の外に行が落ち、レンダリングされない |
| 5 | 参照テストファイルの実在 | 存在しないパスを指定する |

Test ID を持たない TEST.md（kind=docs。静的検証項目だけ）では検査 3・4 を省略し、検査 5 へ進む。

**実装単位表には「担当 EARS」列を置く。** 検査 2 はこの列を読む。

---

<a id="PROC-1"></a>
## [PROC-1] 5. ファイル書き込み制約

### 書き込み範囲の行列（正本）

呼び出し元（`agent_type`。欠落と情報収集系は main）と書き込み先の種別の組み合わせで判定する。種別は `sprint.config.json` の配置（`docs.sprintRoot`・`components[*].src`・`components[*].tests`）から決まり、行列のコードは `harness/hooks/scope-lib.sh` の 1 箇所にある。Write / Edit を `harness/hooks/edit-scope-gate.sh` が事前に判定する。Bash の書き込みは判定しない。src / テストは Edit / Write で書く（CLAUDE.md「ツールの選び方」）。

種別の判定順: `state` → `spec` / `testmd` → その他（`docs/**`）→ `test`（いずれかのコンポーネントの `tests` に一致）→ コンポーネントの src（いずれかの `src` に一致。コンポーネント名）→ その他。

| 呼び出し元 | コンポーネントの src | テスト（`components[*].tests`） | SPEC.md | TEST.md | `flags.json` / `spec-hashes.json` | その他（docs・scripts・設定） |
|---|---|---|---|---|---|---|
| main | deny | deny | allow | allow | deny | allow |
| コンポーネントの `role`（backend / frontend） | **`role` が一致する呼び出し元だけ allow** | deny | deny | deny | deny | allow |
| tester | deny | allow | deny | deny | deny | allow |
| qa | deny | deny | deny | **UNSEAL のみ** | deny | allow |

- コンポーネントの src は「`role` が一致する呼び出し元だけ allow」。backend コンポーネント（`role: backend`）の src は backend エージェントだけが書け、frontend コンポーネントの src は frontend エージェントだけが書ける。role が一致しない呼び出し元（main を含む）は deny
- SPEC.md / TEST.md は `<docs.sprintRoot>/**/` 配下のスプリント仕様。`docs/` 配下の他のファイルはテストの glob に一致しても「その他」
- **UNSEAL のみ** = `<!-- UNSEAL:BEGIN/END -->` ブロック内だけ。`edit-scope-gate.sh` が Edit の引数で領域を判定する
- `flags.json` は `harness/bin/sprint`、`spec-hashes.json` は `bash harness/bin/sprint seal` だけが書く
- `sprint.config.json` が無いとき hooks は判定せず素通りする（出力なし・exit 0）

<a id="PROC-2"></a>
### [PROC-2] 5.1 仕様封印（spec seal）

`SPEC.md` / `TEST.md` は仕様アーティファクトであり、**起草者（main）と評価者（qa）を分離**するためハッシュ封印する。狙いは「測定基準を、測定する側（qa）が書き換えられない」状態の担保（自己評価の防止）。

- **封印領域** = ファイル全体 − `<!-- UNSEAL:BEGIN -->` … `<!-- UNSEAL:END -->` ブロック。マーカーが無いファイルは全体が封印領域
- **TEST.md** の UNSEAL ブロック（「実行結果（qa 記入欄）」）だけが qa の可変領域。テスト仕様・網羅性マトリクスは封印領域
- **SPEC.md** は全体封印。qa は読み取り専用、main のみ書き換え可
- 封印ハッシュは `.sprint/spec-hashes.json` に集約。更新は `bash harness/bin/sprint seal` のみ（main による承認行為）
- `edit-scope-gate.sh` が編集時に封印領域への変更を deny（予防）。`bash harness/bin/sprint seal-verify` が manifest との不一致を検出（保証・SHIP ゲート）

**封印タイミングは REVIEW 完了後・build-red 直前。** PLAN〜REVIEW で仕様を固め、封印が締め。封印の主目的は BUILD 以降の凍結であり、build-red より前であれば足りる。REVIEW では qa は SPEC/TEST を読むだけで編集しないため、REVIEW 中に未封印でも自己評価防止は崩れない。REVIEW で仕様不備が出ても「巻き戻し→再封印」のループが不要になる。`build-red` ゲートの `spec-seal` チェックが封印を強制する。

**運用フロー:**

1. main が PLAN で SPEC.md / TEST.md を起草（封印しない）
2. REVIEW: qa が SPEC/TEST を入力として独立監査（読むだけ。所見は README の「4. REVIEW」節）
3. main が REVIEW 指摘を反映 → REVIEW 完了後・build-red 直前に `bash harness/bin/sprint seal` で封印
4. 封印後の仕様変更は PLAN に巻き戻し → 編集 → 再 REVIEW → build-red 前に再 `bash harness/bin/sprint seal`
5. SHIP で `bash harness/bin/sprint seal-verify` を実行。不一致（封印領域の無断改変・未封印ファイル）は 🔴

**過去スプリントの不改変（CLOSED 後の凍結）:** CLOSED 後のスプリントの SPEC.md / TEST.md は改変しない。設計変更が必要になった場合は、ベース仕様（docs/03_design 等）+ 現行スプリントの SPEC + ADR（docs/08_decisions）で表現する。`bash harness/bin/sprint seal` は docs/07_plans 配下の全 SPEC/TEST を一括再ハッシュするため、過去ファイルの改変は機械的には検出されない。凍結は本運用規約で守る。

---

## 6. スプリントドキュメント

### 構成

`docs/07_plans/<major>_<slug>/<minor>_<slug>/` に README.md / SPEC.md / TEST.md の 3 ファイルを置く。書き方は `docs/07_plans/README.md`。テンプレートは `docs/06_process/templates/`。

| ファイル | 主参照者 | 内容 |
|---------|---------|------|
| README.md | main, qa | 背景・スコープ・進捗・REVIEW・TEST・RETRO・DOCS・SHIP |
| SPEC.md | backend, frontend | EARS 要件・Interface Contracts・状態遷移 |
| TEST.md | tester, qa | テスト仕様・網羅性マトリクス・実行手順 |

### SPEC.md の書き方 — 要件は結果で書く

**実装手段を要件に書かない。** 要件は「何が成り立つか」で書く。「どう実現するか」は実装が選ぶ。

| 悪い書き方 | 何が起きるか | 直した書き方 |
|-----------|------------|------------|
| 入力中カードを**時刻を持たない要素**として先頭に置く | 「時刻を持たない」がデータの性質か表示かを読めない。「先頭」の基準も定まらない | 投入したカードは**最新が先頭**になる |
| 検索カードは**開いた時刻**を並びのキーに使う | 時刻を要件にすると、タイムゾーン・時計のずれ・同一ミリ秒の衝突という要件に無い問題を実装が抱え込む | 投入の順序は**単調増加の値**で表す |

曖昧な要件は、実装が仕様どおりでも利用者の期待を外す。判定に使う語を選ぶときは次を守る。

- 観測できる結果で書く（画面の並び・応答のフィールド・件数）
- 実装の内部状態を要件にしない（変数名・データ型・アルゴリズム）
- 要件が守るべき制約は別の要件に分ける

**是正スプリントの完了判定は出口の実測で書く。** 既存実装の違反を直すスプリントでは、完了判定を是正対象の列挙から独立させる。判定は出口の全数走査（実応答・実行結果を機械で走査し、違反 0 件を確認する）で書く。

- 列挙は作業の手引きとして書いてよい。判定根拠にしない
- 列挙の正しさを REVIEW の反復で追い込まない。漏れを止めるのは走査である
- 源で直す方針でも、源を経由しない経路には是正が届かない。出口の走査だけが両方を覆う
- 走査の対象集合も人が数えない。機械の出力から導く

### RETRO と恒久化の手順

README.md の「6. RETRO」節は最重要セクション。各スプリントで以下を記録する。

- **うまくいったこと**: 再現したい判断・手法
- **問題点**: 予想外の障害・手戻り・仕様の曖昧さ
- **改善策**: 恒久化する規則の本文と、置き場所の候補
- **パターン抽出**: 仕様・実装・プロセスで再利用可能なパターン

**恒久化の手順:**

1. RETRO に規則の**本文**を書く。「〜を検討する」ではなく、恒久文書にそのまま置ける文で書く
2. このスプリント中に恒久文書（ベース仕様・標準・プロセス）へ書く。RETRO 側には反映先を残す（テンプレート README の「6. RETRO」節）
3. 恒久文書に**スプリント ID のタグ**（「18-N で恒久化」）を付けない。規則は出自ではなく内容で置く

恒久化できないもの（未解決の課題・後回しにした作業）は **issue に登録する**。issue の登録はユーザーが指示する。スプリント文書に書いて次スプリントへ送る機構は持たない。`.sprint/` は git 管理外であり、環境を作り直すと消えるためである。

---

## 7. ドキュメントスプリント（kind=docs）

会計原則リファレンス・設計文書など、コードを書かず文書のみを作成するスプリント。コードスプリント用のゲート（tdd-exists・*-audit・results-*）は文書に適さないため、kind 別のゲートセットを用いる（`sprint.config.json` の `gates.docs`）。

### 7.1 kind フィールド

- `flags.json` の `sprints[id].kind`（`code` | `docs`、未設定は `code`）
- 設定: `sprint new <id> <dir> docs`（新規）または `sprint set-kind docs`（既存スプリント）

### 7.2 ステージの意味（docs 版）

| ステージ | 作業 | 担当 |
|---------|------|------|
| PLAN | 章立て・採用方針・参照資料の確定（README/SPEC/TEST 起草） | main |
| REVIEW | 章立て・方針の正しさ・カバレッジ計画の独立監査 | qa |
| 🚧 | 方針の承認（重大な方針判断） | ユーザー |
| build-red | 封印（spec-seal）。検証チェックリスト（TEST.md DOC-x）が未充足を確認 | main |
| BUILD | 成果物文書の執筆 | **main** |
| TEST | ドキュメント整合性チェック（grep・貸借検算等）・TEST.md UNSEAL と README の「5. TEST」節の記入 | **qa** |
| 🚧 | 完成文書の通読・承認 | ユーザー |
| DOCS | 被参照側への波及の反映・本体 commit | main |
| SHIP | リンク検証・commit・ブランチ push | main |

**TEST で指摘が出て是正したら、是正後にもう 1 巡測って UNSEAL を更新する。** 是正は新しい記述であり、書いた瞬間から検証の対象になる。UNSEAL の最終記入が是正前の判定を指したまま次のステージへ進まない。

### 7.3 執筆と検証の分離

qa は Write 権限を持たない（新規文書を作れない）。自己評価防止のため、**執筆 = main、検証 = qa** とする。TEST の判定は機械的検証（grep・貸借検算）に基づき、qa が TEST.md UNSEAL と README の「5. TEST」節に記録する。テスト ID は docs では `DOC-x.x` 形式（コードの `TEST-x.x` と区別）。

### 7.4 参照の実在確認は形状・行番号・件数まで照合する

**存在確認だけで 🟢 としない。** REVIEW で最も多い差し戻し原因は「実在は確認したが、中身を照合していなかった」型である。

| 書くもの | 確認すること |
|---------|------------|
| スキーマ名・型名 | その型が実応答の形状と一致するか。同名でも用途が違えば形状は違う |
| `file:line` | 引用レンジに言及した要素が入っているか。行番号は実装で動く |
| 件数（「N 件」「N 本」「最初である」） | 全数走査で数える。列挙リストを数え合わせただけで済ませない |

件数を根拠にする検証項目は、TEST.md に走査の手順と対象外を書く。識別子の実在突合は [TSTD-2](../04_standards/02_testing.md#TSTD-2)。
