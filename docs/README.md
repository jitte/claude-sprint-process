# 文書の構成

| ディレクトリ | 内容 |
|---|---|
| `01_overview` | プロジェクトの定義・目的・範囲 |
| `02_requirements` | 要件。EARS で書く |
| `03_design` | 設計。データ・アーキテクチャ・API 規約 |
| `04_standards` | コーディング・テスト・リファクタリングの規範 |
| `05_specifications` | モジュール仕様。条項の主な置き場 |
| `06_process` | スプリントプロセス・ゲート・`templates` |
| `07_plans` | スプリントの計画と記録。`<major>_<slug>/<minor>_<slug>/{README,SPEC,TEST}.md`。書き方は `07_plans/README.md` |
| `08_decisions` | 設計判断の記録。仕様本文は現在形だけを書き、判断の理由はここへ分ける |

条項を持つ文書は、frontmatter に `xref-prefix` を宣言した md である。フォルダは関係ない。`07_plans` は `livingDirs` に入れない。記録であり、検証の参照元にしないからである。

`sprint.config.json` の項目との対応:

- `docs.livingDirs` — 条項を持ちうる文書のディレクトリ一覧。`01_overview` 〜 `06_process` を基本とし、`08_decisions` はプロジェクトが条項を持たせるなら加える
- `docs.sprintRoot` — `07_plans`
- `docs.specDir` — `05_specifications`
- `docs.templates` — `06_process/templates`（または取り込み先が決めた配置）
- `docs.normativeDirs`・`docs.commonFiles` — 任意。spec-coverage の単独率が「規範・共通層」と見なすディレクトリとファイル。無ければ単独率を数えない

各ディレクトリは 1 ファイル以上を持つ。空ディレクトリは git に残らない。
