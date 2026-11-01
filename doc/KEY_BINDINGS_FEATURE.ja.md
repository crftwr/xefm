# キーバインド

[English](KEY_BINDINGS_FEATURE.md) \| 日本語

## 概要

XeFM のキーバインドの仕組みでは、アプリケーションのすべてのアクションのキーボードショートカットをカスタマイズできます。次のものに対応しています。

- **1 文字のキー**：'q'、'a'、'?' のような単純なキー
- **キー名**：'ENTER'、'UP'、'PAGE_DOWN'、'F10' のような、文字を持たないキー
- **名前で書く記号**：'SEMICOLON'、'BACKQUOTE'、'LEFT_BRACKET'
- **修飾キーの組み合わせ**：'Shift-Down'、'Command-Q' のような修飾キー付きのキー
- **1 つのアクションに複数のキー**：同じアクションにいくつものキーを割り当てられます
- **選択の条件**：ファイルの選択状態に応じて、アクションを使えるタイミングを制御できます

## キー表現の書式

### 1 文字のキー

もっとも単純な形で、1 文字だけを書きます。

```python
'quit': ['Q']
'context_menu_dir': ['?']
'toggle_hidden': ['.']
```

**重要な動作：**

- **アルファベットは、大文字で書いても小文字で書いても同じキーバインドです。** `'a'` も `'A'` も、修飾キーなしの A キーを意味します。
- **大文字で書くことは Shift を押すことと同じではありません。** `'Q'` と書いたキーバインドは、Shift+Q を押したときには発動*しません*。あくまで Shift なしのキーです。Shift 付きのキーを意味するときは `'Shift-Q'` と書いてください。
- **記号と数字は、そのキーが入力する文字そのものです。** そのため `?` と `/` は、物理的には同じキーでも別のキーとして扱われます。

例：
```python
'quit': ['Q']              # the Q key; writing 'q' would mean the same
'context_menu_dir': ['?']  # the '?' glyph, not the '/' key it shares
'isearch': ['F']           # F on its own
'find_files': ['Shift-F']  # Shift+F — a different binding from 'F'
```

### キー名

文字を持たないキーは名前で書きます。

```python
'move_up': ['UP']
'page_up': ['PAGE_UP']
'confirm': ['ENTER']
'cancel': ['ESCAPE']
'menu': ['F10']
```

**これがすべての一覧です。** ここにない名前は受け付けられません。XeFM は `Unknown key in expression: ...` とログに記録し、そのキーバインドは発動しません。

| グループ | 名前 |
|---|---|
| 移動 | `UP`、`DOWN`、`LEFT`、`RIGHT`、`HOME`、`END`、`PAGE_UP`（または `PAGEUP`）、`PAGE_DOWN`（または `PAGEDOWN`） |
| 編集 | `ENTER`（または `RETURN`）、`ESCAPE`（または `ESC`）、`TAB`、`BACKSPACE`、`DELETE`（または `DEL`）、`INSERT`、`SPACE` |
| ファンクションキー | `F1` から `F12` |
| メニューキー | `APPS` — PC キーボードのコンテキストメニューキーです。Windows（デスクトップアプリとターミナル）、macOS での PC キーボード、Web バックエンドから届きます。POSIX のターミナルはこのキーに対して何も送りません。`Shift-APPS` は別のキーバインドです。 |
| Alt の単独押し | 単独の `ALT` — 間に何も押さずに Alt を押して離す操作です。Windows のターミナルからしか届かず、そこではメニューバーを開きます。*接頭辞*として書く場合（`Alt-X`）は修飾キーになります。 |

名前は**大文字・小文字を区別しません**。`'ENTER'`、`'enter'`、`'Enter'` のいずれも使えます。

### 名前で書く記号

記号は文字そのもの（`'-'`、`'['`、`';'`）でも、名前でも書けます。名前のほうが設定ファイルで読みやすくなります。

