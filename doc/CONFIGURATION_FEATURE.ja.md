# XeFM の設定

[English](CONFIGURATION_FEATURE.md) \| 日本語

## 概要

XeFM は Python で書かれた設定ファイルでカスタマイズします。初回起動時に XeFM がテンプレートからこのファイルを作成するので、それを編集して外観、動作、キーバインド、外部プログラムとの連携を変更します。以下で紹介するオプションはすべて設定クラスの実際の属性です。正式な定義と詳しいコメントは、テンプレートである `xefm/_config.py` を参照してください。

## 設定ファイルの場所

XeFM は設定を次の場所に保存します。

```
~/.xefm/config.py
```

初回起動時に、XeFM はこのファイルを既定の設定で作成します。どのテキストエディターでも編集できます。

`~/.xefm/extensions/` に置いた Python モジュールは、このファイルから import できます。[自分のモジュール](CUSTOMIZATION_FEATURE.ja.md#自分のモジュールxefmextensions)を参照してください。

## クイックスタート

```bash
# View it
cat ~/.xefm/config.py

# Edit it
vim ~/.xefm/config.py        # or: nano / code / your editor of choice
```

変更は次に XeFM を起動したときに反映されます。

## 設定の編集と再読み込み

XeFM から離れずに設定を編集して適用することもできます。どちらのアクションも **Tools** メニューにあります（既定ではどちらもキーに割り当てられていません）。

- **Edit Configuration…**（設定ファイルを編集）は、設定した `TEXT_EDITOR` で `~/.xefm/config.py` を開きます。ファイルがなければ、先にテンプレートから作成します。ターミナルのエディター（`vim` など）なら、保存して終了したときに XeFM が自動で再読み込みします。GUI のエディター（VS Code など）では編集の終わりを XeFM が判断できないので、保存してから **Reload Configuration** を実行してください。
- **Reload Configuration**（設定を再読み込み）は、エディターを開かずに `~/.xefm/config.py` をディスクから読み直して適用します。別のウィンドウでファイルを編集しているときに便利です。

どちらかのアクションをキーに割り当てるには、`KEY_BINDINGS` に追加します。

```python
KEY_BINDINGS = {
    'edit_config':   ['Y'],
    'reload_config': ['Ctrl-Y'],
}
```

再読み込みは、キーバインド、ファイルの関連付け、外部プログラム、お気に入り、確認メッセージ、テキストエディター／差分ツールの設定に**その場で**反映されます。テーマとポストエフェクト、フォント（デスクトップモード）、ペインの分割比とログの高さの比率、ファイル監視の間隔は起動時に一度だけ読み込まれるので、完全に反映されるのは**次回の起動時**です。再読み込みのたびに、XeFM はそのことをログに残します。

編集した設定に Python のエラーがあっても、XeFM はクラッシュせず、エラーをログに記録して内蔵の既定に戻ります。範囲外の値はそのまま適用されますが、`Config warning:` としてログに記録されます。

## 外観

### フォント（GUI／デスクトップモードのみ）

これらはデスクトップモード（macOS／Windows ネイティブのバックエンド）で有効です。ターミナルのバックエンドはターミナルのフォントを使い、これらの設定項目を無視します。

```python
UI_FONT_NAME  = None   # proportional face for names/labels (None = bundled/OS default)
MONO_FONT_NAME = None  # monospaced face for the aligned grid (None = bundled default)
FONT_SIZE      = 12    # point size applied to BOTH faces (8-72)
```

`MONO_FONT_NAME` には等幅フォントを指定する必要があります。画面のグリッドの列幅は、このフォントから決まります。行の高さは 2 つのフォントのどちらも収まる高さになり、どちらのフォントの文字も同じベースラインに並ぶので、どの組み合わせでも行の中で揃います。`UI_FONT_NAME` のフォントが等幅フォントより背が高いと、行が高くなります。デスクトップモードでは、`Cmd-+`／`Cmd--` で `FONT_SIZE` をその場で変更することもできます。

### ターミナルのフォントが全角幅で描く記号（上級者向け）

ターミナルのフォントによっては（HackGen など）、`○ □ ★ ●` のような記号を全角幅で描きます。Unicode ではこれらの幅は「曖昧」とされており、ターミナルは各文字のあとに 1 桁しか進まないので、記号が次の文字に重なってしまいます。そうした文字を `WIDE_CHARS` に指定すると、XeFM はそれぞれに 2 桁を割り当てます。

```python
WIDE_CHARS = '○□★●'   # a string, or a list of single characters
```

- ターミナルの曖昧幅の設定は、既定の**半角（narrow）** のままにしてください。全角にすると、XeFM の枠、スクロールバー、影が崩れます。これらも曖昧幅の文字で描かれているためです。
- 指定するのは、使っているフォントが実際に全角幅で描く記号だけにしてください。ここに指定した文字をフォントが半角幅で描くと、そのあとに空白の桁が入ります。
- 罫線文字（`─ │ ┌` など）は指定しないでください。枠がばらばらになります。
- ASCII 文字と、もともと 2 桁の文字（漢字、かな）はそのまま扱われ、どの文字を無視したかがログに記録されます。
- この設定項目は起動時に読み込まれます。変更したら XeFM を再起動してください。設定の再読み込みでは反映されません。

この設定項目は生成される `config.py` には含まれていないので、自分で行を追加してください。PuiKit 1.12 以降が必要です。それより古い PuiKit では警告がログに記録され、設定は無視されます。

### テーマ／色

XeFM には内蔵テーマ（Dark+、Monokai、Dracula、Nord、Solarized、Gruvbox Dark、Light+、Solarized Light）が付属しています。実行中に **View → Theme** または **View → Theme ▸ Next Theme** で切り替えられます。XeFM は Dark+ で起動し、最後に使ったテーマを再起動後も覚えています。`COLOR_SCHEME` のような文字列の設定項目はありません。代わりに、名前を付けた独自のテーマを登録します。

```python
THEMES = {
    'Ocean': {                    # builds on Dark+ by default
        'accent':     (0, 120, 160),
        'background': (18, 26, 32),
    },
}
```

テーマのキーの完全なリファレンス（GUI で使える、省略可能な CRT／蛍光体風の `post_effect` を含む）は[配色](COLOR_SCHEMES_FEATURE.ja.md)を参照してください。

## 表示とレイアウト

```python
SHOW_HIDDEN_FILES       = False  # show hidden files (toggle at runtime with toggle_hidden)
DEFAULT_LEFT_PANE_RATIO = 0.5    # left pane width as a ratio (0.1 - 0.9)
DEFAULT_LOG_HEIGHT_RATIO = 0.25  # log pane height as a ratio (0.1 - 0.5)
DATE_FORMAT             = 'short'  # 'short' (YY-MM-DD HH:mm) or 'full' (YYYY-MM-DD HH:mm:ss)
SEPARATE_EXTENSIONS     = True   # show extensions in their own column
MAX_EXTENSION_LENGTH    = 5      # longer extensions stay with the filename
```

実行中は `[`／`]` でペインの分割位置を、`{`／`}` でログペインの高さを調整できます。`DEFAULT_LOG_HEIGHT_RATIO` は、ドラッグや `{`／`}` で調整していない間のログペインの高さを決めます。手で設定した高さは再起動後も保持され、設定より優先されます。`reset_log_height` アクションで設定した既定に戻ります（高さも再び設定に従うようになります）。レイアウトの比率は起動時に読み込まれるので、設定で変更したものは次の起動時に反映されます。

`DATE_FORMAT` は、ファイルペインでの更新日時の表示形式を選びます。`'short'` は `YY-MM-DD HH:mm`（コンパクトで秒なし）、`'full'` は `YYYY-MM-DD HH:mm:ss`（4 桁の年と秒あり）です。どちらも ISO-8601 の順序で、長い形式では日付の列が自動で広がります。設定項目を編集したあと、**Tools → Reload Configuration** を実行すれば再起動せずに反映されます。

## インクリメンタルサーチ（Migemo）

```python
MIGEMO_SEARCH    = True  # add Migemo (romaji -> Japanese) matches to incremental search
MIGEMO_MIN_LENGTH = 3    # shortest pattern handed to Migemo
```

Migemo を有効にすると、インクリメンタルサーチ（ファイルペイン、テキスト／差分ビューアー、絞り込みリストのダイアログ）で、入力したローマ字から日本語の名前にもマッチします。`kensaku` で `検索` が見つかります。通常のマッチングも常に行われ、glob パターン（`* ? [`）はワイルドカードとしての動作をそのまま保ち、`MIGEMO_MIN_LENGTH` より短いパターンには Migemo を使いません。[Migemo 検索](MIGEMO_SEARCH_FEATURE.ja.md)を参照してください。

## テキストビューアーのエンコーディング

```python
TEXT_ENCODINGS = ['utf-8', 'cp932', 'euc-jp', 'iso-2022-jp', 'latin-1']
```

テキストビューアーでエンコーディングを手動で選ぶとき（ビューアーの `change_encoding`）に表示される候補です。自動判定は内蔵されていて、常にそれが既定です。このリストは、判定がファイルのエンコーディングを誤ったときのための選択肢を決めるだけです。[Python のコーデック名](https://docs.python.org/3/library/codecs.html#standard-encodings)ならどれでも使えます。[テキストのエンコーディング](TEXT_ENCODING_FEATURE.ja.md)を参照してください。

## ソート

```python
DEFAULT_SORT_MODE    = 'filename'  # 'filename', 'extension', 'size', 'timestamp'
DEFAULT_SORT_REVERSE = False
```

実行中は、**View → Sort By ▸**、ソートダイアログ（`sort`）、`quick_sort_*` アクションでソートを変更できます。

名前のソートは**自然順**（英数字順）です。名前に含まれる数字は数値として比較されるので、`file2` は `file10` より前に並び、先頭にゼロが付いた名前（`Report001`、`Report010`）も期待どおりの順になります。大文字と小文字は区別せず、`'filename'` のソートモードでは常に適用され、無効にはできません。`'size'` と `'timestamp'` のモードには影響しません。ソートモードにかかわらず、ディレクトリは常にファイルより前に表示されます。

## 確認

```python
CONFIRM_DELETE          = True   # before deleting files/directories
CONFIRM_QUIT            = True   # before quitting XeFM
CONFIRM_COPY            = True   # before copying
CONFIRM_MOVE            = True   # before moving
CONFIRM_EXTRACT_ARCHIVE = True   # before extracting an archive
CONFIRM_ARCHIVE_CREATE  = True   # before creating an archive
```

## キーバインド

```python
KEY_BINDINGS = {
    'quit': ['Q'],
    'help': ['F1'],
    'toggle_hidden': ['.'],
    # ... many more actions
}
```

各アクションはキーのリストに対応付けられます。キーには 1 文字（`'a'`、`'Q'`）か特殊キーの名前（`'HOME'`、`'END'`、`'F1'`…`'F12'`、`'UP'`、`'DELETE'` など）を使えます。英字のキーは**大文字と小文字を区別しません**。`'q'` だけと `'Q'` だけは*同じ*物理キーに割り当てられます（既定のテンプレートでは、たまたま `'Q'`、`'C'`、`'M'`、`'K'` のように大文字で書かれています）。Shift を押した大文字のキーだけを割り当てるには、`Shift-<letter>` を使います（例：`'Shift-F'`）。`'?'` や `'/'` のような英字以外の文字は大文字と小文字を区別したままです。

一部のアクションでは、選択状態を考慮した拡張形式を使います。

```python
KEY_BINDINGS = {
    'copy_files':       {'keys': ['C'], 'selection': 'required'},
    'create_directory': {'keys': ['M'], 'selection': 'none'},
}
```

選択モードは `'any'`（既定）、`'required'`（選択項目があるときのみ）、`'none'`（選択項目がないときのみ）です。アクションの一覧は[キーバインド](KEY_BINDINGS_FEATURE.ja.md)を参照してください。各アクションに最初から割り当てられているキーはキーマッププリセットによって異なります。[キーマッププリセット](KEYMAP_PRESETS_FEATURE.ja.md#すべてのキーの一覧)を参照してください。

モーダルなビューアーの*中*のキーも名前の付いたアクションで、同じ方法で割り当て直せます。キーに自分の関数を割り当てることもできます。どちらも[カスタマイズ](CUSTOMIZATION_FEATURE.ja.md)で説明しています。

## カスタマイズ

```python
ACTIONS = {}       # your own functions, bound by name in KEY_BINDINGS
EVENT_HOOKS = {}   # your own functions, run when something happens
```

この設定ファイルをスクリプトの場として使うための API です。ペインを操作する Python 関数をキーに割り当てたり、起動時、終了時、ディレクトリの移動時、ファイルを開いたときに関数を実行したりできます。`ACTIONS` は安定版、`EVENT_HOOKS` はまだプレビューです。どの部分がどちらにあたるかは[カスタマイズ](CUSTOMIZATION_FEATURE.ja.md)を参照してください。

## お気に入り

```python
FAVORITES = [
    {'name': 'Home', 'path': '~'},
    {'name': 'Documents', 'path': '~/Documents'},
    {'name': 'Projects', 'path': '~/Projects'},
]
```

お気に入りは **Go → Go to Favorite…**（`favorites`）で開きます。[ナビゲーションダイアログ](NAVIGATION_DIALOGS_FEATURE.ja.md)を参照してください。

## ドライブの場所

```python
DRIVE_LOCATIONS = None   # built-in: Home, Root, Documents, Downloads, Desktop
```

ドライブダイアログ（**Go → Drives…**）の上部に並ぶ固定の場所です。リストを設定すると独自の場所に置き換わり、`[]` にするとマウント済みのボリュームだけが表示されます。

```python
DRIVE_LOCATIONS = [
    {'name': 'Work', 'path': '~/work'},
    {'name': 'NAS', 'path': 'ssh://nas/'},
]
```

[ナビゲーションダイアログ](NAVIGATION_DIALOGS_FEATURE.ja.md)を参照してください。

## 履歴とログ

```python
MAX_HISTORY_ENTRIES = 100    # directory-history entries kept
MAX_LOG_MESSAGES    = 1000   # messages retained in the log pane
```

[ログ](LOGGING_FEATURE.ja.md)を参照してください。

## 進捗のアニメーション

```python
PROGRESS_ANIMATION_PATTERN = 'spinner'  # spinner, dots, progress, bounce, pulse, wave, clock, arrow
PROGRESS_ANIMATION_SPEED   = 0.2        # frame interval in seconds
```

## 外部ツール

```python
# Editor launched by edit_file. String ('vim') or list (['code', '--wait']).
# Defaults are chosen per backend: 'vim' in the terminal, 'code' in desktop mode.
TEXT_EDITOR = 'code' if is_desktop_mode() else 'vim'

# Diff tool launched from the diff viewers. Same string/list forms.
TEXT_DIFF   = ['code', '--diff'] if is_desktop_mode() else 'vimdiff'
```

### 外部プログラム

```python
PROGRAMS = [
    {'name': 'Git Status', 'command': ['git', 'status']},
    {'name': 'Disk Usage', 'command': ['du', '-sh', '*']},
]
```

各エントリは `name`、`command`（リストまたは文字列）、省略可能な `options`（`vim` や `less` のような全画面のプログラムには `{'terminal': True}` など）を持ちます。プログラムは **Tools → External Programs…**（`programs`）で開きます。[外部プログラム](EXTERNAL_PROGRAMS_FEATURE.ja.md)を参照してください。

### ファイルの関連付け

```python
FILE_ASSOCIATIONS = [
    {'pattern': '*.pdf', 'open|view': ['open', '-a', 'Preview']},
    {'pattern': ['*.jpg', '*.jpeg', '*.png', '*.gif'], 'open|view': ['open', '-a', 'Preview']},
]
```

各エントリは `pattern`（fnmatch の文字列 1 つ、またはそのリスト）と、`open`／`view`／`edit`（またはそれらをまとめた `open|view`）のうち 1 つ以上を持ちます。コマンドはリストか文字列です。[ファイルの関連付け](FILE_ASSOCIATIONS_FEATURE.ja.md)を参照してください。

## キャッシュ

```python
S3_CACHE_TTL          = 60    # S3 directory-listing cache TTL (seconds)
SSH_CACHE_TTL         = 30    # SSH/SFTP cache TTL for successful results (seconds)
SSH_CACHE_ERROR_TTL   = 300   # SSH/SFTP cache TTL for cached errors (seconds)
ARCHIVE_CACHE_MAX_OPEN = 5    # idle archives kept open at once
ARCHIVE_CACHE_TTL      = 300  # how long an idle remote archive's download is kept (seconds)
```

## ファイル監視

ディスク上でディレクトリが変更されたときに、ペインを自動で再読み込みします。

```python
FILE_MONITORING_ENABLED                  = True  # enable/disable auto-reload
FILE_MONITORING_COALESCE_DELAY_MS        = 200   # event coalescing window (ms)
FILE_MONITORING_MAX_RELOADS_PER_SECOND   = 5     # rate limit
FILE_MONITORING_FALLBACK_POLL_INTERVAL_S = 5     # polling interval when native events are unavailable (s)
```

[ファイル監視](FILE_MONITORING_FEATURE.ja.md)を参照してください。

## バックエンドとウィンドウ

描画のバックエンドは設定項目では**ありません**。コマンドラインの `--backend` フラグ（既定の `tui`、`curses`、`gui`／`macos`）だけで選びます。デスクトップモードでは、ウィンドウのサイズと位置が実行をまたいで自動的に記憶されます。ウィンドウの位置やサイズを指定する設定キーはありません。[デスクトップモードガイド](DESKTOP_MODE_GUIDE.ja.md)を参照してください。

## 設定例

### 素早く作業する（確認を減らす）

```python
SHOW_HIDDEN_FILES = False
CONFIRM_COPY = False
CONFIRM_MOVE = False
MAX_LOG_MESSAGES = 500
```

### パワーユーザー向け

```python
DATE_FORMAT = 'full'
SHOW_HIDDEN_FILES = True
DEFAULT_LEFT_PANE_RATIO = 0.5
DEFAULT_LOG_HEIGHT_RATIO = 0.3
MAX_LOG_MESSAGES = 2000
PROGRESS_ANIMATION_PATTERN = 'wave'
```

### デスクトップの外観（macOS）

```python
MONO_FONT_NAME = 'Menlo'
UI_FONT_NAME   = 'Helvetica Neue'
FONT_SIZE      = 14
TEXT_EDITOR    = 'code'
```

## トラブルシューティング

### 変更が反映されない
1. ファイルのパスを確認します：`~/.xefm/config.py`
2. Python の構文エラーがないか確認します
3. XeFM を再起動します

### 編集後に XeFM が起動しない
構文エラー（引用符、カンマ、括弧の抜け）の可能性が高いです。既定に戻すには次のようにします。

```bash
rm ~/.xefm/config.py   # XeFM recreates it from the template on next run
```

### オプションが見つからない
`xefm/_config.py` を確認してください。使えるすべての設定項目が、詳しいコメント付きで正式に一覧されています。

## 関連ドキュメント

- [配色](COLOR_SCHEMES_FEATURE.ja.md) - テーマと色
- [ログ](LOGGING_FEATURE.ja.md) - ログの設定
- [外部プログラム](EXTERNAL_PROGRAMS_FEATURE.ja.md) - 外部プログラムとの連携
- [ファイルの関連付け](FILE_ASSOCIATIONS_FEATURE.ja.md) - ファイルの種類の関連付け
- [ファイル監視](FILE_MONITORING_FEATURE.ja.md) - ディレクトリの自動再読み込み
- [キーバインド](KEY_BINDINGS_FEATURE.ja.md) - キーバインドの設定
- [カスタマイズ](CUSTOMIZATION_FEATURE.ja.md) - 独自のアクションとイベントフック
- [デスクトップモード](DESKTOP_MODE_GUIDE.ja.md) - デスクトップモード（macOS）
- [XeFM ユーザーガイド](XEFM_USER_GUIDE.ja.md) - 完全なユーザーガイド
