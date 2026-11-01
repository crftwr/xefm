# XeFM ユーザーガイド

[English](XEFM_USER_GUIDE.md) \| 日本語

## 目次

- [はじめに](#はじめに)
- [インストール](#インストール)
- [デスクトップモード（Windows、macOS）](#デスクトップモードwindowsmacos)
- [基本的な使い方](#基本的な使い方)
- [中核の機能](#中核の機能)
- [ファイル操作](#ファイル操作)
- [移動](#移動)
- [検索と絞り込み](#検索と絞り込み)
- [テキストの表示と編集](#テキストの表示と編集)
- [AWS S3 との連携](#aws-s3-との連携)
- [高度な機能](#高度な機能)
- [カスタマイズ](#カスタマイズ)
- [コマンドラインオプション](#コマンドラインオプション)
- [トラブルシューティング](#トラブルシューティング)
- [機能ドキュメント](#機能ドキュメント)

---

## はじめに

XeFM（*Xenolith File Manager*）は、ネイティブのデスクトップアプリ（Windows、macOS）としても、ターミナル（Windows、macOS、Linux）でも動作する、強力な 2 画面ファイルマネージャーです。クラウドストレージとの連携、高度な検索機能、豊富なカスタマイズオプションによって、効率的なファイル管理ができます。

### XeFM の特長

- **2 画面表示**で、ディレクトリ間のファイル操作を効率的に
- **デスクトップ*と*ターミナル** - 同じアプリが、Windows／macOS ではネイティブのウィンドウとして、Windows／macOS／Linux では TUI として動作
- **AWS S3 との連携**で、クラウドストレージをシームレスに管理
- **高度な検索**：内容検索と絞り込み
- **拡張性**：外部プログラム、独自のキーバインド、`config.py` に書く Python のアクション、インストールできる[拡張パッケージ](EXTENSIONS_FEATURE.ja.md)
- **クロスプラットフォーム**：macOS、Linux、Windows に対応

---

## インストール

**デスクトップアプリ（Windows、macOS）。** Windows では [Microsoft Store](https://apps.microsoft.com/detail/9PK2X44W810V) からインストールします。macOS では[最新リリース](https://github.com/crftwr/xefm/releases/latest)から `-macos.dmg` をダウンロードするか、`brew install --cask crftwr/tap/xefm` を実行します。Python は同梱されています。デスクトップで XeFM を使うにはこれがおすすめの方法です。[デスクトップモードガイド](DESKTOP_MODE_GUIDE.ja.md#デスクトップアプリのパッケージのインストール)を参照してください。

**ターミナルアプリ（Windows、macOS、Linux）。** PyPI からインストールします。

```bash
pipx install xefm     # or:  uv tool install xefm,  or:  pip install xefm
xefm
```

[pipx](https://pipx.pypa.io) と [uv](https://docs.astral.sh/uv/) は、XeFM を専用の環境に入れたうえで `xefm` コマンドを PATH に置いてくれます。アプリケーションにはこの形が適しています。`uvx xefm` なら何もインストールせずに一度だけ試せます。必要なのは Python 3.10 以上だけで、プラットフォーム固有のものも含めて、依存関係はすべて一緒にインストールされます。

**Homebrew でターミナルアプリ（macOS、Linux）。**

```bash
brew install crftwr/tap/xefm
```

`config.py` で XeFM に同梱されていないライブラリを import している場合や、`pillow-heif` のような Pillow プラグインを使いたい場合は、`~/.xefm/requirements.txt` に書いて `xefm deps sync`（または Tools → Advanced → Sync Python Packages）を実行してください。Homebrew やデスクトップアプリを含むどのインストール方法でも動作し、アップグレード後も残ります。[追加の Python ライブラリ](PYTHON_PACKAGES_FEATURE.ja.md)を参照してください。

2 つのインストールは共存でき、`~/.xefm/` を共有します。両方をインストールするのはごく普通の使い方です。ソースのチェックアウトからの使い方は **[README](../README.ja.md#ソースから)** で説明しています。

### アップグレードとアンインストール

**インストールしたときと同じツールを使ってください。** 最初に使った方法の行を選びます。

| インストール方法 | アップグレード | アンインストール |
|----------------|---------|-----------|
| `pipx install xefm` | `pipx upgrade xefm` | `pipx uninstall xefm` |
| `uv tool install xefm` | `uv tool upgrade xefm` | `uv tool uninstall xefm` |
| `pip install xefm` | `pip install --upgrade xefm` | `pip uninstall xefm` |
| `brew install crftwr/tap/xefm` | `brew upgrade xefm` | `brew uninstall xefm` |
| `brew install --cask crftwr/tap/xefm` | `brew upgrade --cask xefm` | `brew uninstall --cask xefm` |

これらは互いに置き換えられません。どのツールも自分でインストールしたものしか知らないからです。pipx や pip でインストールしたコピーに `uv tool upgrade xefm` を実行すると `` `xefm` is not installed `` で失敗します。また、`uvx xefm` は何もインストールしないので、アップグレードするものはありません。

デスクトップ版のパッケージは、それぞれの経路でアップグレードします。Microsoft Store 版は自動で更新されます。macOS では、新しい DMG を古いアプリの上にインストールします（Homebrew でインストールした場合は `brew upgrade --cask xefm` を実行します）。すでに *アプリケーション* にある DMG 版のコピーは、`brew install --cask --adopt crftwr/tap/xefm` で Homebrew の管理に移せます。

### インストールのトラブルシューティング

- `pip install xefm` のあとに `xefm: command not found` と表示される — コンソールスクリプトが PATH にない環境にインストールされています。`pipx install xefm` や `uv tool install xefm` ならこれを自動で処理してくれます（または `python3 -m xefm` として実行します）
- pip から `error: externally-managed-environment` と表示される — [PEP 668](https://peps.python.org/pep-0668/) がシステムの Python（Homebrew、Debian/Ubuntu）を保護しています。pipx、uv、または virtualenv を使ってください
- `uv tool upgrade xefm` から `` `xefm` is not installed `` と表示される — uv が管理するのは `uv tool install` でインストールしたものだけなので、そのコピーは pipx か pip の管理下にあります（または `uvx` がインストールせずに実行しました）。インストールしたときと同じツールでアップグレードしてください。上の表を参照してください

**初回起動時：** XeFM が使うキーマッププリセットを尋ねます（[キーマッププリセット](KEYMAP_PRESETS_FEATURE.ja.md)を参照）。そのあとは矢印キーで移動、`Tab` でペインの切り替え、`F1` でヘルプ、**File → Quit** で終了です。

---

## デスクトップモード（Windows、macOS）

XeFM は、GPU アクセラレーションを使うネイティブのデスクトップアプリケーションとして動作できます。同じキーボード中心のインターフェースはそのままに、モダンなウィンドウ環境で使えます。

### クイックスタート

デスクトップ版のパッケージをインストールし（[インストール](#インストール)を参照）、macOS では Launchpad／Spotlight から、Windows ではスタートメニューから **XeFM** を開きます。

ターミナルから `xefm --backend gui` を実行しても同じウィンドウが開きますが、これは*開発*用の方法です。アプリのアイコンが正しく表示されず、macOS ではファイルのアクセス権限が XeFM ではなくターミナルのものとして扱われます。[Why not `xefm --backend gui`?](DESKTOP_MODE_GUIDE.ja.md#xefm---backend-gui-ではいけないのはなぜですか) を参照してください。

### 機能

デスクトップモードには、ターミナルモードに比べていくつかの利点があります。

- **ネイティブのウィンドウ**：標準のウィンドウ操作ができる、サイズ変更可能な Windows または macOS のウィンドウ
- **高品質な描画**：文字のグリッドではなく、ネイティブのなめらかな描画
- **より良い色**：True RGB カラーに対応し、色を正確に再現
- **フォントのカスタマイズ**：好みの等幅フォントとサイズを選択可能
- **フルスクリーン対応**：macOS ではネイティブのフルスクリーンモード
- **ウィンドウの記憶**：ウィンドウのサイズと位置を記憶

### 設定

デスクトップモードのフォントの設定は `~/.xefm/config.py` にあります（ターミナルモードでは無視されます）。

```python
# GUI fonts and size — the grid is derived from the monospace face
MONO_FONT_NAME = 'Menlo'   # monospaced face for aligned columns (None = bundled default)
UI_FONT_NAME  = None       # proportional face for names/labels (None = bundled/OS default)
FONT_SIZE     = 12         # point size applied to both faces (8–72)
```

ウィンドウのサイズと位置は、実行をまたいで**自動的に**記憶されます（Windows と macOS のそれぞれのネイティブのウィンドウ自動保存を使います）。ウィンドウの位置やサイズを指定する設定キーはありません。

#### 使えるフォント

`MONO_FONT_NAME = None`（既定値）のときは、同梱の等幅フォント Noto Sans Mono を使います。代わりに、システムにインストールされている等幅フォントを指定できます。たとえば Windows では `Consolas`、macOS では次のフォントです。
- `Menlo` - Apple の既定の等幅フォント
- `Monaco` - 昔からある Mac の等幅フォント
- `SF Mono` - San Francisco Mono（インストールされている場合）
- `Courier New` - 伝統的な等幅フォント
- `Fira Code` - 人気のプログラミング用フォント（インストールされている場合）
- `JetBrains Mono` - モダンなプログラミング用フォント（インストールされている場合）

### バックエンドの選択

バックエンドは `--backend` フラグだけで選びます。設定ファイルで指定する項目はありません。既定はターミナルモードです。

- `--backend tui` — ターミナル。既定です（`--backend curses` を指定すると、普通でないターミナル向けの代替手段として、従来の curses による描画を使います）
- `--backend gui` — Windows（別名 `windows`）または macOS（別名 `macos`）のネイティブのウィンドウ

Linux にはデスクトップのバックエンドがないので、ターミナルモードを使ってください。

### キーボードショートカット

ターミナルモードとデスクトップモードのキーマップは 1 つです。デスクトップのウィンドウでは、2 つのアクション（OS のアプリでファイルを開く操作と、macOS でのテキストのコピー）に、プラットフォーム標準のキーの組み合わせがもう 1 つ割り当てられます。それ以外はすべて共通です。`~/.xefm/config.py` の "Three cases" を参照してください。

**F1** を押せば、いつでも内蔵のヘルプを表示できます。ヘルプは自分の `KEY_BINDINGS` から作られるので、常にその設定のとおりです。

### パフォーマンス

デスクトップモードは非常に良好なパフォーマンスを発揮します。
- **描画**：GPU アクセラレーションで 60 FPS
- **応答性**：入力に即座に反応
- **大きなディレクトリ**：ファイルが何千個あってもなめらかにスクロール
- **検索の操作**：UI を止めずに更新

### デスクトップモードのトラブルシューティング

**デスクトップモードが起動しない：**
- Windows か macOS で実行しているか確認します（Linux ではターミナルモードのみです）
- Python のバージョンを確認します（3.10 以上が必要です）

**ウィンドウが表示されない：**
- コンソールの出力にエラーメッセージがないか確認します
- PyObjC がインストールされているか確認します：`python3 -c "import objc; print('OK')"`
- まずターミナルモードで XeFM が動作するか確認します：`python3 -m xefm`

**フォントの問題：**
- フォント名が正しいか確認します（大文字と小文字を区別します）
- `Font Book.app` でインストールされているフォントを確認します
- 既定に戻すには、設定から `MONO_FONT_NAME` を削除します（または `None` にします）

**パフォーマンスの問題：**
- デスクトップモードは 60 FPS で動作するはずです
- アクティビティモニタで CPU／GPU の使用率を確認します
- 設定でウィンドウのサイズを小さくしてみます

---

## 基本的な使い方

### 初回起動
XeFM を初めて起動すると、次のものが表示されます。
- **左ペイン**：カレントディレクトリ
- **右ペイン**：ホームディレクトリ
- **ログペイン**：下部にシステムメッセージ
- **ステータスバー**：現在のパスとファイルの情報

### 基本のキー
- **矢印キー**：ファイルやディレクトリの間を移動
- `switch_pane`：左右のペインを切り替え
- `open_item`：ディレクトリに入る、またはテキストファイルを表示
- `go_parent`：親ディレクトリへ移動
- `go_root`：現在のドライブや場所のルートへ移動
- `help`：ヘルプダイアログを表示。ほかのすべてのアクションのキーもここでわかります

最初に `F1`（`help`）を押してください。このダイアログは自分の `KEY_BINDINGS` から作られるので、常にその設定に合ったキーの一覧です。
- `quit`：XeFM を終了（**File → Quit**）

---

## 中核の機能

### 2 画面のしくみ
- **左右のペイン**：それぞれ独立にファイルをブラウズし、ペイン間で連動した操作が可能
- **アクティブなペインの強調表示**：フォーカスのあるペインがひと目でわかる
- **Tab での切り替え**：Tab キーでペインをすばやく切り替え
- **ペインの同期**：ペイン間でディレクトリやカーソル位置を同期
- **サイズ変更できるレイアウト**：角括弧のキーでペインの境界を調整

**詳しいドキュメント**：[ステータスバー](STATUS_BAR_FEATURE.ja.md)

### 表示
- **ファイルの情報**：サイズ、日付、パーミッションを表示
- **隠しファイルの切り替え**：`toggle_hidden` で隠しファイルの表示／非表示を切り替え。どのプラットフォームでもドットで始まる名前が対象で、Windows では隠し属性を持つファイルやフォルダーも対象になります
- **配色**：ダーク系とライト系のテーマを実行中に切り替え
- **ステータスバー**：現在のパス、ファイル数、操作の状態
- **ログペイン**：システムメッセージや出力を表示する下部のペイン
- **全角文字への対応**：各国語のファイル名や Unicode 文字を正しく表示

**詳しいドキュメント**：
- [配色](COLOR_SCHEMES_FEATURE.ja.md)
- [全角文字への対応](WIDE_CHARACTER_SUPPORT_FEATURE.ja.md)

---

## ファイル操作

### 基本の操作

| アクション | 動作 |
|--------|--------------|
| `toggle_select_down` | ファイルを選択／解除して 1 つ下に移動 |
| `select_range` | 最も近い選択項目からカーソルまでをすべて選択 |
| `copy_files` | 選択したファイルを反対側のペインにコピー |
| `move_files` | 選択したファイルを移動 |
| `copy_files_to` / `move_files_to` | 選択したファイルを、入力したディレクトリにコピー／移動 |
| `create_directory` | ディレクトリを作成（何も選択していないときの同じキー） |
| `delete_files` | 選択したファイルを削除 |
| `rename` | ファイルの名前を変更（複数なら一括リネーム） |
| `edit_file` | 選択項目（またはフォーカスのあるファイル）を外部エディターで編集 |
| `create_file` | 新しいファイルを作成 |

**詳しいドキュメント**：
- [ファイル操作](FILE_OPERATIONS_FEATURE.ja.md)

### 複数選択
1. `toggle_select_down` でファイルを 1 つずつ選択します
2. `select_range` でひと続きの範囲をまとめて選択します。最初のファイルに印を付け、最後のファイルにカーソルを移動すると、その間がすべて選択されます
3. `toggle_select_files` ですべてのファイルを選択／解除します
4. `toggle_select_items` ですべての項目（ファイルとディレクトリ）を選択／解除します
5. `select_by_pattern` / `unselect_by_pattern` でパターン（`*.jpg *.png`）にマッチするファイルを選択／解除し、`select_same_extension` でカーソル位置のファイルと同じ拡張子のファイルをすべて選択します。[パターンで選択](SELECT_BY_PATTERN_FEATURE.ja.md)を参照してください
6. `cursor_next_selected` / `cursor_prev_selected` で選択した項目の間を移動します
7. 選択項目に対して操作を実行します

`select_range` は、カーソルより上にある最も近い選択項目を起点にします。上に選択項目がなければ、下にある最も近いものを使います。そのため、印を付けたファイルから下に移動しても上に移動しても同じように動作します。この操作は選択を追加するだけです。範囲外の項目の状態は変わらないので、複数の範囲を積み重ねられます。

範囲の反対の端までカーソルを移動するには、矢印キーだけでなく検索も使えます。`isearch` を実行して名前を必要なだけ入力し、`isearch.accept`（Enter）を押すと、見つかったファイルにカーソルを置いたまま検索を終了します。そこで `select_range` を実行すれば範囲が選択されます。検索バーには意図的に範囲選択のキーがありません。検索バーのカーソルはマッチした項目にありますが、先に印を付けた項目はマッチしていないので、そこで範囲を選択すると、パターンにマッチしなかったファイルまで含まれてしまうからです。先に検索を終了すれば、キーは文字どおりの意味で動作します。

既定のキーは `Shift-Space` ですが、ターミナルはこのキーを伝えられません。印字可能なキーには修飾キーを載せる余地がないので、POSIX のターミナルは単なるスペースとして伝え、1 つの項目の選択を切り替えてしまいます。Terminal.app、iTerm2、Linux のターミナルでは、ターミナルが伝えられるキーの組み合わせに割り当てるか、**Select → Select to Cursor** を使ってください。

```python
KEY_BINDINGS = {
    'select_range': ['Ctrl-LEFT'],   # or 'F6', 'Ctrl-Y' …
}
```

**詳しいドキュメント**：[キーバインド](KEY_BINDINGS_FEATURE.ja.md)

### 高度な操作
- **一括リネーム**：正規表現で複数のファイルの名前を変更
- **アーカイブの作成**：ZIP、TAR.GZ、TGZ のアーカイブを作成（`create_archive`）
- **アーカイブの展開**：アーカイブを反対側のペインに展開（`extract_archive`）
- **ファイルの比較**：ペイン間で選択したファイルを比較

**詳しいドキュメント**：[一括リネーム](BATCH_RENAME_FEATURE.ja.md)

### 安全のための機能
- **確認ダイアログ**：元に戻せない操作の前にユーザーに確認
- **競合の解決**：両方のファイルのサイズと日付を見たうえで、Overwrite、Overwrite older、Skip、Keep both、Compare、Cancel から選択。1 回だけ、または残りのすべての競合に適用
- **権限のチェック**：ファイルシステムの権限を検証
- **取り消し不能な操作の防止**：元に戻せない操作についてはっきりと警告

**詳しいドキュメント**：[ファイル操作](FILE_OPERATIONS_FEATURE.ja.md)

---

## 移動

### ディレクトリの移動

矢印キーでカーソルを動かし、`nav_left` / `nav_right` でペインの間を移動したり、ディレクトリに出入りしたりします。`open_item` はディレクトリに入るかファイルを表示し、`go_parent` は上の階層に移動し、`go_root` は現在のドライブや場所のルートに移動し、`cursor_top` / `cursor_bottom` は最初／最後の項目に移動します。

### すばやい移動

| アクション | 開くもの |
|--------|---------------|
| `favorites` | お気に入りのディレクトリとファイル |
| `jump_to_path` | パスへ移動（ファイルのパスならそのファイルにカーソルを置く） |
| `history` | どちらかのペインで訪れたディレクトリ |
| `sync_current_to_other` | 反対側のペインをこのペインのディレクトリにする |
| `sync_other_to_current` | このペインを反対側のペインのディレクトリにする |

**詳しいドキュメント**：
- [ナビゲーションダイアログ](NAVIGATION_DIALOGS_FEATURE.ja.md)

---

## 検索と絞り込み

### 検索の方法

| アクション | 動作 |
|--------|--------------|
| `isearch` | インクリメンタルサーチ（入力しながらマッチ） |
| `find_files` | 別スレッドで動くファイル名検索のダイアログ |
| `find_in_files` | 内容検索（grep）のダイアログ |
| `filter` | ペインを絞り込む（パターン、または設定で定義したフィルター） |
| `clear_filter` | 現在のフィルターを解除 |

### ソート
`sort` でソートのダイアログ（キーと順序）を開きます。`quick_sort_name`、`quick_sort_ext`、`quick_sort_size`、`quick_sort_date` は、それぞれ 1 回押すだけでソートします。

ダイアログの操作方法（キーは頭文字で選び、Left/Right で昇順／降順を選ぶ）は[ソートダイアログ](SORT_DIALOG_FEATURE.ja.md)を参照してください。

### インクリメンタルサーチのキー

`isearch` を実行してから入力します。検索バーが開いている間は、次のアクションが使えます。

| アクション | 動作 |
|--------|--------------|
| `isearch.prev_match` / `isearch.next_match` | 前／次のマッチ |
| `isearch.toggle_select_down` | ファイルを選択して、次のマッチに移動 |
| `isearch.select_matches` | すべてのマッチを一度に選択。もう一度で解除 |
| `isearch.accept` | 現在のマッチで止まる |
| `isearch.cancel` | キャンセルして、カーソルを元の位置に戻す |

検索はマッチがあるところで止まります。入力するとマッチがなくなってしまう文字は受け付けられないので、パターンは空のリストに進むことなく、最後に見つかったファイルにとどまります。Backspace を押せばいつでも戻れます。（ローマ字で日本語を入力するときは数文字の余裕があります。`ni` は `nih` になって初めて日本語にマッチするからです。[Migemo 検索](MIGEMO_SEARCH_FEATURE.ja.md)を参照してください。）

Space はスペースを入力します。スペースはパターンの単語を区切ります（`re 24` で `report_2024.txt` が見つかります）。そのため、ここでファイルに印を付けるキーは、多くのプリセットでファイルリストの印付けに使う Space だけではなく `Ctrl-Space` です。ここでは Space は文字を入力するので、Ctrl を付けることで、普通なら文字を入力するキーがコマンドになります。*逆方向*に印を付けるキーは、どちらにも既定では割り当てられていません。使いたい場合は `isearch.toggle_select_up` を割り当ててください。
`isearch.select_matches` は、右側のカウンターが示しているマッチ全体に印を付けます。`.log` と入力してこれを実行すれば、すべてのログファイルが選択されます。検索の外で選択したファイルはそのままなので、2 回目の検索の結果はそれに追加されます。これらのキーはすべて割り当て直せます。[カスタマイズ](CUSTOMIZATION_FEATURE.ja.md#インクリメンタルサーチバー)を参照してください。

### 検索のヒント
- **インクリメンタルサーチ**：入力を始めるとすぐにファイルが絞り込まれます
- **ローマ字で日本語（Migemo）**：インクリメンタルサーチで `kensaku` と入力すると `検索` も見つかります。IME は必要ありません。[Migemo 検索](MIGEMO_SEARCH_FEATURE.ja.md)を参照してください。
- **パターンでの絞り込み**：`*.txt` や `test_*` のようなワイルドカードを使います。スペース（または `;`）で区切って複数のパターンを書くと、どれかにマッチするファイルが表示されます（`*.jpg *.png *.svg`）。スペースを含むパターンは引用符で囲みます：`"my file*"`
- **独自のフィルター**：`filter` の入力欄には、設定で定義したフィルターも *clear filter* の下に並びます。名前だけでなく、ファイルのあらゆる情報でマッチできます（「今日更新したもの」「100 MB 超」など）。[カスタマイズ](CUSTOMIZATION_FEATURE.ja.md#自分のフィルターfilters)を参照してください。
- **ファイル名検索**（`find_files`）：検索語はファイル名全体に*完全一致*する glob です。`report.txt` はその名前にしかマッチしません。部分一致させるにはワイルドカードを加えます：`report*`、`*.py`、以前の「含む」動作なら `*report*`。
- **内容検索**：進捗を見ながらファイルの中を検索します。ペインのフィルターが有効なら、検索の対象はそのフィルターにマッチするファイルに絞られます。`*.txt` で絞り込んでいれば、grep されるのは `.txt` ファイルだけです（サブディレクトリはそれでもたどります）。フィルターが適用されている間は、ダイアログのタイトルにパターンが表示されます。BOM 付きの Unicode ファイル（UTF-8、UTF-16、UTF-32）は、バイナリとして飛ばされずにテキストとして検索されます。
- **クイックソート**：`quick_sort_*` アクションは 1 回押すだけでソートします
- **ESC**：どの検索の操作もキャンセルします

**詳しいドキュメント**：[検索アニメーション](SEARCH_ANIMATION_FEATURE.ja.md)

---

## テキストの表示と編集

### 内蔵のテキストビューアー

`view_file` は、フォーカスのあるファイルを内蔵のビューアーで開きます。独自の `enter` ルールがないファイルなら、`open_item` でも開きます。

### テキストビューアーの操作

矢印キー、ページ送り、Home/End でスクロールします。`toggle_wrap` は行の折り返しのオン／オフを切り替え、`toggle_view_mode` は Markdown などのリッチなファイルの整形表示と生テキストの表示を切り替え、`change_encoding` はテキストのエンコーディングを選び、`isearch` はファイルの中を検索し、`edit_file` はファイルをエディターに渡します。`quit`（または Esc）でビューアーを閉じます。ビューアーは下部に自分のキーを表示し、ビューアーの中で `F1` を押すとすべてのキーが一覧されます。[テキストビューアー](TEXT_VIEWER_FEATURE.ja.md)を参照してください。

### 外部エディター

`edit_file` は選択項目（またはフォーカスのあるファイル）を編集し、`create_file` は新しいファイルを作ります。

複数のファイルを選択していると、`edit_file` はそれらをすべて開きます。同じエディターで開くファイルは、1 回の起動でまとめて渡されます（`vim a.txt b.txt`）。

使いたいエディターは `~/.xefm/config.py` で設定します。
```python
TEXT_EDITOR = 'vim'  # or 'nano', 'code', etc.
```

**詳しいドキュメント**：[テキストエディター](TEXT_EDITOR_FEATURE.ja.md)

### サブシェル

`subshell` は、カレントディレクトリでシェルを開きます。

ターミナルモードでは、シェルを終了すると XeFM に戻ります。デスクトップアプリには引き渡せる自前のターミナルがないので、代わりにターミナルのウィンドウでシェルを開きます。[外部ターミナル](EXTERNAL_TERMINAL_FEATURE.ja.md)を参照してください。シェルからは `XEFM_*` 環境変数（ペインのディレクトリと選択項目）が見え、プロンプトの先頭に `[XeFM]` が付きます。

この先頭の文字列は `PS1`/`PROMPT` 環境変数で渡されるので、起動ファイルで独自のプロンプトを設定するシェルでは上書きされます。zsh は必ずそうなります。macOS では、`~/.zshrc` がなくても、`/etc/zshrc` が対話シェルのたびにプロンプトをリセットするからです。その場合は、代わりに `~/.zshrc` の**最後**で `XEFM_ACTIVE` を見て設定してください。

```zsh
if [[ -n $XEFM_ACTIVE ]]; then
  PROMPT="[XeFM] $PROMPT"
fi
```

コマンドを実行するたびにプロンプトを作り直すフレームワーク（powerlevel10k、starship）では、これでも上書きされます。その場合は、フレームワーク自身の設定に目印を入れてください。たとえば starship の `env_var` モジュールや、powerlevel10k の独自のセグメントです。

どの変数で先頭の文字列を渡すかは、起動するシェルによって決まります。`cmd.exe` は `PROMPT` を独自の `$` コードの構文で読むので、`[XeFM] $P$G`（または既存の `PROMPT` の先頭に付けたもの）が渡されます。PowerShell は `prompt` 関数でプロンプトを作り、環境変数ではそれに手が届かないので、先頭の文字列は付きません。プロファイルで `XEFM_ACTIVE` を見て関数を定義してください。

```powershell
if ($env:XEFM_ACTIVE) {
  function prompt { "[XeFM] $($executionContext.SessionState.Path.CurrentLocation)$('>' * ($nestedPromptLevel + 1)) " }
}
```

XeFM は既定で `$SHELL` を起動し、それがなければプラットフォームの既定（Windows では `cmd.exe`、それ以外では `/bin/sh`）を使います。`~/.xefm/config.py` で変更できます。
```python
SUBSHELL = 'zsh'                     # a single command...
SUBSHELL = ['powershell', '-NoLogo'] # ...or a command with arguments
```

---

## AWS S3 との連携

XeFM は AWS S3 にネイティブに対応していて、クラウドストレージをシームレスに管理できます。セットアップ、使い方、トラブルシューティング、高度な機能を含む S3 の詳しい説明は、**[AWS S3 対応の機能ガイド](S3_SUPPORT_FEATURE.ja.md)** を参照してください。

### クイックスタート

1. AWS の認証情報を設定します。`aws configure`、`AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_DEFAULT_REGION` 環境変数、または IAM ロール（EC2 では設定不要）を使います
2. s3:// の URI で S3 バケットに移動します

### S3 での移動
```bash
# Navigate to S3 bucket
s3://my-bucket/

# Navigate to specific path
s3://my-bucket/path/to/files/
```

### S3 での操作
- 標準のファイル操作はすべて S3 のオブジェクトでも使えます
- ローカルと S3 のストレージの間でコピーできます
- S3 のテキストファイルや画像を直接表示できます（編集はローカルでのみ可能です。ファイルをローカルのペインにコピーし、そこで編集してから、コピーして戻してください）
- S3 のオブジェクトでアーカイブを作成／展開できます

### S3 の例
```bash
# Copy local files to S3
# 1. Select files in left pane (local directory)
# 2. Navigate right pane to s3://bucket/path
# 3. Run copy_files (File → Copy to Other Pane)

# View S3 text file
# 1. Navigate to s3://bucket/file.txt
# 2. Run view_file (File → Open With ▸ Viewer); editing needs a local copy
```

---

## 高度な機能

### サブシェルモード
`subshell` でサブシェルモードに入ります（デスクトップアプリではターミナルのウィンドウで開きます。[外部ターミナル](EXTERNAL_TERMINAL_FEATURE.ja.md)を参照してください）。次の環境変数が設定されます。
- `XEFM_LEFT_DIR`：左ペインのディレクトリ
- `XEFM_RIGHT_DIR`：右ペインのディレクトリ
- `XEFM_THIS_DIR`：アクティブなペインのディレクトリ
- `XEFM_OTHER_DIR`：反対側のペインのディレクトリ
- `XEFM_THIS_SELECTED`：アクティブなペインで選択したファイル。何も選択していなければ空です
- `XEFM_THIS_FOCUSED`：選択にかかわらず、アクティブなペインでカーソル位置にある項目（`*_FOCUSED` はほかの 3 つのペインの変数にもあります）

### 外部プログラム
`programs` で外部プログラムのメニューを表示します。プログラムからは XeFM の環境変数を使えます。

**詳しいドキュメント**：[外部プログラム](EXTERNAL_PROGRAMS_FEATURE.ja.md)

### ペインのレイアウト

`adjust_pane_left` / `adjust_pane_right` でペインの境界を動かし、`reset_pane_boundary` で 50/50 に戻します。`adjust_log_up` / `adjust_log_down` でログペインの高さを変え、`reset_log_height` で元に戻します。

### ファイルの比較

`diff_files` は選択した 2 つのテキストファイルの差分を表示し、`diff_directories` は 2 つのペインのカレントディレクトリを再帰的に比較し、`compare_selection` はファイルとディレクトリの比較オプションを開きます。

**詳しいドキュメント**：[差分ビューアー](DIFF_VIEWER_FEATURE.ja.md)（ファイルとディレクトリの差分）

### 表示のオプション

`toggle_hidden` で隠しファイルの表示／非表示を切り替えます。

そのほかの表示の設定（ソート、隠しファイル、テーマ）も、メニューバーの **View** にあります。

配色のテーマはメニューバー（**View → Theme**）で切り替えます。キーボードで順に切り替えたい場合は、`~/.xefm/config.py` で `toggle_color_scheme` にキーを割り当ててください。

### 進捗のアニメーション
ファイルの検索のような時間のかかる操作の間、XeFM は進捗をアニメーションで表示します。

**詳しいドキュメント**：[検索アニメーション](SEARCH_ANIMATION_FEATURE.ja.md)

---

## カスタマイズ

### 設定ファイル
XeFM は初回起動時に `~/.xefm/config.py` を作成します。次の方法で開けます。
- メニューバーの **Tools → Edit Configuration…**
- または `~/.xefm/config.py` を直接編集

**設定の詳しいドキュメント**は、使えるすべてのオプション、例、おすすめの使い方を網羅した **[設定機能ガイド](CONFIGURATION_FEATURE.ja.md)** を参照してください。

### キーバインド

XeFM のキーバインドは、修飾キーや、1 つのアクションへの複数のキーの割り当てを含めて、柔軟にカスタマイズできます。

```python
KEY_BINDINGS = {
    # An action can have several keys — add your own alongside the defaults
    'quit': ['Q'],
    'help': ['F1'],

    # e.g. add vim-style movement next to the arrow keys
    'cursor_up': ['UP', 'k'],
    'cursor_down': ['DOWN', 'j'],

    # Modifier key combinations
    'page_up': ['PAGE_UP', 'Shift-UP'],
    'page_down': ['PAGE_DOWN', 'Shift-DOWN'],

    # Extended form with a selection requirement
    'delete_files': {
        'keys': ['K', 'DELETE'],
        'selection': 'required'  # only when files are selected
    },
    'create_directory': {
        'keys': ['M'],
        'selection': 'none'      # only when nothing is selected
    },
}
```

**主な特長：**
- **修飾キー**：Shift、Control、Alt、Command
- **1 つのアクションに複数のキー**：同じアクションに複数のキーを割り当て可能
- **選択の条件**：アクションを使える状況を制御
- **大文字と小文字を区別しないキー**：特殊キーの名前（'ENTER' = 'enter'）と英字だけのキー（'q' = 'Q'）は同じ物理キーに割り当てられます。Shift を押した方を割り当てるには 'Shift-Q' を使います
- **修飾キーの順序は自由**：'Command-Shift-X' = 'Shift-Command-X'

**詳しいドキュメント**：[キーバインド](KEY_BINDINGS_FEATURE.ja.md)

### テーマ
XeFM には複数の内蔵テーマ（Dark+、Light+、Monokai、Dracula、Nord、Solarized、Gruvbox Dark、Solarized Light）が付属していて、最後に使ったテーマを覚えています。実行中は **View → Theme ▸ Next Theme** で順に切り替えるか、**View → Theme** から選びます。独自のテーマは設定の `THEMES` 辞書で定義します。

**詳しいドキュメント**：[配色](COLOR_SCHEMES_FEATURE.ja.md)

### お気に入り
```python
FAVORITES = [
    {'name': 'Projects', 'path': '~/dev'},
    {'name': 'Documents', 'path': '~/Documents'},
    {'name': 'S3 Bucket', 'path': 's3://my-bucket/'},
]
```

**詳しいドキュメント**：[ナビゲーションダイアログ](NAVIGATION_DIALOGS_FEATURE.ja.md)

### 外部プログラム
```python
PROGRAMS = [
    {'name': 'Git Status', 'command': ['git', 'status']},
    {'name': 'Open in VSCode', 'command': ['code', '.']},
    {'name': 'View with less', 'command': ['less'],
     'options': {'terminal': True}},
]
```

**詳しいドキュメント**：[外部プログラム](EXTERNAL_PROGRAMS_FEATURE.ja.md)

---

## コマンドラインオプション

ここで説明するオプションは、ターミナル版のインストールとソースのチェックアウトで使えます。デスクトップ版のパッケージはコマンドラインの引数を取りません。ランチャーがネイティブのバックエンドを直接起動します。

### 基本的な使い方
```bash
python3 -m xefm                    # Terminal mode — the default
python3 -m xefm --left ~/projects  # Set the left pane's startup directory
python3 -m xefm --right ~/docs     # Set the right pane's startup directory
```

### バックエンドの選択
`--backend` で描画のバックエンドを選びます。

```bash
python3 -m xefm --backend tui      # Terminal — default (--backend curses: classic curses fallback)
python3 -m xefm --backend gui      # Native window (aliases: --backend macos / windows)
```

`--backend gui` はデスクトップモードの開発用の方法です。普段使いには、代わりにデスクトップ版のパッケージをインストールしてください（[理由](DESKTOP_MODE_GUIDE.ja.md#xefm---backend-gui-ではいけないのはなぜですか)）。

### すべてのオプション
```bash
--backend {tui,curses,gui,macos,windows}  # Rendering backend (default: tui)
--left DIR                        # Left pane startup directory
--right DIR                       # Right pane startup directory
--version                         # Show version and exit
--help                            # Show help and exit
```

### オプションの組み合わせ
```bash
# Desktop window with custom startup directories (from a checkout)
python3 -m xefm --backend gui --left ~/projects --right ~/docs
```

`--left`/`--right` で指定した起動時のディレクトリは、そのセッションでは保存されたペインの履歴より優先されます。無効なパスを指定した場合は、保存されたディレクトリ（またはホームディレクトリ）が使われます。

---

## トラブルシューティング

### よくある問題

#### デスクトップモードが起動しない（Windows／macOS）
- Python のバージョンを確認します：`python3 --version`（3.10 以上が必要です）
- まずターミナルモードを試します：`xefm`
- コンソールの出力にエラーメッセージがないか確認します

#### Linux でのデスクトップモード
デスクトップモードは Windows と macOS でのみ動作します。Linux で `--backend gui` を指定しても、ターミナルモードには切り替わらず、起動に失敗します。ターミナルモードで使うには、このオプションを付けずに XeFM を起動してください。

#### 色が正しく表示されない
ターミナルの色の対応状況と TERM 環境変数を確認してください

#### 全角文字が正しく表示されない
ターミナルの Unicode 対応とロケールの設定を確認してください

**詳しいドキュメント**：[全角文字への対応](WIDE_CHARACTER_SUPPORT_FEATURE.ja.md)

#### キーが反応しない
ターミナルのキーの対応付けと ESCDELAY の設定を確認してください

#### S3 へのアクセスが拒否される
AWS の認証情報とバケットの権限を確認してください

#### ファイル操作が失敗する
ファイルの権限とディスクの空き容量を確認してください

#### パフォーマンスの問題
- デスクトップモードは GPU アクセラレーションにより高いパフォーマンスを発揮します
- `pygments` をインストールすると、シンタックスハイライトが速くなります
- 大きなディレクトリを操作するときは、使えるメモリを確認してください

### ヘルプ
- **F1** を押すと内蔵のヘルプが表示されます
- **Tools → Command Palette…** で[コマンドパレット](COMMAND_PALETTE_FEATURE.ja.md)が開きます。どのアクションも名前で探して、キーを確かめ、実行できます
- 下の機能ドキュメントを確認してください
- コマンドラインオプションの `--help` を使ってください
- [XeFM wiki](https://github.com/crftwr/xefm/wiki) にはレシピとコミュニティの拡張機能がまとめられています
- 質問や作ったものの紹介は [Discussions](https://github.com/crftwr/xefm/discussions) へ、バグの報告は [Issues](https://github.com/crftwr/xefm/issues) へどうぞ

**詳しいドキュメント**：[ヘルプダイアログ](HELP_DIALOG_FEATURE.ja.md)

---

## 機能ドキュメント

個々の機能の詳しい情報は、次の専用のガイドを参照してください。

### ファイル操作
- [ファイル操作](FILE_OPERATIONS_FEATURE.ja.md) - コピー、移動、複製、名前の競合の処理、進捗
- [ゴミ箱への削除](TRASH_FEATURE.ja.md) - ゴミ箱への削除、または完全な削除
- [ファイルクリップボード](FILE_CLIPBOARD_FEATURE.ja.md) - 今コピーまたは切り取りして、次に移動した先で貼り付け（Finder／エクスプローラーとの間でも）
- [バックグラウンドジョブ](BACKGROUND_JOBS_FEATURE.ja.md) - コピー、移動、削除の実行中も作業を続ける
- [類似ファイルの検索](FIND_SIMILAR_FILES_FEATURE.ja.md) - 同一ファイルと、似た画像・動画・音声を、XeFM を終了しても続くスキャンで検索
- [一括リネーム](BATCH_RENAME_FEATURE.ja.md) - 正規表現で複数のファイルの名前を変更
- [エディターでの名前の変更](RENAME_IN_EDITOR_FEATURE.ja.md) - テキストエディターで名前を編集して、多数のファイルの名前を変更
- [パターンで選択](SELECT_BY_PATTERN_FEATURE.ja.md) - パターンにマッチするすべてのファイルを選択／解除
- [ファイルのタグ](FILE_TAGS_FEATURE.ja.md) - システムが管理するタグの読み書きと、タグによる検索
- [ファイルリストのレイアウト](FILE_LIST_LAYOUTS_FEATURE.ja.md) - 行に表示する列の選択と定義、フォルダーのサイズ、Git の状態などの独自の値
- [アーカイブ](ARCHIVE_FEATURE.ja.md) - アーカイブの作成、展開、ブラウズ（パスワード付きも含む）
- [ファイルの詳細](FILE_DETAILS_FEATURE.ja.md) - ファイルの詳しい情報の表示
- [OS のインデックス検索](OS_INDEX_SEARCH_FEATURE.ja.md) - Spotlight と Windows Search の結果を一覧として表示
- [ファイルリスト](FILE_LIST_IMPORT_FEATURE.ja.md) - クリップボード、ファイル、コマンドから得たパスの一覧をペインに表示
- [テキストとしての文書](DOCUMENT_VIEWER_FEATURE.ja.md) - ビューアーと内容検索での PDF、Office、EPUB ファイル
- [クイックビュー](QUICK_VIEW_FEATURE.ja.md) - カーソル位置の項目を反対側のペインでプレビュー
- [ツリーファイル](TREE_FILES_FEATURE.ja.md) - 参照をまとめた .xft をブラウズし、実際のファイルを操作
- [ファイル監視](FILE_MONITORING_FEATURE.ja.md) - ディスク上でディレクトリが変更されたときに自動で更新
- [ディレクトリの同期](DIRECTORY_SYNC_FEATURE.ja.md) - ディレクトリの差分から、一方のディレクトリをもう一方に合わせる

### リモートとクラウドのストレージ
- [AWS S3 対応](S3_SUPPORT_FEATURE.ja.md) - クラウドストレージとの連携と S3 バケットの管理
- [SFTP 対応](SFTP_SUPPORT_FEATURE.ja.md) - SSH 経由のリモートサーバーへのアクセス
- [リモートのファイルの編集](REMOTE_EDIT_FEATURE.ja.md) - SSH や S3 上のファイルをローカルのエディターで編集

### 移動と検索
- [ナビゲーションダイアログ](NAVIGATION_DIALOGS_FEATURE.ja.md) - お気に入り、ジャンプ、履歴、ドライブの選択画面
- [キーマッププリセット](KEYMAP_PRESETS_FEATURE.ja.md) - AFX style、Orthodox、OS native、Vim style と、それぞれのすべてのキーの一覧
- [フォルダータブ](FOLDER_TABS_FEATURE.ja.md) - 各ペインで複数の場所を開いたままにする
- [フラット表示](FLAT_VIEW_FEATURE.ja.md) - ディレクトリ以下のすべてのファイルを 1 つの平らな一覧で表示
- [サーバーへ接続](CONNECT_TO_SERVER_FEATURE.ja.md) - XeFM の中から NAS やファイルサーバーをマウント
- [Tab 補完](TAB_COMPLETION_FEATURE.ja.md) - 入力ダイアログでのパスの補完
- [Migemo 検索](MIGEMO_SEARCH_FEATURE.ja.md) - インクリメンタルサーチで、入力したローマ字から日本語にマッチ
- [検索のオプション](SEARCH_OPTIONS_FEATURE.ja.md) - ファイル名検索と内容検索のオプション
- [検索アニメーション](SEARCH_ANIMATION_FEATURE.ja.md) - 検索中の進捗の表示

### ビューアー
- [テキストビューアー](TEXT_VIEWER_FEATURE.ja.md) - 内蔵のテキストビューアーでのシンタックスハイライト、選択、検索
- [Markdown ビューアー](MARKDOWN_VIEWER_FEATURE.ja.md) - Markdown の整形表示
- [JSON／CSV ビューアー](JSON_CSV_VIEWERS_FEATURE.ja.md) - 構造化ファイルの整形表示
- [画像ビューアー](IMAGE_VIEWER_FEATURE.ja.md) - 拡大縮小とスクロールができる内蔵の画像ビューアー
- [差分ビューアー](DIFF_VIEWER_FEATURE.ja.md) - ファイルとディレクトリの差分ビューアー
- [テキストのエンコーディング](TEXT_ENCODING_FEATURE.ja.md) - ビューアーでの古いエンコーディングの判定と、手動での選択
- [テキストエディター](TEXT_EDITOR_FEATURE.ja.md) - 外部エディターとの連携

### インターフェースと表示
- [2 画面](DUAL_PANE_FEATURE.ja.md) - 2 つのペインのレイアウトとペインの操作
- [メニューバー](MENU_BAR_FEATURE.ja.md) - ネイティブ／ウィンドウ内のメニューバー
- [ステータスバー](STATUS_BAR_FEATURE.ja.md) - ビューアーの状態の表示
- [ヘルプダイアログ](HELP_DIALOG_FEATURE.ja.md) - 内蔵のヘルプ
- [コマンドパレット](COMMAND_PALETTE_FEATURE.ja.md) - すべてのアクションを名前で探して実行
- [コンテキストメニュー](CONTEXT_MENU_FEATURE.ja.md) - 項目とディレクトリの右クリックメニューを、マウスやキーボードから
- [今日のヒント](TIPS_FEATURE.ja.md) - 起動時に 1 つの機能についての短いヒントを表示
- [マウスと操作](MOUSE_EVENT_SUPPORT_FEATURE.ja.md) - マウス、ダブルクリック、ドラッグ＆ドロップ
- [配色と視覚効果](COLOR_SCHEMES_FEATURE.ja.md) - テーマ、背景アニメーション、動き
- [全角文字への対応](WIDE_CHARACTER_SUPPORT_FEATURE.ja.md) - 各国語の文字の表示
- [デスクトップモードガイド](DESKTOP_MODE_GUIDE.ja.md) - ネイティブのデスクトップアプリの導入とオプション

### 設定とカスタマイズ
- [設定](CONFIGURATION_FEATURE.ja.md) - 設定の完全なリファレンスとカスタマイズガイド
- [キーバインド](KEY_BINDINGS_FEATURE.ja.md) - カスタマイズできるキーボードショートカット
- [カスタマイズ](CUSTOMIZATION_FEATURE.ja.md) - ビューアーのキーの割り当て直し、自分の Python 関数へのキーの割り当て、イベントでの関数の実行
- [ファイルの関連付け](FILE_ASSOCIATIONS_FEATURE.ja.md) - ファイルの種類ごとに、開く・表示する・編集するプログラム
- [アプリケーションを選んで開く](OPEN_WITH_FEATURE.ja.md) - 今回どのアプリケーションでファイルを開くかを選ぶ
- [追加の Python ライブラリ](PYTHON_PACKAGES_FEATURE.ja.md) - `config.py` や拡張機能が必要とするライブラリを `~/.xefm/requirements.txt` から
- [ログ](LOGGING_FEATURE.ja.md) - ログペインとログファイル

### 連携と拡張機能
- [拡張パッケージ](EXTENSIONS_FEATURE.ja.md) - アクション、テーマ、ソート順、シンタックスハイライトなどを追加するパッケージのインストール、アップグレード、作成。公式のパッケージは [crftwr/xefm-extensions](https://github.com/crftwr/xefm-extensions) に、その他は [wiki](https://github.com/crftwr/xefm/wiki/Extensions) にあります
- [AI エージェント向け XeFM スキル](AGENT_SKILL_FEATURE.ja.md) - AI コーディングエージェントに設定の編集や拡張機能の作成を任せる
- [使い捨てのホームで XeFM を試す](TRY_FEATURE.ja.md) - `xefm try`：一時的なホームで XeFM を実行し、自分の `~/.xefm` には手を付けない
- [外部プログラム](EXTERNAL_PROGRAMS_FEATURE.ja.md) - 独自のプログラムとの連携（VSCode のレシピを含む）
- [外部ターミナル](EXTERNAL_TERMINAL_FEATURE.ja.md) - デスクトップアプリがサブシェルやターミナルのプログラムのために開くターミナルのウィンドウ
- [仮想フォルダー](VIRTUAL_FOLDERS_FEATURE.ja.md) - レジストリ、データベース、API など、ディレクトリではないものをディレクトリのようにブラウズ

---

## キーボードショートカットのリファレンス

**リファレンスは XeFM の中にあります。** `F1` を押すとヘルプダイアログが開きます。ヘルプは設定から実際に作られたキーマップからアクションごとに生成されるので、キーの実際の動作とずれることはありません。メニューバーにも、各項目の横に同じキーが表示されます。

そのため、このガイドではキーではなく**アクション**の名前（`copy_files`、`find_files`、`jump_to_path`）で説明しています。キーは選んだ[キーマッププリセット](KEYMAP_PRESETS_FEATURE.ja.md)によって変わるからです。すべてのプリセットのすべてのキーは、[キーマッププリセット](KEYMAP_PRESETS_FEATURE.ja.md#すべてのキーの一覧)に並べて載せています。キーを変えるには、`~/.xefm/config.py` の `KEY_BINDINGS` にアクションを追加します。

- どのキーの組み合わせがどこで使えるか（ターミナルはウィンドウが送れるものをすべて送れるわけではありません）、どれがターミナルやエディターに先に取られるか：[キーバインド](KEY_BINDINGS_FEATURE.ja.md)
- ビューアーやダイアログの中だけのアクションと、その割り当て直し方：[カスタマイズ](CUSTOMIZATION_FEATURE.ja.md)

### キーバインドのカスタマイズ

すべてのキーバインドは設定ファイル（`~/.xefm/config.py`）でカスタマイズできます。拡張されたキーバインドのしくみは、次のものに対応しています。

- **修飾キー**：Shift、Control、Alt、Command（例：'Shift-UP'、'Command-Q'）
- **1 つのアクションに複数のキー**：同じアクションに複数のキーを割り当て可能
- **選択の条件**：ファイルの選択状態に応じて、アクションを使える状況を制御
- **大文字と小文字を区別しないキー**：特殊キーの名前（`ENTER`）と英字だけのキー（`q` = `Q`）は同じ物理キーに割り当てられます。Shift を押した方には `Shift-Q` を使います

**例：**
```python
KEY_BINDINGS = {
    'page_up': ['PAGE_UP', 'Shift-UP'],  # Two ways to page up
    'cursor_up': ['UP', 'k'],            # add a vim-style alternative
    'delete_files': {
        'keys': ['K', 'DELETE'],
        'selection': 'required'          # Only when files selected
    },
}
```

詳しくは[設定](#カスタマイズ)のセクションと[キーバインド](KEY_BINDINGS_FEATURE.ja.md)を参照してください。

---

## ヒントとコツ

### 効率よく使うためのヒント
1. **Tab をよく使う**：ペインのすばやい切り替えが効率の鍵です
2. **複数選択を覚える**：`toggle_select_down` で複数のファイルを選択してから操作します
3. **インクリメンタルサーチを使う**：`isearch`（**View → Find…**）を実行して入力を始めると、ファイルが絞り込まれます
4. **キーバインドをカスタマイズする**：XeFM を自分の作業の流れに合わせます
5. **お気に入りを使う**：よく開くディレクトリをブックマークしておきます

### 作業の例

#### ファイルの整理
1. 左ペインで移動元のディレクトリに移動します
2. 右ペインで移動先に移動します
3. `toggle_select_down` でファイルを選択します
4. **File → Copy to Other Pane** でコピー、**File → Move to Other Pane** で移動します

#### 開発の作業
1. プロジェクトのディレクトリをお気に入りに登録します
2. git の操作には外部プログラムを使います
3. `edit_file`（**File → Open With ▸ Text Editor**）でファイルを編集します
4. 内容検索でコードを探します

#### S3 のデータ管理
1. 左ペインでローカルのディレクトリに移動します
2. 右ペインで s3://bucket/path に移動します
3. ローカルとクラウドのストレージの間でファイルをコピーします
4. S3 上の設定ファイルを直接編集します

---

このユーザーガイドでは、XeFM を効果的に使うためのあらゆる側面を網羅しています。技術的な実装の詳細は、`doc/dev/` ディレクトリの開発者向けドキュメントを参照してください。