| 名前 | キー | `Shift-` で得られるもの |
|---|---|---|
| `MINUS` | `-` | `_` |
| `EQUAL`、`EQUALS` | `=` | `+` |
| `LEFT_BRACKET` | `[` | `{` |
| `RIGHT_BRACKET` | `]` | `}` |
| `BACKSLASH` | `\` | `\|` |
| `SEMICOLON` | `;` | `:` |
| `QUOTE`、`APOSTROPHE` | `'` | `"` |
| `COMMA` | `,` | `<` |
| `PERIOD`、`DOT` | `.` | `>` |
| `SLASH` | `/` | `?` |
| `GRAVE`、`BACKTICK`、`BACKQUOTE` | `` ` `` | `~` |

記号や数字のキーに `Shift-` を付けると、US 配列でそのキーが実際に入力する文字になります。`'Shift-EQUAL'` は `+`、`'Shift-1'` は `!`、`'Shift-BACKQUOTE'` は `~` です。そのため、どちらの書き方でも同じキーバインドになります。

```python
'go_root': ['BACKSLASH']          # same as ['\\']
'adjust_log_up': ['Shift-LEFT_BRACKET']   # same as ['{']
```

US 以外の配列では、Shift 付きの名前ではなく、キーボードが入力する文字そのものを書いてください。

### 修飾キーの組み合わせ

メインのキーの前に、ハイフンで区切って修飾キーを書きます。

```python
'page_up': ['PAGE_UP', 'Shift-UP']
'page_down': ['PAGE_DOWN', 'Shift-DOWN']
'jump_to_top': ['Command-UP']
'jump_to_bottom': ['Command-DOWN']
'delete_files': ['DELETE', 'Command-Backspace']
```

**使える修飾キー：**
- `Shift` - Shift キー
- `Control` または `Ctrl` - Control キー
- `Alt` または `Option` - Alt／Option キー
- `Command` または `Cmd` - Command キー（macOS）

**修飾キーの規則：**
- 修飾キーは**大文字・小文字を区別しません**。`'Shift'`、`'SHIFT'`、`'shift'` のいずれも使えます
- 修飾キーの**順序は関係ありません**。`'Command-Shift-X'` と `'Shift-Command-X'` は同じです
- **複数の修飾キー**を組み合わせられます：`'Command-Shift-X'`、`'Control-Alt-Delete'`

### キーシーケンス

キーバインドには、続けて押す複数のキーも指定できます。キーをスペースで区切って書きます。

```python
'go_root': ['g r'],          # g, then r
'cursor_top': ['g g'],       # g twice
'toggle_hidden': ['z Shift-H'],
```

シーケンスの途中では、それまでに押したキーがステータスバーに表示されます（`g …`）。`Esc` で取り消せます。どのシーケンスの続きでもないキーを押すと、シーケンスは終わり、そのキーは本来の動作をします。シーケンスはファイル一覧とテキストビューアーで使えます（テキストビューアーでは途中のキーは表示されません）。

あるキーバインドが別のキーバインドの先頭になっている場合（`g` 単独と `g g`）、XeFM は次のキーを待ちます。どれだけ待つかは `config.py` の `KEY_SEQUENCE_TIMEOUT` で決まります。

```python
KEY_SEQUENCE_TIMEOUT = 1.0    # seconds; then g runs on its own (the default)
KEY_SEQUENCE_TIMEOUT = None   # no timeout: g runs when the next key is not g
```

シーケンスの開始にしか使われず、単独では割り当てられていないキー（この例で `g g` と `g r` だけが使っている場合の `g`）は、それだけでは何も実行せず、タイムアウトがなければただ待ち続けます。

### キーマッププリセット

すべてのキーは**プリセット**（完全なキーマップ）から来ています。AFX 風、Orthodox、OS ネイティブ、Vim 風のいずれかです。XeFM は初回起動時にどれを使うか尋ね、**Tools → Advanced → Keymap…**（または `config.py` の `KEY_PRESET`）で切り替えられます。`KEY_BINDINGS` には自分の変更だけを書き、各エントリはどのプリセットでもそのアクションのキーを置き換えます。自分で割り当てたキーは、プリセットがそのキーを割り当てていたアクションから外されるので、そちらのアクションを空にする必要はありません。[キーマッププリセット](KEYMAP_PRESETS_FEATURE.ja.md#自分のキーバインドが優先される)を参照してください。

### ターミナルで送れるキー

同じ XeFM がデスクトップアプリとしてもターミナルでも動きますが、ターミナルはウィンドウが受け取れるすべての組み合わせを送れるわけではありません。そのため各プリセットは **1 つの共通の表**をもとにしていて、その中のキーはすべて macOS アプリ、Windows アプリ、どのターミナルでも XeFM に届きます。それに加えて、デスクトップのプラットフォームがその操作を完全に持っている場合に限り、デスクトップアプリでキーが追加されます。ターミナルでは共通の表がキーマップのすべてです。どのプリセットがどのデスクトップアプリでどのキーを追加するかは、[キーマッププリセット](KEYMAP_PRESETS_FEATURE.ja.md#すべてのキーの一覧)（*macOS app*、*Windows app* で始まる行）にあります。

ターミナルが送れないものと、それらの組み合わせが共通の表にない理由：

| 組み合わせ | 理由 |
|---|---|
| `Command-<key>` | Command キーをエンコードするターミナルはまったくありません。Terminal.app も iTerm2 も VS Code のターミナルもそうです。 |
| `Ctrl-Shift-<letter>` | ターミナルは Ctrl+文字を 1 バイトの制御コードとして送るので、Shift を入れる余地がありません。そのためターミナルでは `'Ctrl-Shift-C'` は `'Ctrl-C'` *そのもの*です。（Windows のコンソールは例外ですが、1 つのコンソールでしか動かないキーバインドは既定値にはしません。） |
| `Shift-<printable>` | 同じ問題の裏返しです。ターミナルは文字を報告しますが、Shift+Space が入力する文字はスペースです。それでも `select_range` は `Shift-Space` を使います。これは表の中で唯一の意図的な例外です。Shift はユーザーが最初から知っている範囲選択の操作で、ターミナルが送れるものの中には「範囲」を表すものがそもそもないからです。POSIX のターミナルでは、割り当てを変えるまでは 1 つの項目を切り替えます（普通の Space の役目）。 |
| `Ctrl-ENTER` | 同じ理由で、普通の `ENTER` と区別できません。 |
| `Alt-ENTER` | macOS のキーボードでは Option は文字入力と IME に使われ、Windows のターミナルは Alt+Enter を全画面表示に使います。 |
| `Ctrl-I`、`Ctrl-M`、`Ctrl-J`、`Ctrl-H`、`Ctrl-[` | これらのバイトはすでに Tab、Enter、Backspace、Escape *そのもの*です。 |

**名前の付いた**キーに付ける Shift と Ctrl は、どこでも問題ありません（`Ctrl-UP`、`Shift-DOWN`、`Ctrl-HOME`、`Shift-F3`）。ターミナルにはそれらを表すシーケンスがあるからです。そのため、キーマップ全体で頼れる組み合わせは**修飾キーが Ctrl だけの `Ctrl-<letter>`** ということになり、OS 寄りのアクションにはこれが使われています。`Ctrl-Space` もこの仲間です。ターミナルはこれを NUL バイトとして送り、PuiKit がそれをデコードし、両方のコンソールもネイティブに報告します。検索バーでファイルにマークを付けるのにこのキーを使っているのはそのためです。

### ホストが先に取るキー

さらに、XeFM を動かしているものが、XeFM に届く前にキーの組み合わせを取ってしまうことがあります。そうなっても何もログには残りません。XeFM にはキーが押されたことが伝わらないので、キーバインドは単に何もしません。知っておく価値があるもの：

- **Windows Terminal** は `Ctrl-Shift-P`（コマンドパレット）、`Ctrl-Shift-F`（検索）、`Ctrl-Shift-T`/`N`/`D`/`W`（タブ、ウィンドウ、ペイン）、`Ctrl-Shift-A`/`V`/`M`/`K`（すべて選択、貼り付け、マークモード、クリア）、`Ctrl-Shift-<arrow>`/`HOME`/`END`/`PAGE_UP`/`PAGE_DOWN`（スクロールバック）、`Ctrl-Shift-SPACE`、`Ctrl-Shift-TAB`、`Ctrl-Shift-<digit>`、`Ctrl-Alt-<digit>`、`Alt-ENTER`、`F11` を取ります。コピーの組み合わせ（`Ctrl-Shift-C`、`Ctrl-INSERT`、`ENTER`）は、*ターミナル上で*テキストが選択されているときだけ発動し、何も選択されていなければそのまま通過します。
- **VS Code の統合ターミナル**は、`terminal.integrated.commandsToSkipShell` に列挙されたコマンドを自分で処理し、シェルには送りません。その中にはコマンドパレット（`Cmd-Shift-P` / `Ctrl-Shift-P`）と Quick Open（Windows と Linux では `Ctrl-P` と `Ctrl-E`）が含まれます。そのため、`Ctrl-P` の `copy_paths` は既定値の中で唯一の意図的な妥協です。どのターミナルでも動きますが、VS Code のターミナルだけは例外で、代わりに Quick Open が開きます。そこでは割り当てを変えるか、**Edit → Copy Full Path(s)** を使ってください。
- **tmux と screen** は、自分のプレフィックスキー（`Ctrl-B`、`Ctrl-A`）とそのあとに入力されたものを取ります。

### 移動した既定値

これらは、キーマップが 1 つの共通の表になったとき（`help` はその後、コンテキストメニューのキーの場所を空けるため）に変わりました。プリセットができる前のことで、そのキーマップは現在の AFX 風なので、最後の列は AFX 風のキーです。それ以前の `config.py` にはまだ古いキーが残っているかもしれず、`KEY_BINDINGS` のエントリは常にプリセットより優先されます。XeFM はすでにある `KEY_BINDINGS` を書き換えないので、その行を手で編集するか、削除してプリセットのキーを使ってください。

| アクション | 以前 | 現在（AFX 風） |
|---|---|---|
| `open_with_os` | `Command-ENTER` / `Ctrl-ENTER`（Windows） | `Ctrl-O`。デスクトップアプリでは古い組み合わせも |
| `reveal_in_os` | `Alt-ENTER` / `Ctrl-Shift-E`（Windows） | `Ctrl-R` |
| `copy_names` | `Command-Shift-C` / `Ctrl-Shift-C`（Windows） | `Ctrl-N` |
| `copy_paths` | `Command-Shift-P` / `Ctrl-Shift-P`（Windows） | `Ctrl-P` |
| `copy_log_selection` | `Command-C`、`Ctrl-C` | 未割り当て（Edit メニュー）。`Ctrl-C` は現在 `clipboard_copy` で、ログで選択したテキストがあればそれを、なければファイルをコピーします |
| `toggle_select_up` | `Shift-SPACE` | 未割り当て。このキーは `select_range` に移りました（下記参照） |
| `isearch.toggle_select_down` | `Shift-DOWN` | `Ctrl-SPACE` |
| `isearch.toggle_select_up` | `Shift-UP` | 未割り当て |
| `help` | `?` | `F1`。`?`（Shift-/）は `context_menu_dir` に、`/` は `context_menu` に移りました |

`Shift-Space` は現在*範囲*を選択します（`select_range`）。これはほかのどのアプリケーションでも Shift が意味することです。それに合わせて、検索バーのマーク付けも Space の仲間に移りました。`Ctrl-Space` で現在の一致にマークを付けます。以前は `Shift-Down` / `Shift-Up` で、それでも動いていましたが、ログペインのスクロールキー（すぐ隣の画面での同じ組み合わせ）のように見えていました。既定のキーを失ったのは、どちらの場所でも*逆方向*のマーク付けです。どちらのアクションも登録されたままなので、`KEY_BINDINGS` に 1 行書けばどちらも復活させられます。検索バーには範囲選択のキーはありません。Enter で検索を抜けるとカーソルが一致した項目の上に残るので、あとは `Shift-Space` で行えます。

## 設定の書式

### シンプルな書式

選択の条件がないアクションには、キーのリストを使います。

```python
KEY_BINDINGS = {
    'quit': ['Q'],              # the Q key ('q' would mean the same)
    'help': ['F1'],             # a named key
    'context_menu_dir': ['?'],  # the '?' glyph
    'move_up': ['UP', 'k'],     # two keys for one action
    'move_down': ['DOWN', 'j'],
}
```

### 拡張書式

ファイルの選択を必要とする、または禁止するアクションには、辞書を使います。

```python
KEY_BINDINGS = {
    'delete_files': {
        'keys': ['K', 'DELETE'],
        'selection': 'required'  # Only available when files are selected
    },
    'create_directory': {
        'keys': ['M'],
        'selection': 'none'  # Only available when no files are selected
    },
}
```

リストだけの形式は `'selection': 'any'` の省略形にすぎないので、既存のリスト形式のキーバインドはそのまま動きます。

**選択の条件：**
- `'required'` - ファイルが選択されているときだけ使えるアクション
- `'none'` - ファイルが選択されていないときだけ使えるアクション
- `'any'` - 常に使えるアクション（既定）

**選択状態に応じる既定のアクション。** AFX 風では、次のファイル操作が `'required'` を使います（選択項目に対して動作するので、何も選択されていないときは隠れます）：`copy_files`、`move_files`、`copy_files_to`、`move_files_to`、`delete_files`、`create_archive`。`create_directory` は `'none'` を使うので、`move_files` と衝突なく同じキーを共有できます。XeFM は現在の選択状態に合うほうのアクションを選びます。キーは[キーマッププリセット](KEYMAP_PRESETS_FEATURE.ja.md#すべてのキーの一覧)にあります。ほかのどのアクションにも、同じ方法で `'selection'` の条件を加えられます。

### ビューアーのキー

テキスト、画像、差分、ディレクトリ差分の各ビューアーの*中で*使うキーも名前付きのアクションで、所属するビューアーの接頭辞が付いています（`text_viewer.page_down`、`file_diff.next_block`、`dir_diff.switch_side`）。ほかのアクションと同じく `KEY_BINDINGS` にエントリがなくても動くので、変えたいキーについてだけエントリを追加してください。

```python
KEY_BINDINGS = {
    'text_viewer.page_down': ['SPACE'],
    'file_diff.next_block': ['J'],
}
```

各画面は自分の名前だけを見るので、ビューアーのキーはファイル一覧のキーと衝突せずに同じキーを使えます。同じ接頭辞で、*共通の*アクション（`quit`、`help`、`isearch`、`edit_file`）を 1 つのビューアーだけに限定することもできます。`'file_diff.quit': ['X']` はそこだけを変え、ほかには影響しません。

ビューアーのアクションとその既定値の完全な一覧は、自分の Python 関数にキーを割り当てる方法とあわせて[カスタマイズ](CUSTOMIZATION_FEATURE.ja.md)にあります。

### 検索バーのキー

インクリメンタルサーチのバー（`isearch`）もそれ自体が 1 つの画面で、そのキーも同じようにその名前を持っています（`isearch.next_match`、`isearch.prev_match`、`isearch.toggle_select_down`、`isearch.toggle_select_up`、`isearch.select_matches`、`isearch.accept`、`isearch.cancel`）。割り当ての変更方法はビューアーとまったく同じです。既定値とそれぞれの動作は[カスタマイズ](CUSTOMIZATION_FEATURE.ja.md#インクリメンタルサーチバー)にあります。

この画面に特有の規則が 1 つあります。**文字を入力するキーは使えません。** 印字可能なキーはまずパターン入力欄に渡されます。そのおかげで、ファイル一覧でアクションが割り当てられているアルファベット、`?`、Space も、パターンには入力できるのです。そのため、`N` に割り当てた isearch のアクションは決して発動しません。XeFM は、そのキーバインドを黙って無効のままにせず、起動時にログペインでその旨を伝えます。`Shift-DOWN`、`Ctrl-N`、`F2` はどれも問題ありません。ここでは、Shift だけでは印字可能なキーをコマンドにできません。`Shift-Space` はスペースを入力するので、仮に範囲選択がこの画面に属するとしても、ファイル一覧の `select_range` のキーはここでは使えません（実際には属しません）。Enter を押して検索を抜ければ（カーソルは一致した項目の上に残ります）、`Shift-Space` がまた使えます。

### 名前が変わったアクション

いくつかのアクションには、よりわかりやすい名前が付けられました。**古い名前も引き続き使えます。** 古い名前でのキーバインドも同じアクションに解決され、XeFM は起動時に一度だけログペインでその旨を伝えます。都合のよいときに名前を変えてください。変えなくても何も壊れません。

| 古い名前 | 現在の名前 |
|---|---|
| `search` | `isearch` |
| `search_dialog` | `find_files` |
| `search_content` | `find_in_files` |
| `sort_menu` | `sort` |
| `drives_dialog` | `drives` |
| `connect_to_server` | `connect_server` |
| `rename_file` | `rename` |
| `select_file` | `toggle_select_down` |
| `select_file_up` | `toggle_select_up` |
| `select_all_files` | `toggle_select_files` |
| `select_all_items` | `toggle_select_items` |
| `image_zoom_in` | `image_viewer.zoom_in` |
| `image_zoom_out` | `image_viewer.zoom_out` |
| `image_zoom_reset` | `image_viewer.zoom_reset` |
| `image_next` | `image_viewer.next` |
| `image_prev` | `image_viewer.prev` |
| `image_scroll_up` | `image_viewer.pan_up` |
| `image_scroll_down` | `image_viewer.pan_down` |
| `image_scroll_left` | `image_viewer.pan_left` |
| `image_scroll_right` | `image_viewer.pan_right` |

ここには 3 種類の変更があります。画像ビューアーのアクションにはビューアーの接頭辞が付きました。これにより、接頭辞のない名前（`zoom_in`、`next`）は、いつか 2 つ目のビューアーが同じ機能を持ったときに共通のアクションとして使えるよう空けてあります。`image_scroll_*` の一群は `pan_*` になりました。これらのキーがもともとしていたのはパンだからです。そして、「search」と呼ばれていた無関係な 3 つのものには、どれがどれかわかる名前が付きました。`isearch` は入力に合わせて一致へ移動し、`find_files` は名前でファイルを検索し、`find_in_files` はファイルの中身を検索します。

テキストビューアーの `toggle_wrap`、`toggle_view_mode`、`change_encoding` には、あえて接頭辞を付けて**いません**。これらは 1 つのビューアーでの使い方ではなく機能そのものを表す名前だからです。差分ビューアーが明日エンコーディングの選択を持つかもしれません。接頭辞のない名前なら、2 つ目のビューアーが設定をまったく変えずにそれを使えるようになります。

設定にあるアクションの両方の書き方があると、現在の名前が優先され、古い名前は無視されます。そのため、1 つずつキーを移行しても安全です。

## 完全な例

設定の完全な例です。

```python
# ~/.xefm/config.py

class Config:
    KEY_BINDINGS = {
        # Basic navigation
        'quit': ['q'],                    # Matches both 'q' and 'Q'
        'help': ['F1'],                   # Function key F1
        'move_up': ['UP', 'k'],           # 'k' matches both 'k' and 'K'
        'move_down': ['DOWN', 'j'],       # 'j' matches both 'j' and 'J'
        'move_left': ['LEFT', 'h'],       # 'h' matches both 'h' and 'H'
        'move_right': ['RIGHT', 'l'],     # 'l' matches both 'l' and 'L'
        
        # Page navigation with modifiers
        'page_up': ['PAGE_UP', 'Shift-UP'],
        'page_down': ['PAGE_DOWN', 'Shift-DOWN'],
        'jump_to_top': ['HOME', 'Command-UP'],
        'jump_to_bottom': ['END', 'Command-DOWN'],
        
        # File operations with selection requirements
        'delete_files': {
            'keys': ['K', 'DELETE'],
            'selection': 'required'
        },
        'copy_files': {
            'keys': ['C'],                # 'C' and 'c' are equivalent
            'selection': 'required'
        },
        'create_directory': {
            'keys': ['M'],                # 'M' and 'm' are equivalent
            'selection': 'none'
        },
        # Use Shift modifier for uppercase-specific bindings
        'find_files': ['Shift-F'],     # Only matches Shift+F
    }
```

## 古い書式からの移行

既存の設定がある場合は、次のように移行します。

### 古い書式（移行前）

```python
KEY_BINDINGS = {
    'quit': ['q', 'Q'],           # Redundant uppercase
    'copy_files': ['c', 'C'],     # Redundant uppercase
    'move_up': ['UP', 'k'],
    'page_up': ['PPAGE'],         # Old special key name
}
```

### 新しい書式（移行後）

```python
KEY_BINDINGS = {
    'quit': ['Q'],                # one entry: 'Q' and 'q' are the same binding
    'copy_files': ['C'],          # likewise
    'move_up': ['UP', 'k'],       # a named key and a letter, both bound
    'page_up': ['PAGE_UP', 'Shift-UP'],  # the current name, plus a chord
}
```

**主な変更点：**
- **重複したアルファベットを削除する**：`'q'` と `'Q'` はまったく同じキーバインドなので、両方を書いても意味がありません。
- **Shift 付きのキーを意味するときは Shift 修飾キーを使う**：`'F'` ではなく `'Shift-F'` と書きます。トークンを大文字で書いても Shift にはなりません。
- **記号はそのキーが入力する文字のまま**：`?` と `/` は別のキーです。
- `PPAGE` → `PAGE_UP`、`NPAGE` → `PAGE_DOWN`。古い curses の名前は**受け付けられません**。まだそれらを使っている設定では、起動時に `Unknown key in expression` がログに記録され、そのキーバインドは何もしません。
- ほかのキー名は変わっていません。

## ヒントとおすすめの使い方

1. **意味のわかるキーを使う**：アクションにふさわしいキーを選びましょう
2. **代わりのキーを用意する**：重要なアクションには複数のキーを割り当てましょう
3. **修飾キーを活用する**：関連するアクションには修飾キーを使いましょう（例：ページ移動に Shift）
4. **キーバインドを試す**：キー同士が衝突していないか確かめましょう
5. **独自のキーバインドを記録する**：わかりにくい選択にはコメントで説明を付けましょう

## トラブルシューティング

### XeFM を起動せずにキーバインドを確かめる

`xefm keys` は、`config.py` と拡張パッケージを XeFM と同じように読み込み、キーマッププリセットを重ねたうえで、場所ごとにどのキーがどのアクションを実行するかを表示します。場所とは、ファイルリスト（`filer`）、各ビューアー、検索バー、各ピッカーです。ウィンドウは開かず、何も変更しません。

```bash
xefm keys F12             # F12 が何をするか（効く場所すべて）
xefm keys reload_config   # そのアクションを実行するキー
xefm keys                 # すべて
```

```text
config:  /Users/me/.xefm/config.py
keymap:  afx (chosen in XeFM), tui

[filer]
  F12  reload_config
```

決して発動しないキーバインドは `error:` の行で報告されます。XeFM が知らないキー名や修飾キー、XeFM のどこにもないアクション名（近い名前があればそれも示します）、形の崩れたエントリー、読み込みに失敗する `config.py` がこれに当たります。このとき終了ステータスは 1 です。`warning:` の行は、XeFM がログペインに出す `Config warning` のメッセージです。

- `--keymap NAME` で別のプリセットのキーを表示します。指定しないときは、XeFM で選んだプリセット、または `config.py` の `KEY_PRESET` です。
- `--backend gui` でデスクトップアプリのキーを表示します。OS ネイティブのプリセットでは、ターミナルとキーが異なります。
- `--context NAME` で一つの場所だけを表示します（例: `--context text_viewer`）。
- `--config FILE` で別の `config.py` を読みます（拡張は `~/.xefm` のものを使います）。

`same key as …` と付いた行は、そこに書かれたアクションとキーを共有しています。たいていの場所では、先に表示されたほうが実行されます。

### キーが効かない

1. 上のとおり、そのキーを付けて `xefm keys` を実行してください。XeFM がキーとアクションを理解できるか、そのキーがどこに割り当てられているかがわかります
2. キー表現の書式が正しいか確認してください
3. キー名が上の「キー名」と「名前で書く記号」に載っているものか確かめてください。一覧にない名前は `Unknown key in expression: ...` とログに記録され、発動しません
4. 修飾キーの綴りが正しいか確認してください
5. ほかのキーバインドと衝突していないか確認してください
6. ターミナルでは、その組み合わせがそもそもターミナルで送れるものか、そしてターミナルエミュレーター（または VS Code や tmux）が先に取っていないかを確認してください。上の「ターミナルで送れるキー」と「ホストが先に取るキー」を参照してください
7. `isearch.*` のアクションでは、キーが印字可能なものでないか確認してください。検索パターンにはそれらが先に渡されるので、そうしたキーバインドは決して発動しません（XeFM は起動時にログペインでその旨を伝えます）

### アクションが使えない

1. 選択の条件が現在の状態に合っているか確認してください
2. アクションが `'selection': 'required'` を必要とする場合は、ファイルが選択されているか確かめてください
3. アクションが `'selection': 'none'` を必要とする場合は、ファイルが何も選択されていないか確かめてください

### 修飾キーが認識されない

1. 修飾キーの名前が Shift、Control/Ctrl、Alt/Option、Command/Cmd のいずれかであるか確かめてください
2. 綴りを確認してください（大文字・小文字は関係ありません）
3. 修飾キーとメインのキーをハイフンで区切っているか確認してください

## 関連項目

- [設定](CONFIGURATION_FEATURE.ja.md) - 設定全般のガイド
- [カスタマイズ](CUSTOMIZATION_FEATURE.ja.md) - ビューアーのキー、独自のアクション、イベントフック
- [ヘルプダイアログ](HELP_DIALOG_FEATURE.ja.md) - XeFM の中でキーバインドを確認する
