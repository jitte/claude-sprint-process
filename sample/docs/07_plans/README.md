# スプリントの計画と記録

## 1. 単位と名前

進行の単位は sprint だけである。phase・wave・step・milestone という語を使わない。

- ID は `<major>-<minor>`。major は連続する sprint のまとまり、minor はその中の順番。どちらも 1 から振る
- 記録の置き場は `<docs.sprintRoot>/<major 2 桁>_<slug>/<minor 2 桁>_<slug>/`。README.md・SPEC.md・TEST.md を置く。作るのは `bash harness/bin/sprint new <major>-<minor> <dir>`
- major ごとの計画は `<docs.sprintRoot>/<major 2 桁>_<slug>/README.md` に書く

## 2. 計画の書き方

計画は sprint の並びで書く。初期開発計画は sprint 1-1 から 1-N である。1 行に ID・kind・目的を書く。

| sprint | kind | 目的 |
|---|---|---|
| 1-1 | docs | 01_overview・02_requirements を書く |
| 1-2 | docs | 03_design・04_standards を書く |
| 1-3 | code | 最初のコンポーネントと lint / typecheck / build / test の証跡 |

kind は docs か code。docs の sprint はコードのゲート（results・tdd-*・impl-sync・size-audit）を通らない。定義は `docs/06_process/sprint-process.md`。

## 3. 導入の局面

取り込む時点のプロジェクトの状態で、最初の sprint と `sets` を定義する時期が決まる。

| 局面 | 最初の sprint | `sprint.config.json` の `sets` |
|---|---|---|
| コードが無い | 1-1 から kind=docs。01〜04 を書く | 最初の code の sprint で `components` を書く。`sets` はコードができてから |
| 既存コードが多く、条項が無い | 1-1 から kind=docs。05 を実装から書き起こす | 条項が実装の集合を覆ってから定義する。定義した時点で impl-sync が不一致を全て出す。それまで impl-sync は何も比較しない |
| 仕様も実装もある | 1-1 から kind=code | 取り込み時に定義する |

## 4. 測定と次の範囲

測るのは major の切り替わりである。sprint の途中で測らない。途中の値に対する行動が無い。

1. major の最後の sprint が CLOSED になったら `bash harness/bin/sprint spec-coverage --no-sprint` を実行する
2. 値を次の major の README.md の先頭に書く
3. 値を見て次の major の sprint の並びを決める

見る値は 3 つ。fail の条件にしない。

| 値 | 低いときの sprint |
|---|---|
| cov（条項化率） | docs。条項の外にある説明文を条項にするか消す |
| rcov（被参照率） | docs。参照されない条項を消すか、参照元を書く（`--unreferenced` で ID を出す） |
| tcov（テスト被参照率） | code。テストの名前に `[[ID]]` を付けるか、テストを書く（`--untested` で ID を出す） |
