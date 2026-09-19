# 仕様指標の測定

仕様の条項がどれだけ構造化・参照・テストされているかを測る。

## 1. 指標

| 値 | 意味 | 低いときの作業 |
|---|---|---|
| cov（条項化率） | 条項の外にある行の割合。条項化されていない規範か説明文かを判断する | docs sprint。条項にするか消す |
| rcov（被参照率） | 参照されない条項の割合 | docs sprint。条項を消すか参照元を書く（`--unreferenced` で ID を出す） |
| tcov（テスト被参照率） | テストの名前から参照されない条項の割合 | code sprint。テストの名前に `[[ID]]` を付けるか、テストを書く（`--untested` で ID を出す） |

- **値に閾値を置かない。** 値は対象を選ぶための材料であり、合否ではない
- **sprint の途中で測らない。** 途中の値に対する行動が無い

## 2. コマンド

```bash
bash harness/bin/sprint spec-coverage               # 全指標
bash harness/bin/sprint spec-coverage --no-sprint    # active sprint を除外して測定
bash harness/bin/sprint spec-coverage --unreferenced # 被参照 0 の条項を列挙
bash harness/bin/sprint spec-coverage --untested     # テスト未参照の条項を列挙
```

## 3. 値の記録

測定はユーザーの指示で行う。値の記録先と、値を見て何をするかはユーザーが決める。
