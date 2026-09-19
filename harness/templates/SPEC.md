# SPEC — Sprint [major]-[minor]

> 実装契約。backend / frontend エージェントの主参照。
> レビューは `README.md`、テスト設計は `TEST.md` を参照。
> **封印**: 本ファイルは全体が `bash harness/bin/sprint seal` でハッシュ封印される。main のみが
> 書き換え・再封印できる。backend / frontend / tester / qa は読み取り専用。

---

## 0. 参照する共通条項

本スプリントが従う共通条項を `[ID](<相対パス>#ID)` の形で列挙する。**内容を再記述しない。**
相対パスはこの SPEC.md（`<docs.sprintRoot>/<major>_<slug>/<minor>_<slug>/SPEC.md`）からの相対で書く。
条項の一覧は `bash harness/bin/sprint spec-graph files`、検証は `bash harness/bin/sprint spec-graph`。

**参照した条項ごとに、テストをどう扱うかを宣言する。** 扱いは 4 値（新規 / 改修 / 流用 / 不要）
のいずれかを書く。空欄は REVIEW ゲート（`spec-lint.sh` の refs）が fail する。判断の記録が目的であり、
テストの存在は強制しない。

| 参照する条項 | 適用理由 | テストの扱い | Test ID / 理由 |
|---|---|---|---|
{{common_clauses}}

- **新規**: 本スプリントで新しいテストを書く。Test ID は本スプリントのもの
- **改修**: 既存テストを変更する。削除も改修に含む。**既存テストが red になるなら改修である。** 判定条件を厳しくする変更（許容値の限定・必須化）は、PLAN で既存テストの fixture を走査し（`rg` で入力値の作り方を見る）、条件に合わない fixture を「改修」として宣言する
- **流用**: 既存テストが無変更で担保する。本スプリントでは触らない
- **不要**: テスト対象の振る舞いが変わらない。文脈参照・用語参照がこれにあたる。「実装を条項に従わせる」変更は振る舞いが変わるので「不要」ではなく「新規」である
- 旧スプリントの Test ID は非一意である。引用は `<sprint_id> TEST-x.x` の形で書く（例 `12-1 TEST-3.2`）
- 1 条項に複数の扱いが併存する場合は、同じ条項を複数行に分けて書く
- 参照が無いスプリントは `| （参照なし） | — | 不要 | 共通条項に依存しない |` の 1 行を書く


---

## ベース仕様参照

| ドメイン | ファイル | セクション | 差分種別 |
|---------|---------|----------|---------|
| — | `<docs.specDir>/*.md` | — | 追加 / 変更 / なし |

---

## 実装単位と依存関係

BUILD で**並列に進められる単位**を宣言する。`agent-gate.sh` は BUILD で
backend / frontend / tester の同時起動を許可しており、依存のない単位は同時に着手できる。

| 単位 | 担当 | 依存する単位 | 備考 |
|------|------|------------|------|
| — | backend / frontend / tester | なし | — |

- 「依存する単位 = なし」の単位は**並列に着手する**
- API の型・スキーマ（共有スキーマ）は FE 実装より先に確定させる必要があるため、
  FE の単位は該当スキーマを定義する BE の単位に依存する
- **合流点**（全単位の完了後に行う統合テスト・E2E 等）があれば備考に書く

---

## EARS 要件

### N-x.x — Normal Cases

- **N-1.1**: WHEN `<actor>` `<trigger>` THE system SHALL `<response>`

### E-x.x — Error Cases

- **E-1.1**: IF `<invalid condition>` THEN the system SHALL `<rejection behavior>`

---

## 状態遷移（必要に応じて）

| 開始状態 | トリガー | 終了状態 | 対応 EARS |
|---------|---------|---------|----------|
| — | — | — | N-x.x |

> 状態遷移がないスプリントではこのセクションを削除。

---

## 使用 API と型充足確認

スプリントで使用する全 API を列挙し、共有スキーマに対応する型が存在するか確認する。不足している場合はスキーマ定義を本 SPEC に記載し、build-green で backend エージェントが作成する。

<!-- UNSEAL:BEGIN -->

| API | 用途 | 共有スキーマの型 | 状態 |
|-----|------|-------------------|------|
| `GET /api/v1/xxx` | — | `XxxResponse` | ✅ 既存 / ⬜ 要作成 |

<!-- UNSEAL:END -->

> 「要作成」の型がある場合は、下の「スキーマ定義」セクションに全フィールドを記載すること。

### スキーマ定義（型が不足している場合）

```typescript
// 共有スキーマ xxx に追加
export const xxxSchema = z.object({
  // 全フィールドを記載
})
export type Xxx = z.infer<typeof xxxSchema>
```

> 全 API の型が既存の場合はこのセクションを削除。

---

## Interface Contracts（API を新規作成する場合のみ）

### `METHOD /api/v1/xxx`

**Request**:
```typescript
export const xxxSchema = z.object({
  // ...
})
```

**Response** (200):
```typescript
export type XxxResponse = {
  // ...
}
```

> API 新規作成がないスプリントではこのセクションを削除。
