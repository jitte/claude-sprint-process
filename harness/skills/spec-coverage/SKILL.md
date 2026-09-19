---
name: spec-coverage
description: ベース仕様（docs.livingDirs の条項を持つ md）の条項参照カバレッジをファイル単位で出す。cov（条項化率。行と見出しの 2 通り）、rcov（被参照率 = 参照される条項の行の割合）、tcov（テスト被参照率 = テストの名前から参照される docs.specDir の条項の割合）、指定 sprint の SPEC.md を考慮した rcov+（既定は active sprint）、単独率（規範・共通層をひとつも参照しない末端の仕様の割合。docs.normativeDirs / docs.commonFiles があるときだけ）。「仕様カバレッジ」「cov」「rcov」「被参照率」「参照されていない条項」「孤立条項」「どの条項が使われていないか」「この sprint はベース仕様のどこを参照しているか」「テストがない条項はどれか」「tcov」と言われたら使う。テストのコードカバレッジ（lcov）は本スキルではない。
---

# 仕様カバレッジ（cov / rcov / tcov）

`bash harness/bin/sprint spec-coverage` を **1 回だけ**実行する。引数は下表で選ぶ。複数を試さない。

```bash
bash harness/bin/sprint spec-coverage [引数]
```

| ユーザーの言い方 | 付ける引数 |
|---|---|
| 「仕様カバレッジ」「cov と rcov」「今の sprint は」など、sprint の指定なし | なし（active sprint を rcov+ に反映する） |
| 「1-3 の」「sprint 1-3 を考慮して」 | `--sprint 1-3` |
| SPEC.md のパスを渡された | `--spec <path>` |
| 「ベース仕様だけ」「sprint は関係なく」 | `--no-sprint` |
| 「参照されていない条項はどれ」「孤立条項の一覧」 | `--unreferenced`（sprint の引数と併用できる） |
| 「テストがない条項はどれ」「テストから参照されていない条項」 | `--untested`（docs.specDir の条項のうちテストの名前から参照されない ID を文書別に出す） |
| 「JSON で」「機械で処理したい」 | `--json` |

出力（ファイル別の表と全体、末尾の注記）をそのまま画面に出す。数字を丸めない。行を省かない。

| 指標 | 定義 |
|---|---|
| cov(行) | 条項の範囲に入る行の割合（非空行。frontmatter を除く）。条項の外にある説明文が多いほど低い |
| cov(見出し) | 条項 ID を持つ見出しの割合（`##`〜`####`。コードフェンス外） |
| rcov(行) | 生きている文書（docs.sprintRoot 以外）から参照される条項の行の割合 |
| rcov+(行) | sprint の SPEC.md 全体の参照を入る辺に加えた rcov |
| tcov | docs.specDir の各文書について、テストファイル（テストの名前の `[[ID]]`）から参照される条項の数 / 条項数。specDir 以外の文書は `—`。rcov / rcov+ / 単独はテストの参照を数えない |
| 単独 | 規範・共通層（docs.normativeDirs と docs.commonFiles）をひとつも参照しない条項の割合。対象は specDir の末端の仕様だけ。設定が無いときは全行 `—` |

評価指標であり fail させない。指標の定義とコマンドは `docs/06_process/spec-metrics.md` に書く。値からリファクタリングの対象を選ぶ見方は `docs/04_standards/03_spec-structure.md` に書く。
