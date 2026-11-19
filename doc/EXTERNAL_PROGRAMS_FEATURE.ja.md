# 外部プログラム

[English](EXTERNAL_PROGRAMS_FEATURE.md) \| 日本語

## 概要

外部プログラム機能を使うと、自作の外部プログラムを XeFM から直接実行でき、そのプログラムは環境変数を通じてファイルマネージャーの現在の状態を参照できます。外部のツールやスクリプトと連携させることで、XeFM の機能を広げられます。

## キーバインド

- `programs`（**Tools → External Programs…**）：外部プログラムのダイアログを開く
- `subshell`：サブシェル（コマンドライン）モードに入る（別の機能です）

キーはキーマッププリセットによって異なります。[キーマッププリセット](KEYMAP_PRESETS_FEATURE.ja.md#すべてのキーの一覧)を参照してください。

プログラムメニューとサブシェルは別々の道具です。`programs` は設定した `PROGRAMS` の 1 つを実行して XeFM に戻り、`subshell` は現在のペインのディレクトリで対話的なシェルに入ります。

`programs` の選択画面からではなく専用のキーでプログラムを実行するには、アクションから `ctx.run_program()` を呼び出します。[キーから外部プログラムを実行する](CUSTOMIZATION_FEATURE.ja.md#キーから外部プログラムを実行する)を参照してください。

## 設定

外部プログラムは、`config.py` の `PROGRAMS` リストで設定します。各プログラムの項目には次のものが必要です。

- `name`：プログラムの表示名
- `command`：コマンドの引数リスト
- `options`（省略可）：
  - `terminal: True` — ターミナルをプログラムに引き渡し、終了するまで待ちます。全画面のプログラムや対話的なプログラム（`vim`、`less`、REPL）向けです。ターミナルモード専用です。デスクトップモードには引き渡すターミナルがないので、起動は拒否され、ログペインにエラーが出ます。
  - `auto_return` — 非推奨で、無視されます。起動が XeFM をブロックすることはありません。まだこれを書いている項目は、設定の警告で名前が示されます。

### 基本的な設定例

```python
PROGRAMS = [
    {'name': 'Git Status', 'command': ['git', 'status']},
    {'name': 'Git Log', 'command': ['git', 'log', '--oneline', '-10']},
    {'name': 'Disk Usage', 'command': ['du', '-sh', '.']},
]
```

## 環境変数

外部プログラムを実行すると、XeFM は現在の状態の情報を環境変数で渡します。

- `XEFM_THIS_DIR` / `XEFM_OTHER_DIR`：現在のペイン／反対側のペインのディレクトリ
- `XEFM_LEFT_DIR` / `XEFM_RIGHT_DIR`：左／右のペインのディレクトリ
- `XEFM_THIS_SELECTED` / `XEFM_OTHER_SELECTED` / `XEFM_LEFT_SELECTED` /
  `XEFM_RIGHT_SELECTED`：それぞれのペインで選択した（印を付けた）ファイル（スペース区切り、ダブルクォート付き）。**何も選択していないときは空です。**
- `XEFM_THIS_FOCUSED` / `XEFM_OTHER_FOCUSED` / `XEFM_LEFT_FOCUSED` /
  `XEFM_RIGHT_FOCUSED`：そのペインのカーソル位置にある 1 つの項目。同じ方法でクォートされます。選択とは関係なく、空になるのはペインが空のときだけです。
- `XEFM_ACTIVE`：XeFM の下で実行しているときは `1` になります。シェルの rc ファイルでこれを見て、たとえばサブシェルのプロンプトに印を付けられます（[ユーザーガイド](XEFM_USER_GUIDE.ja.md)の Subshell の節を参照してください）

スクリプトはこれらの変数を使って、現在の選択項目や場所に対して処理できます。

### 選択とカーソル

2 つの系統は別々に渡されるので、どちらを使うかはプログラムが自分で決められます。

```python
targets = selected or focused   # act on the selection, else the cursor
if len(selected) != 2:          # or: require a real selection
    sys.exit("select exactly two files")
```

`*_SELECTED` は選択だけを渡すので、プログラムは意図して 1 つのファイルを選択したのか、たまたまカーソルがそこにあるだけなのかを区別できます。

これは*環境変数*についての約束です。プログラムの**コマンドライン**に追加されるファイル名は、これとは違い、答えを 1 つだけ返す規則に従います。選択があれば選択、なければフォーカスされた項目です。1 つの引数リストでは両方を表せないからです。

## 使い方

1. **Tools → External Programs…**（`programs`）でプログラムのダイアログを開きます
2. 検索できる一覧でプログラムを探して選びます
3. Enter を押して起動します

プログラムは現在のペインを作業ディレクトリとしてバックグラウンドで実行されます。選択したファイル名（またはフォーカスされたファイル名）は、コマンドライン引数としても追加されます。出力（標準出力と標準エラー出力）は、ターミナルモードでもデスクトップモードでもログペインに流れ、0 以外の終了コードもそこに報告されます。その間も XeFM は普段どおりに反応します。

既定では、プログラムの入力は起動時に閉じられるので、対話的なターミナルプログラムはこの方法では実行できません。そのような項目には代わりに `'terminal': True` を指定します。ターミナルモードでは、XeFM は自分の表示を一時停止してプログラムにターミナルを引き渡し（作業ディレクトリ、引数、`XEFM_*` 環境変数は同じです）、終了すると再描画します。そのため `vim`、`less`、REPL も期待どおりに動きます。

```python
{'name': 'View with less', 'command': ['less'], 'terminal': True},
```

（以前の書き方の `'options': {'terminal': True}` も使えます。）

プログラムが 0 以外のコードで終了した場合、XeFM は再描画の前に Enter を待つので、ターミナルに残ったエラー出力を読めます。

デスクトップモードには引き渡すターミナルがないので、`terminal: True` の項目は代わりに XeFM 自身のターミナルで、動かしたまま隠せるターミナルセッションとして動きます。作業ディレクトリ、引数、`XEFM_*` 環境変数は同じです。XeFM はその終了を待ちません。[ターミナル](TERMINAL_FEATURE.ja.md)を参照してください。

## 使用例

### Git の操作
- リポジトリの状態を確認する
- 最近のコミットを見る
- ファイルをステージングに追加する

### ファイルの操作
- ファイルのパーミッションを見る
- ディスク使用量を確認する
- 大きなファイルを探す

### 開発ツール
- Python や Node.js の REPL を開く
- テストスイートを実行する
- ビルドスクリプトを実行する

### システム情報
- システム情報を見る
- メモリ使用量を確認する
- 実行中のプロセスを一覧表示する

## 自作のスクリプトを作る

初回起動時に、XeFM は個人用のツールディレクトリ `~/.xefm/tools/` を作り、そこに例として `example_tool.py` を置きます。これはすべての `XEFM_*` 変数を表示し、現在の選択を絶対パスに解決するものです。既定の `PROGRAMS` に **Example Tool (show XeFM environment)** として登録されているので、選択画面を開いてこれを実行すれば、自作のスクリプトが何を受け取るのかが正確にわかります（このディレクトリに例が置かれるのは一度だけです。例を削除すれば、削除されたままになります）。

自作のツールを追加するには次のようにします。

1. スクリプトを `~/.xefm/tools/` に置きます。`example_tool.py` をコピーして始めるのがよいでしょう。
2. `~/.xefm/config.py` の `PROGRAMS` に項目を追加します。

```python
{'name': 'My Tool', 'command': [xefm_python, xefm_tool('my_tool.py')]},
```

ツールは Python に限りません。`command` 欄はオペレーティングシステムにそのまま渡される引数リストなので、シェルスクリプトや普通のコマンドも同じように使えます。

```bash
#!/bin/bash
# Simple script that processes selected files
echo "Working in: $XEFM_THIS_DIR"
echo "Selected files: $XEFM_THIS_SELECTED"
```

```python
{'name': 'My Shell Script', 'command': ['bash', xefm_tool('my_script.sh')]},
```

## 連携の例

XeFM には、実際の外部ツールをメニューに組み込む方法を示す、すぐに使える `PROGRAMS` の項目がいくつか付属しています。どれも、上で説明した `XEFM_*` 環境変数を読む小さな補助スクリプトを指す 1 つのレシピです。補助スクリプトは XeFM 同梱のツールディレクトリ（`xefm/tools/`）にあり、実行時に `xefm_tool('name')` が見つけます。`xefm_tool` は先に `~/.xefm/tools/` を探し、次に同梱のディレクトリを探します。`xefm_python` は XeFM が動いているインタープリターです。

### Beyond Compare（削除済み）

以前のリリースには、Beyond Compare 用の補助スクリプト（`bcompare_files.py`、`bcompare_dirs.py`）とそれを使うメニュー項目が同梱されていました。どちらも削除されました。XeFM の内蔵の差分ビューアーで、選択した 2 つのファイル（**=**）と両ペインのディレクトリ（**Shift+=**）を比較できます。[差分ビューアー](DIFF_VIEWER_FEATURE.ja.md)を参照してください。古いスクリプトをまだ参照している設定では、起動の失敗がログに出ます。その `PROGRAMS` の項目を削除するか、[Beyond Compare](https://www.scootersoftware.com/) を使いたい場合は、`XEFM_LEFT_DIR` / `XEFM_RIGHT_DIR` に対して `bcompare` を実行する小さなツールを `~/.xefm/tools/` に書いてください（`example_tool.py` から始めるとよいでしょう）。

### Visual Studio Code

1 つの項目で、現在のディレクトリ（と選択したファイル）を VS Code で開けます。

```python
{'name': 'Open in VSCode',
 'command': [xefm_python, xefm_tool('vscode.py')]}
```

`vscode.py` は `XEFM_THIS_DIR` と `XEFM_THIS_SELECTED` を読みます。現在のディレクトリが git リポジトリの中にある場合は、リポジトリのルートまでさかのぼって、サブディレクトリの代わりにそれを開き、そのうえで選択した通常のファイルを追加します（ディレクトリは飛ばされます。スペースを含むファイル名も扱えます）。`PATH` に `code` コマンドが必要です。VS Code のコマンドパレットから *Shell Command: Install 'code' command in PATH* を実行してください。

## トラブルシューティング

### プログラムが見つからない
- コマンドが PATH にあることを確認してください
- 自作のスクリプトには絶対パスを使ってください

### アクセスが拒否される
- スクリプトに実行権限があることを確認してください
- ファイルやディレクトリのアクセス権を確認してください

### 出力がない
- 何も出力せずに動くプログラムもあります
- プログラムが正常に終了したことを確認してください

## クイックリファレンス

- `programs`（**Tools → External Programs…**）：外部プログラムのダイアログを開く
- `subshell`：サブシェルモードを開く（別の機能）
- 手早く済む特定の作業には外部プログラムを使う
- 対話的なコマンドライン作業にはサブシェルモードを使う
