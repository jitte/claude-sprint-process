---
name: sprint
description: スプリント管理。/sprint resume でコンテキスト復元、/sprint handover で clear 前の引き継ぎ準備、/sprint to <stage> で目標まで一括実行、/sprint status で状態確認、/sprint new で新規作成、/sprint stage で単発遷移。「スプリント」「再開」「resume」「status」「flag」で起動する。**ユーザーが会話の破棄を口にしたら handover で起動する** —「clear していい？」「リセットする」「コンテキストを消す」「/clear する」「session clear」「一旦切る」「ここまでで区切る」など。
---

# Sprint Manager

`.sprint/flags.json` を読み書きしてスプリントのライフサイクルを管理するスキル。
`/clear` 後にコンテキストを復元する主要手段。

ステージの定義・遷移規則・各ステージの作業内容・🚧 ゲートは `docs/06_process/sprint-process.md` が正本である。本スキルはコマンドの構文と、`resume` / `handover` の手順だけを持つ。

## コマンド

引数で動作を分岐する。引数なしは `status` と同じ。

### 短縮形

**コマンド名は先頭一致で受け付ける。** 一意に定まる最短形は次である。

| 短縮形 | コマンド |
|---|---|
| `r` | `resume` |
| `ho` | `handover` |
| `he` | `help` |
| `n` | `new` |
| `sw` | `switch` |
| `t` | `to` |
| `stat` | `status` |
| `stag` | `stage` |

上表より長い先頭一致も同じコマンドとして扱う（`res` → `resume`、`hand` → `handover`）。

**一意に定まらない短縮形は実行しない。** `h`（handover / help）・`s`・`st`・`sta`（status / stage / switch）は候補を示して聞き返す。勝手にどちらかを選ばない。

`to` は省略できる（`/sprint REVIEW` = `/sprint to REVIEW`）。ステージ名も先頭一致で受け付ける（`/sprint b` は build-red / BUILD が一意に定まらないため聞き返す）。

### `resume` — コンテキスト復元

`/clear` 後の再開用。以下を順に実行する:

1. **`bash harness/bin/sprint status --json` を実行**して active スプリントの状態を一括取得する
2. `sprint_dir` から README.md / SPEC.md / TEST.md を読む（SPEC.md は全文。エージェントへの指示の土台になる）
3. CLAUDE.md を読む
4. 現在のステージ**と status** を踏まえた次のアクションをユーザーに提示する

出力フォーマット:
```
## Sprint: {sprint_id}
- Stage: {stage} ({status})
- Dir: {sprint_dir}
- 封印: SPEC {✓/✗} / TEST {✓/✗}  テスト失敗: {n} 件  証跡: {fresh/stale}

### スコープ
（README.md §2 から MUST タスクを列挙）

### 現在の状態
（README.md §3 のタスク進捗を表示）

### 次のアクション
```

**推奨アクションは `stage` だけでなく `status` も見て決める。**

| status | 意味 | 次のアクション |
|---|---|---|
| `open` / `doing` | そのステージの作業が未完了 | そのステージの作業を実行・継続する（内容は `sprint-process.md` §3） |
| `closed`（REVIEW / TEST） | 🚧 ゲート。作業完了済み | **停止してユーザー指示を待つ。** 同じステージを再実行しない（`agent-gate.sh` が機械的に拒否する） |
| `closed`（その他） | 作業完了済み | 次ステージへ遷移する |
| `CLOSED` + `closed` | スプリント完了 | 次スプリントへ（`switch` / `new`） |

### `handover` — clear 前の引き継ぎ準備

`resume` の対。**セッションを破棄しても作業が続く状態を実際に作ってから**報告する。

ユーザーが会話の破棄を口にしたら起動する（「clear していい？」「リセットする」「一旦切る」「ここまでで区切る」など）。

失敗の型は決まっている。**準備できていないのに「復帰できます」と断言する**ことである。実例: ディスクに文書があることだけを確認して「復帰できます」と答えたが、作業ブランチが未作成で `main` にいた。

守ることは 3 つ。

1. **点検が全部通るまで「復帰できます」と書かない**
2. **直せるものは聞かずに直す。** ブランチを切る、status を実態に合わせる。可逆で範囲内の操作は報告して終わらせない
3. **決まった表で返す。** 散文にしない

#### 点検項目

| # | 項目 | 判断 |
|---|------|------|
| 1 | 実行中の処理 | バックグラウンドのコマンド・エージェントが残っていれば **clear 不可**。結果を受け取れなくなる |
| 2 | 作業ブランチ | スプリント中に `main` などの共有ブランチにいたら**切る** |
| 3 | **会話にしかない情報** | **最重要。** 消えるのは会話であってディスクではない |
| 4 | 状態ファイル | `bash harness/bin/sprint status` で stage / status が実態と合っているか |
| 5 | 未コミット差分 | 内容を**報告する**。**コミットはしない**（ユーザーが内容を確認してから決める） |
| 6 | 再開手段 | 1 行で示す。示せないなら準備が足りていない |

**項目 3 が中心。** 本当に失われるのは、調査で分かった事実（行数・件数・原因の切り分け結果）、ユーザーと口頭で合意した設計判断、「あとでやる」と言った項目である。落とす先（SPEC / README / issue / コミットメッセージ）が無いなら、落としてから clear する。

#### 出力

この表だけを返す。前置きも締めの言葉も書かない。

```
| 項目 | 状態 |
|------|------|
| 実行中の処理 | なし |
| ブランチ | sprint/17-6 |
| 会話にしかない情報 | なし |
| 状態ファイル | 17-6 / REVIEW / doing |
| 未コミット差分 | 3 ファイル（sprint 文書） |

clear して問題ない。再開: `/sprint resume`
```

直した項目があれば表の下に 1 行で書く。clear できない項目があれば、それだけを書く。

### `status` — 状態表示

**`bash harness/bin/sprint status` を実行する。** active スプリントの状態（stage / status / kind / dir / 封印 / テスト失敗数 / 証跡の鮮度 / 直近の遷移）を集約表示する。

- 全スプリントの一覧: `bash harness/bin/sprint list`
- ステージ遷移の集計: `bash harness/bin/sprint log`
- JSON 形式: `bash harness/bin/sprint status --json`

### `stage <STAGE>` — ステージ遷移（単発）

**`bash harness/bin/sprint stage <STAGE>` を実行する。** flags.json を更新するだけで、ステージの作業は実行しない。直接編集は edit-scope-gate が deny する。

有効なステージ: `PLAN` / `REVIEW` / `build-red` / `BUILD` / `TEST` / `DOCS` / `SHIP` / `CLOSED`

遷移規則（前進は次の許可遷移のみ・後退は常に許可・skip は拒否）とゲートは `sprint-process.md` §3。skip を試みると非ゼロ終了するので、その旨をユーザーに報告する。

#### `stage <STAGE> to <STAGE>` — 巻き戻してから走らせる

**第 1 引数のステージへ遷移してから、第 2 引数のステージまで一括実行する。** 用途は巻き戻しである（封印後の仕様不備・SHIP 後の SPEC 記述誤り）。

```
/sprint stage PLAN to TEST     PLAN へ巻き戻し、そこから TEST まで走らせる
/sprint stage DOCS to SHIP     DOCS へ巻き戻し、DOCS → SHIP を回す
```

**🚧 ゲート（REVIEW 後・TEST 後）は通常どおり効く。** 巻き戻しの指示はゲート通過の指示ではない。第 2 引数がゲートの先にある場合でも、ゲートに達したら停止して指示を待つ。

### `[to] <STAGE>` — 目標ステージまで一括実行

現在のステージから目標ステージまで、**未実施のステージを順番に実行**する。各ステージの作業を main が自律的に進め、ステージ遷移も自動で行う。作業内容は `sprint-process.md` §3（REVIEW / BUILD サブフェーズ / DOCS / SHIP の各作業内容）に従う。

**目標ステージに到達したら結果を報告して停止する。後続ステージには絶対に進まない。**

ステージ順序: `PLAN → REVIEW → 🚧 → build-red → BUILD → TEST → 🚧 → DOCS → SHIP → CLOSED`

- 🚧 は Human-in-the-Loop ゲート。ユーザーの指示がなければ通過不可。`/sprint to BUILD` で REVIEW を通過する場合、REVIEW の結果を報告して停止する
- 封印（`bash harness/bin/sprint seal`）は REVIEW 完了後・build-red 直前に行う
- 途中で 🔴 が出た場合やテスト失敗が解消できない場合は停止してユーザーに確認する

### `new <sprint_id> <名前 | sprint_dir>` — 新規スプリント

**第 2 引数は正式なパスでなくてよい。** 名前/説明を渡されたら main が規約どおりの `sprint_dir` に変換する。

- 第 2 引数が `docs/07_plans/...` 形式の正式パスなら、そのまま使う
- そうでなければ名前とみなし、次で導出する:
  1. `sprint_id`（例 `10-2`）の major に対応する **major ディレクトリ**を特定（`ls docs/07_plans/10_*`）。無ければ新しい major の slug を決める
  2. major ディレクトリ内の**次の連番**（既存 `NN_*` の最大 +1・ゼロ詰め 2 桁）
  3. 名前を**英小文字 kebab スラッグ**に変換（例 `sankey/mosaic後編` → `sankey-mosaic-2`）
  4. `docs/07_plans/<major>_<slug>/<NN>_<slug>` を `sprint_dir` とする
- 導出した `sprint_dir` は提示してから実行する。パスの可否は聞かない。sprint の中身・スコープの確定は別途対話で合意する
- **既存 ID は `sprint.sh new` が弾く。** その場合は既存の扱い（再定義 / 別番号で新規）をユーザーに確認する

**`bash harness/bin/sprint new <sprint_id> <sprint_dir> [docs]` を実行する。** テンプレートから README/SPEC/TEST を作り、flags.json に追加し、active を切り替える。SPEC.md / TEST.md はこの時点では封印しない。

### `switch <sprint_id>` — active 切替

**`bash harness/bin/sprint switch <sprint_id>` を実行する。**

### `help` — ヘルプ

このスキルのコマンド一覧を表示する。

## 実装ノート

- **flags.json の読み取りは Read ツール、書き込みは `harness/bin/sprint` 経由**
  - stage 遷移: `bash harness/bin/sprint stage <STAGE>`
  - status 更新: `bash harness/bin/sprint set-status <open|doing|closed>`
  - 新規/切替: `bash harness/bin/sprint new|switch ...`
  - 値取得: `bash harness/bin/sprint get [field]`
  - 状態集約: `bash harness/bin/sprint status [--json]`
- sprint_dir はプロジェクトルートからの相対パス
- `updated_at`（ISO 8601 JST）はスクリプトが自動更新する

### status のライフサイクル

| status | 意味 | 遷移タイミング |
|--------|------|-------------|
| `open` | ステージ開始前 | `stage` で新ステージに遷移した時 |
| `doing` | ステージ作業中 | `to` でステージの作業を開始した時（`set-status doing`） |
| `closed` | ステージ完了 | 作業完了時（`set-status closed`）。次の `stage` で `open` に戻る |
