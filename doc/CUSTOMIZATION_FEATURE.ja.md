# カスタマイズ

[English](CUSTOMIZATION_FEATURE.md) \| 日本語

> **安定版。ただし一部はプレビュー。** このページの API はバージョン 1（`xefm.user_api.API_VERSION`）です。安定版の部分は XeFM のリリースをまたいで動き続けます。廃止される予定の安定版 API は、まず非推奨になります。その後も少なくとも 1 つ先のマイナーリリースまでは動き続け、使うと XeFM が代わりの API を示す警告をログに出し、リリースノートにもそのことが書かれます。削除されるのはその後で、そのとき `API_VERSION` が新しくなります。**（Preview）** と記された部分は、どのリリースでもまだ変わる可能性があります。
>
> 安定版：`ACTIONS`、`SORT_KEYS`、`FILTERS`、`PATH_SCHEMES`（組み込みのスキームの置き換えを除く）、関数に渡されるペインとエントリ、`ctx.pane` / `other` / `left` / `right`、`ctx.invoke`、`ctx.run_program`、`ctx.message`、`ctx.action_names`、そして `PROGRAMS` 用の `xefm_tool`、`xefm_python`、`is_desktop_mode`。
>
> プレビュー：`EVENT_HOOKS`、`MENU_ITEMS`、`IMAGE_DECODERS`、`LEXERS`、`ATTRIBUTES`、`LAYOUTS`、`DEFAULT_LAYOUT`、`LAYOUT_EXTRAS`、`entry.attr`、`Cell`、プロンプト（`ctx.input` / `choose` / `confirm`）、`ctx.run_task`、`ctx.show_markdown`、`ctx.copy_text`、`ctx.diff`、`ctx.actions`、`pane.open_list`。プレビューのテーブルを使う設定では、そのことを伝える 1 行がログペインに表示されます。また、プレビューの関数を初めて呼び出すと、その名前を示す 1 行がログに出ます。

`~/.xefm/config.py` は XeFM が起動時に実行する本物の Python なので、以前からロジックを書くことができました。`if sys.platform == 'win32':` のブロック、計算で求めたパス、リスト内包表記などです。この機能はその一歩先を行きます。設定の中で**関数**を定義し、キーに割り当て、何かが起きたときに実行できます。

これでできることは次の 3 つです。

- **どこでも、どのキーでも割り当てを変更できます。** ファイルリストだけではありません。テキスト、画像、差分、ディレクトリ差分の各ビューアーが、使うキーのすべてに名前を付けるようになり、そのどれもが変更できます。
- **キーを自分の関数に割り当てられます。** 関数はペインを読み取り、操作できます。
- **何かが起きたときに自分の関数を実行できます** — 起動時、終了時、ペインがディレクトリを移動したとき、ファイルが開かれたとき。

すべてのキーに名前を付けるにあたって、すでにあった名前の一部も修正しました。古い名前も引き続き使えます。一覧は[名前が変わったアクション](KEY_BINDINGS_FEATURE.ja.md#名前が変わったアクション)を参照してください。

---

## ビューアーのキーの割り当てを変更する

`KEY_BINDINGS` には、XeFM の機能の大部分がすでに並んでいました。並んでいなかったのはビューアーの*中の*キーです。テキストビューアーをスクロールする `PgDn`、次の差分ブロックへ移動する `n`、ディレクトリ差分で左右を切り替える `Tab` などがそれで、コードに固定されていて変更できませんでした。

現在、これらは普通の名前付きアクションです。既定では `KEY_BINDINGS` に記載されておらず、エントリがなくても動作するので、変更したいキーについてだけエントリを追加してください。

```python
KEY_BINDINGS = {
    ...
    'text_viewer.page_down': ['SPACE'],   # page with Space in the text viewer
    'text_viewer.page_up': ['B'],
    'file_diff.next_block': ['J'],
    'file_diff.prev_block': ['Shift-J'],
}
```

名前の先頭には、そのアクションが属するビューアーの名前が付きます。それぞれの画面は自分の名前しか見ないので、ビューアーのキーとファイルリストのキーが同じキーを共有しても曖昧さは生じません。ビューアーでは `W` で行の折り返しを切り替え、ファイルリストでは（AFX 風のように）`W` でペインを比較しても、衝突にはなりませんし、もともと衝突させるつもりもありません。上の例では、`SPACE` はテキストビューアーではページ送りをしつつ、ファイルリストでは引き続き本来の役目を果たします。各プリセットがどのキーをどこに割り当てているかは、[キーマッププリセット](KEYMAP_PRESETS_FEATURE.ja.md#すべてのキーの一覧)を参照してください。

`KEY_BINDINGS` のほかの場所と同じく、エントリは既定に追加されるのではなく、既定を**置き換え**ます。上の最初の行を書いた後は、PgDn ではテキストビューアーのページ送りができなくなります。両方使いたい場合は、`['SPACE', 'PAGE_DOWN']` のように両方を並べてください。

### ビューアーのアクション一覧

標準で割り当てられているキーはここには載せていません。各アクションは自分のキーを `xefm/actions.py` で宣言していますし、ビューアーの中で `F1` を押すと、あなたの環境で何に割り当てられているかが表示されます。古くなりようがない一覧はそれだけです。

| テキストビューアー | ファイル差分 |
|---|---|
| `text_viewer.scroll_up` | `file_diff.scroll_up` |
| `text_viewer.scroll_down` | `file_diff.scroll_down` |
| `text_viewer.page_up` | `file_diff.page_up` |
| `text_viewer.page_down` | `file_diff.page_down` |
| `text_viewer.scroll_top` | `file_diff.scroll_top` |
| `text_viewer.scroll_bottom` | `file_diff.scroll_bottom` |
| `text_viewer.scroll_left` | `file_diff.scroll_left` |
| `text_viewer.scroll_right` | `file_diff.scroll_right` |
| `toggle_wrap` \* † | `file_diff.next_block` |
| `toggle_view_mode` \* † | `file_diff.prev_block` |
| `change_encoding` \* † | |

| 画像ビューアー | ディレクトリ差分 |
|---|---|
| `image_viewer.zoom_in` \* | `dir_diff.cursor_up` |
| `image_viewer.zoom_out` \* | `dir_diff.cursor_down` |
| `image_viewer.zoom_reset` \* | `dir_diff.page_up` |
| `image_viewer.next` \* | `dir_diff.page_down` |
| `image_viewer.prev` \* | `dir_diff.cursor_top` |
| `image_viewer.pan_up` \* | `dir_diff.cursor_bottom` |
| `image_viewer.pan_down` \* | `dir_diff.expand` |
| `image_viewer.pan_left` \* | `dir_diff.collapse` |
| `image_viewer.pan_right` \* | `dir_diff.activate` |
| `image_viewer.first` | `dir_diff.switch_side` |
| `image_viewer.last` | `dir_diff.next_change` |
| | `dir_diff.prev_change` |
| | `dir_diff.rescan` |
| | `dir_diff.split_left` |
| | `dir_diff.split_right` |

### インクリメンタルサーチバー

検索バー（`isearch`）はそれ自体が 1 つの画面で、そのキーにも同じ方式で名前が付いています。

| アクション | |
|---|---|
| `isearch.next_match` | 次のマッチへ移動 |
| `isearch.prev_match` | 前のマッチへ移動 |
| `isearch.toggle_select_down` | 選択してから次のマッチへ移動 |
| `isearch.toggle_select_up` | 選択してから前のマッチへ移動（既定のキーなし） |
| `isearch.select_matches` | すべてのマッチを選択（もう一度押すと解除） |
| `isearch.accept` | 現在のマッチで止まる |
| `isearch.cancel` | キャンセルしてカーソルを元に戻す |

ここにだけ当てはまる規則が 1 つあります。**文字を入力するキーは使えません。** 印字可能な文字はすべて入力中のパターンのものです。そのため、ここでファイルを選択するキーは Space ではなく `Ctrl-Space` になっています。Space の文字は、検索では `report 2024` を `report*2024*` として扱うための区切りとして読まれるからです。isearch のアクションを `N` に割り当てても決して発動しません。XeFM は、あなたが首をかしげたままにならないよう、起動時にそのことをログペインに表示します。Shift を付けても印字可能なキーはコマンドになりません。`Shift-Space` もスペースを入力するので、ファイルリストの `select_range` のキーはここでは何もしません（範囲選択はこの画面の操作にも含まれていません。Enter で検索を終えればカーソルはマッチした位置に残るので、そこでファイルリストのキーが使えます）。Ctrl を付けたキーと、印字されないキーはすべて自由に使えます。`Ctrl-Y`、`Shift-DOWN`、`F2`、`INSERT`（Windows とターミナルで。macOS のキーボードには Insert キーがありません）などです。

`isearch.select_matches` は、本来ならパターン入力欄が使うキー（テキストの全選択）を取ってしまう唯一の既定です。取るのは Ctrl の形だけで、macOS では `Cmd-A` で引き続きテキストを選択できます。この組み合わせが手に染みついているのは macOS だからです。

\* これらは既定の `KEY_BINDINGS` に有効なエントリとして記載されているので、テンプレートから生成した設定にはすでに含まれています。それ以外は、エントリがなくても上の既定のまま動作します。

† 意図的に接頭辞を付けていません。この 3 つは 1 つのビューアーでの使い方ではなく*機能*そのものの名前です。また、すでに同じデコーダーを通して読み込んでいる差分ビューアーは、文字コード選択の 2 番目の置き場所として十分に考えられます。接頭辞のない名前にしておけば、もしそうなっても、既存の割り当てが何も変えずに両方のビューアーに効きます。1 つの名前が複数のコンテキストに存在し、それぞれが独自の動作を持つことはありえます。`copy_files` がファイルリストとディレクトリ差分ですでにそうなっているのとまったく同じです。

ディレクトリ差分は、フォーカスのあるノードに対して実行できるファイルリストのアクション（`copy_files`、`move_files`、`delete_files`、`view_file`、`edit_file`）も同じ名前で理解するので、1 回の割り当て変更で両方が変わります。

### 共通のキーを 1 か所だけで変更する

`quit`、`help`、`isearch`、`edit_file` はどの画面でも意味を持ちます。そのため、`quit` の割り当てを変更すると、ファイルリスト*と*すべてのビューアーで変わります。1 つのビューアーだけで変更するには、名前の前にそのビューアーの名前を付けます。

```python
KEY_BINDINGS = {
    'quit': ['Q'],            # everywhere...
    'file_diff.quit': ['X'],  # ...except in the file diff viewer
}
```

---

## 自分のアクション：`ACTIONS`

引数を 1 つ取る関数を定義し、その名前を `ACTIONS` に書いて、`KEY_BINDINGS` でその名前をキーに割り当てます。関数は `class Config:` の**上**に定義してください。普通のモジュールレベルの Python です。

```python
def select_documents(ctx):
    """Select every Word/PDF document in the active pane."""
    n = ctx.pane.select(lambda e: e.suffix.lower() in ('.docx', '.pdf'))
    ctx.message(f"Selected {n} document(s)")


class Config:
    ACTIONS = {
        'select-documents': select_documents,
    }

    KEY_BINDINGS = {
        ...
        'select-documents': ['Shift-D'],
    }
```

Shift-D を押すとドキュメントが選択されます。自分のアクションはヘルプダイアログ（`F1`）にも、組み込みのアクションと並んで **Your Actions** の下に表示されます。

ファイルを編集して `reload_config` を実行すると、新しい版がすぐに有効になります。再起動は不要です。

### 組み込みのアクションを置き換える・包む

すでに組み込みのアクションとして存在する名前は、意図したものだと明示しない限り無視され、ログペインに警告が出ます。明示した場合でも、組み込みのアクションは `ctx.invoke()` から呼び出せるので、置き換えるのではなく包むこともできます。

```python
def confirm_then_quit(ctx):
    ctx.message("saving session…")
    save_session(ctx)
    ctx.invoke('quit')          # runs the *built-in* quit


class Config:
    ACTIONS = {
        'quit': {'func': confirm_then_quit, 'override': True},
    }
```

### アクションの説明：docstring

自分のアクションは、キーに割り当てているかどうかにかかわらず、すべてコマンドパレット（**Tools → Command Palette…**）に並びます。そのため、月に 1 度しか実行しないアクションにはキーが要りません。そこでの説明は docstring で、Python の通常の方法で分けて使われます。

```python
def open_in_vscode(ctx):
    """Open the item under the cursor in VS Code.

    Works on directories too — VS Code opens them as a workspace.
    """
    ctx.run_program(['code', str(ctx.pane.focused.path)])
```

- **1 行目**は 1 行の説明です。ヘルプダイアログ（F1）の行と、パレットのリストの下に出る行になります。
- **空行の後の段落**は、パレットでそのアクションに対して F1 を押したときに開くページになります。そこでは Markdown が使えます。

docstring がない場合は、どちらにもアクションの名前だけが表示されます。docstring を書けない関数（lambda やライブラリの関数）の場合は、辞書形式で `description` を指定できます。書き方も分け方も docstring とまったく同じで、docstring 全体を置き換えます。

```python
ACTIONS = {
    'tidy': {'func': lambda ctx: ctx.invoke('unselect_all'),
             'description': """
                 Clear the selection.

                 The same as Select ▸ Clear Selection, under a name of its own.
             """},
}
```

コマンドパレットより前の設定で書かれていたような 1 行の `description` は、続きのページを持たない概要になります。

### 関数に渡されるもの

引数は `ctx` だけです。`ctx` には次のものがあります。

| | |
|---|---|
| `ctx.pane` | アクティブなペイン |
| `ctx.other` | アクティブでないペイン |
| `ctx.left`, `ctx.right` | 位置で指定したペイン |
| `ctx.invoke(name)` | 別のアクション（組み込みでも自分のものでも）を実行 |
| `ctx.message(text)` | ログペインに 1 行書き出す |
| `ctx.show_markdown(title, source)` | （プレビュー）Markdown をスクロールできるダイアログに表示し、各コードブロックに Copy ボタンを付ける — 後述 |
| `ctx.copy_text(text)` | （プレビュー）テキストをクリップボードに置く |
| `ctx.diff(left, right)` | （プレビュー）**Select → Compare Selected Files…** と同じように 2 つのファイルを比べる。選択は不要。どちらも SSH、S3、アーカイブ、仮想フォルダの中のファイルでよく、`left_title=` / `right_title=` で左右の見出しを付けられる |
| `ctx.run_task(title, work, on_done=fn)` | （プレビュー）時間のかかる処理を進捗ダイアログ付きでバックグラウンドで実行 — 後述 |
| `ctx.input(prompt, default, on_accept=fn)` | （プレビュー）1 行のテキストを入力してもらう。`complete='path'`（または `'directory'`）を付けると、Jump to Path と同じくパスを Tab で補完できる — 相対パスはアクティブなペインが起点 |
| `ctx.choose(title, items, on_result=fn)` | （プレビュー）リストから選んでもらう（インデックス、または `None`）。`type='filter'` で検索できるリストになる |
| `ctx.confirm(prompt, on_result=fn)` | （プレビュー）はい / いいえ |
| `ctx.run_program(command, terminal=False)` | 外部プログラムを実行 — 後述 |
| `ctx.copy(items, dest, on_done=fn)` | （Preview）**File → Copy to Other Pane** と同じように（確認、競合ダイアログ、進捗付きで）ファイルをコピーし、それぞれの結果を受け取る — 後述 |
| `ctx.move(items, dest, on_done=fn)` | （Preview）同じく移動 |
| `ctx.terminal_backend_suspended()` | （Preview）`subprocess` で対話的なプログラムを自分で実行するための `with` ブロック — 後述 |
| `ctx.program_env()` | （Preview）`subprocess` に渡す `{'cwd': ..., 'env': ...}`。`run_program` がプログラムに渡すものと同じ |
| `ctx.is_terminal_backend` | （Preview）XeFM がターミナルで動いていて、引き渡すターミナルがあるかどうか |
| `ctx.action_names()` | `invoke()` が受け付けるすべての名前 |
| `ctx.actions()` | （プレビュー）同じアクションを、それぞれの `name`、`description`、`aliases`（以前の名前）、`keys`（`KEY_BINDINGS` を反映した、いま割り当てられているキー）付きで返す |

各ペインには次のものがあります。

| | |
|---|---|
| `pane.path` | 表示しているディレクトリ |
| `pane.name` | `'left'` または `'right'` |
| `pane.is_active` | カーソルがそのペインにあるかどうか |
| `pane.activate()` | カーソルをそのペインに移す |
| `pane.entries` | 表示されているすべてのもの（ペインのソート順） |
| `pane.cursor` | フォーカスのある行のインデックス（代入可能。範囲内に収められる） |
| `pane.focused` | カーソル位置のエントリ、または `None` |
| `pane.selected()` | 選択されたエントリ |
| `pane.select(predicate)` | 条件に合うものを選択に加え、その数を返す |
| `pane.unselect(predicate)` | 条件に合うものを選択から外す。条件を省くと選択をすべて解除 |
| `pane.cd(path, focus_name=None)` | どこかへ移動 |
| `pane.refresh()` | ディレクトリを読み直す |
| `pane.open_list(paths, title=...)` | （プレビュー）ディレクトリの代わりにパスのリストを開く — 後述 |

各エントリには `.name`、`.path`、`.suffix`、`.stem`、`.is_dir`、`.is_file`、`.is_link`、`.size`、`.mtime` があります。`.path` は `pathlib.Path` に似たもので、アーカイブ内や S3 / SFTP 上のファイルも指せるため、`entry.path.read_text()` はペインが動作する場所ならどこでも使えます。`pathlib` のメソッドのほかに、`.scheme`（`'file'`、`'s3'`、`'ssh'`、`'archive'`、…）、`.is_remote()`、`.supports(capability)`（`'write_operations'`、`'directory_rename'`、`'file_editing'`、`'streaming_read'` のいずれか）、そしてツリーファイルのエントリが表す実際のファイルを返す `.target()` があります。アーカイブの中のように読み取り専用のストレージでは、書き込みで `OSError` が発生することがあります。

`.size` と `.mtime` は初めて尋ねたときにディスクから読み取ります。それ以外はコストがかかりません。したがって、名前だけを見る条件はファイルシステムにまったくアクセスしないので、大きなディレクトリでは違いが出ます。

### 結果を表示する（Preview）

`ctx.show_markdown` は、Help や File Details が使うダイアログを、あなたの Markdown を入れて開きます。フェンスで囲んだコードブロックにはそれぞれ **Copy** ボタンが付きます（Tab で移動して Enter を押すか、クリックします）。また、どのテキストもマウスで選択してコピーできます。ユーザーがほかの場所に貼り付けたくなりそうなものは、コードブロックに入れてください。

```python
from xefm.user_api import md_code_block, md_escape

def show_names(ctx):
    entries = ctx.pane.selected() or [ctx.pane.focused]
    names = "\n".join(e.name for e in entries if e is not None)
    ctx.show_markdown("Names",
                      f"From **{md_escape(ctx.pane.path.name)}**:\n\n"
                      + md_code_block(names))
```

`md_code_block(text, lang='')` は、`text` の中身（バッククォートを含む名前や、それ自体が Markdown であるテキスト）によってブロックが途中で終わってしまわないように `text` をフェンスで囲みます。`md_escape(text)` は、ファイル名を文中でそのまま読めるようにします。`a_b*.txt` は、半分がイタリックになったりせず `a_b*.txt` のまま表示されます。

何も表示せずにコピーするだけなら、`ctx.copy_text(text)` を使います。

### 時間のかかる処理：`ctx.run_task`（Preview）

アクションは UI スレッドで実行され、ウィンドウはその完了を待ちます。`ctx` はそのスレッドのものです。アクションの中や `on_done` などのコールバックから使い、ほかのスレッドからは決して使わないでください。ファイル全体の読み込みやリモートのフォルダーなど、しばらくかかる処理は `ctx.run_task` に任せてください。`ctx.run_task` は、コピーと同じ進捗ダイアログ（**Cancel** と **Run in background** 付き）の裏で、関数をワーカースレッドで実行します。

```python
import hashlib
from xefm.user_api import md_code_block

def sha256_selection(ctx):
    paths = [e.path for e in (ctx.pane.selected() or [ctx.pane.focused])
             if e is not None and not e.is_dir]

    def work(job):                       # on the worker thread
        lines = []
        for i, path in enumerate(paths):
            job.checkpoint()             # stops here if the user cancelled
            job.progress(i, len(paths), detail=path.name)
            digest = hashlib.sha256()
            with path.open('rb') as f:
                for block in iter(lambda: f.read(1 << 20), b''):
                    digest.update(block)
            lines.append(f"{digest.hexdigest()}  {path.name}")
        return lines

    def done(ctx, outcome):              # back on the UI thread
        if outcome.ok:
            ctx.show_markdown("SHA-256", md_code_block("\n".join(outcome.value)))
        elif outcome.status == "cancelled":
            ctx.message("SHA-256: cancelled")

    ctx.run_task("SHA-256", work, on_done=done, read_only=True)
```

- **ワーカーが触れるのは `job` だけです。** `ctx` にもペインにも触れません。パスや設定など、必要なものはタスクを始める前に取り出しておいてください。`entry.path` はどのスレッドでも使え、`path.open('rb')` はディスク上でも、アーカイブの中でも、SSH / S3 上でも同じようにファイルを読み込めます。
- `job.progress(done, total, detail='')` はバーを進め、タイトルの下に `detail` を表示します。最初に呼び出すまでは、ダイアログにスピナーが表示されます。`job.item_progress(done, total)` は、コピーが大きなファイルについて表示するのと同じように、現在の項目についての 2 本目のバーをバイト単位（`1.2 GB / 30.0 GB`）で追加します。1 つのファイルを読み込んでいる間に呼び出してください。次の `job.progress` で消えます。`job.checkpoint()` は、ユーザーがキャンセルしたときに処理を止めます。`except Exception` で捕まえずに、そのまま通してください。`job.cancelled()` は、止めずにキャンセルされたかどうかだけを尋ねます。
- `on_done(ctx, outcome)` は、処理がどう終わったかにかかわらず 1 回だけ、新しい `ctx` を受け取って実行されます。`outcome.status` は `'done'`（`outcome.value` に `work` の戻り値が入ります）、`'cancelled'`、`'failed'`（`outcome.error` が入ります。トレースバックはすでにログに出ています）のいずれかです。`outcome.ok` は `'done'` のときに真になります。
- `read_only=True` は、その処理が何も変更しないことを示します。通常、バックグラウンドジョブは 1 つずつ実行されるので、長いバックグラウンドのコピー中に始めたタスクはその完了を待つことになりますが、読み取り専用のタスクはコピーと並行して実行されます。

### アクションをメニューに入れる：`MENU_ITEMS`（Preview）

アクションは、**File** メニュー、行から開く**コンテキストメニュー**（右クリックまたは Menu キー）、あるいはその両方に置けます。

```python
class Config:
    ACTIONS = {'sha256': sha256_selection}
    MENU_ITEMS = {
        'sha256': {'menus': ['file', 'context'], 'label': 'SHA-256…',
                   'when': 'entry'},
    }
```

`when` は、適用できないときに項目をグレー表示にします。`'entry'` はカーソル位置にエントリが必要で、`'selection'` は少なくとも 1 つの選択されたエントリが必要です。既定は `'always'` です。自分の項目は各メニューの下のほうに独自のグループとしてまとめられ、書いた順に並び、アクションにキーがあればそのキーも表示されます。3 つまではそこに並び、それより多いと、メニューが端末に収まるよう **Custom ▸** サブメニューの下にまとまります。組み込みのアクションを指定することもできます。誤りのあるエントリは、ログペインに 1 行出したうえで読み飛ばされます。

### キーから外部プログラムを実行する

`PROGRAMS` のエントリは **Tools → External Programs…** の選択画面から起動します。プログラムに専用のキーを割り当てるには、アクションから `ctx.run_program()` で呼び出します。

```python
def massren(ctx):
    ctx.run_program(['massren'], terminal=True)


class Config:
    ACTIONS = {'massren': massren}
    KEY_BINDINGS = {..., 'massren': ['Alt-R']}
```

`command` はリスト、またはコマンドラインと同じように分割される文字列です。`PROGRAMS` のエントリと同じように、アクティブなペインのディレクトリで、同じ [`XEFM_*` 変数](EXTERNAL_PROGRAMS_FEATURE.ja.md#環境変数)を環境に入れて実行されます（`env={...}` で独自の変数を追加したり、`cwd=` でディレクトリを指定したりできます）。違いは 1 つで、**ファイル名は付け加えられません。** プログラムが選択項目を必要とする場合は、自分で渡してください。

```python
def open_selection_in_vim(ctx):
    files = ctx.pane.selected() or [ctx.pane.focused]
    ctx.run_program(['vim'] + [str(e.path) for e in files if e], terminal=True)
```

- `terminal=True` を付けない場合、プログラムはバックグラウンドで起動し、その出力はログペインに送られ、XeFM はそのまま動き続けます。
- `terminal=True` を付けた場合、XeFM はターミナルをプログラムに引き渡し、終了を待ちます。エディターやページャーなど、画面に描画したりキーボードから読み込んだりするものにはこれが必要です。プログラムが終了すると両方のペインが読み直され、終了コードが返されます。終了コードが 0 以外の場合は、エラー出力を読めるよう、まず Enter を待ちます。デスクトップのウィンドウには引き渡すターミナルがないため、そこではプログラムは代わりに [`TERMINAL`](EXTERNAL_TERMINAL_FEATURE.ja.md) のアプリケーションで開き、XeFM はその終了を待ちません。

対話的なプログラムに対して自分で `subprocess.run()` を呼び出さないでください。ただし `ctx.terminal_backend_suspended()`（後述）の中は例外です。ターミナルは XeFM が管理しているので、XeFM の知らないところでターミナルに描画したりキーボードから読み込んだりするプログラムは、画面を乱してしまいます。あるいは、両者が同じキーを待ち続けることになります。

### 対話的なプログラムを自分で実行する（Preview）

`run_program` が返すのは終了コードだけです。プログラムに入力を渡したり、その出力を読んだりするには、`ctx.terminal_backend_suspended()` の中で自分で実行します。たとえば `fzf` のような選択ツールは、候補を stdin で受け取り、選ばれたものを出力します。`with` ブロックの中では XeFM が退き、画面とキーボードはターミナルのものになるので、`subprocess` はシェルの中と同じように動きます。

```python
import shutil
import subprocess


def fuzzy_cd(ctx):
    fzf = shutil.which('fzf')
    if not ctx.is_terminal_backend or fzf is None:
        ctx.message('fuzzy_cd needs the terminal app and fzf')
        return
    folders = {e.name: e.path for e in ctx.pane.entries if e.is_dir}
    with ctx.terminal_backend_suspended():
        r = subprocess.run([fzf], input='\n'.join(folders), text=True,
                           stdout=subprocess.PIPE, **ctx.program_env())
    if r.returncode == 0:
        ctx.pane.cd(folders[r.stdout.strip()])
```

- ブロックを抜けると、例外で抜けた場合も含めて、XeFM はターミナルを取り戻し、両方のペインを読み直して再描画します。
- `ctx.program_env()` は、`run_program` が渡すのと同じものをプログラムに渡します。アクティブなペインのディレクトリと、[`XEFM_*` 変数](EXTERNAL_PROGRAMS_FEATURE.ja.md#環境変数)です。
- 受け取るのは、答えが出てくるストリームだけにします。`fzf` は選ばれたものを stdout に出力し、画面はターミナルに描きます。`dialog` や `whiptail` はその逆なので、`stderr` を受け取ります。
- `run_program` が加えて行っていることは、自分で行います。`run_program` は終了コードが 0 以外のときに Enter を待ちます（Esc で取り消した選択ツールでは、普通は待たないほうがよいでしょう）。また Windows では、`subprocess` が見つけられない `.cmd` のプログラムも見つけます。上の例のように、`shutil.which()` で得たパスを渡してください。
- デスクトップアプリには引き渡すターミナルがないため、そこではこのブロックはエラーになります。先に `ctx.is_terminal_backend` を確かめてください。

`ctx` のほかのすべてと同じく、これらはアクションが動く UI スレッドでのみ使えます。`ctx.run_task` の処理の中や、自分で立てたスレッドからは使えません。

### ファイルのコピーと移動（Preview）

`ctx.copy(items, dest)` と `ctx.move(items, dest)` は、**File → Copy to Other Pane** や **File → Move to Other Pane** と同じ操作を実行します。確認、名前が既にある場合の競合ダイアログ、**Cancel** と **Run in background** の付いた進捗ダイアログも同じです。対象のアイテムとコピー先は自分で決めます。

```python
def backup_selection(ctx):
    def done(ctx, outcome):
        if outcome.status == 'done':
            failed = [r for r in outcome.value if r.status == 'failed']
            ctx.message(f'Backed up {len(outcome.value) - len(failed)} item(s)')

    ctx.copy(ctx.pane.selected(), '/Volumes/Backup/inbox', on_done=done)
```

- `items` には、`ctx.pane.selected()` が返すもの、パス、絶対パスの文字列を渡せます。カーソル位置のアイテムに自動で切り替わることはありません。それが必要なら、自分で `[ctx.pane.focused]` を渡してください。
- `dest` はフォルダーで、なければ作成されます。SSH や S3 の上でもかまいませんが、アーカイブの中は指定できません。また、アイテムをそれ自身のフォルダーにはコピーできません。どちらも呼び出した時点でエラーになります。
- 呼び出しはすぐに戻ります。`on_done(ctx, outcome)` は、操作が終わったときに新しい `ctx` を渡して実行されます。ジョブキューで待った場合やバックグラウンドで実行した場合も同じです。
  - `outcome.status` は `'done'`、`'cancelled'`（確認、競合ダイアログ、実行中のいずれかで取り消した場合）、`'failed'`（操作自体が失敗した場合。理由は `outcome.error`）のいずれかです。
  - `outcome.value` は、アイテムごとの結果を渡した順に並べたリストです。`r.source`、`r.dest`、`r.status`（`'done'`、競合ダイアログでの `'skipped'`、`'failed'`）、`r.errors`（その下で起きた失敗の `(name, message)` の組）を持ちます。ほとんどのファイルをコピーできたフォルダーは `'done'` になり、コピーできなかったものは `r.errors` に入ります。

### 自分のファイルリストを開く（Preview）

`pane.open_list()` は、検索結果がペインに表示されるのと同じように、任意のパスのリストをペインに表示します。どの行に対してもすべてのファイル操作が使え、`go_parent` で元のディレクトリに戻ります。自分で作った検索（あるいはパスを出力するツールなら何でも）の結果を XeFM に取り込むための方法です。

```python
import subprocess


def modified_in_git(ctx):
    out = subprocess.run(['git', 'ls-files', '--modified'],
                         cwd=str(ctx.pane.path), capture_output=True,
                         text=True).stdout
    ctx.pane.open_list(out.splitlines(), title='git: modified')


class Config:
    ACTIONS = {'modified_in_git': modified_in_git}
```

パスは文字列、`Path` オブジェクト、エントリのいずれでもよく、絶対パスでも `pane.path` からの相対パスでもかまいません。`ssh://…` や `s3://…` の URI も使え、1 つのリストに混在させることもできます。どれが存在するかはワーカースレッドで確認されます。存在しないものは除外されてログペインにその数が表示され、1 つも存在しない場合はペインは元のままです。各行の名前は、すべてに共通する最も深いディレクトリからの相対パスになります。その後のペインの動作は[ファイルリスト機能](FILE_LIST_IMPORT_FEATURE.ja.md)で説明しています。

リストを作るのはあなたのコードの仕事で、ほかのアクションと同じく UI スレッドで実行されます。数秒かかるコマンドを実行すると、その間ウィンドウが固まります。

---

## イベントへの反応：`EVENT_HOOKS`（Preview）

```python
def log_visit(ctx, event):
    with open(Path.home() / '.xefm' / 'visited.log', 'a') as f:
        f.write(f"{event.new_path}\n")


def open_psd_in_gimp(ctx, event):
    if event.path.suffix.lower() != '.psd':
        return False
    subprocess.Popen(['gimp', str(event.path)])
    return True          # claimed — XeFM does nothing further


class Config:
    EVENT_HOOKS = {
        'directory_changed': [log_visit],
        'file_open': [open_psd_in_gimp],
    }
```

フックはすべて `fn(ctx, event)` の形です。`event.name` はイベントの名前で、何が起きたかはイベントのほかの属性に入っています。

| イベント | `event` の中身 | 発生するとき |
|---|---|---|
| `startup` | — | アプリが立ち上がり、ペインの一覧が表示された後に 1 回 |
| `quit` | — | XeFM が終了する前。ペインはまだ有効 |
| `directory_changed` | `pane`, `old_path`, `new_path` | ペインが別のディレクトリに移動したとき |
| `file_open` | `path` | ファイル上で Enter を押し、XeFM がそれをどう扱うか決める前。`True` を返すとそのファイルを引き受ける |

各イベントにはリストを対応させ、その順に実行されます。1 つしかない場合は、関数をそのまま書いてもかまいません。

引数は決して変わりません。後のバージョンでイベントが伝えることが増える場合は新しい属性として伝えるので、その属性を読まないフックには影響しません（以前のフックは、情報を `fn(ctx, pane, old_path, new_path)` のように別々の引数として受け取っていました。そのようなフックは現在、読み込み時に除外され、その名前を示す 1 行がログペインに表示されます）。

`file_open` を使えば、`FILE_ASSOCIATIONS` に触れずに、ファイルの種類ごとに自分の好きな処理へ回せます。これは **open** アクション（Enter）で発生します。ディレクトリでは発生しません（ディレクトリに入るのは開くことではなく移動だからです）。また、`view_file`、`open_with_os`、ビューアーでも発生しません。これらは特定の方法で開くことを明示的に求める操作だからです。

`directory_changed` は、実際にディレクトリが変わったときに発生します。再表示、並べ直し、ファイル操作の後の再読み込み、ファイルシステム監視による再読み込みは、いずれもペインをその場に残すので、発生しません。

---

## 自分のソート順：`SORT_KEYS`

XeFM は名前を文字コード順に並べます。これはエクスプローラーや Finder のディレクトリの並べ方とは違います。それらは記号や数字を別の位置に置き、漢字はシステム独自の規則で並べます。XeFM は、そのどれか 1 つを選ぶ代わりに、あなたが望む順序を書けるようにしています。

ソートキーは、エントリを 1 つ受け取って並べ替えられる値を返す関数です。XeFM は返ってきた値で並べ替えます。

```python
SORT_KEYS = {
    "biggest": {"label": "Size, then name", "key": lambda e: (e.size, e.name)},
}
```

これで、ソートダイアログ（`sort`）と **View → Sort By** メニューに、4 つの組み込みの行と並んで **Size, then name** の行が追加されます。

### 受け取るものと返すもの

関数には、`name`、`path`、`is_dir`、`is_link`、`size`、`mtime` を持つエントリが 1 つ渡されます。`size` や `mtime` を読んでもコストはかかりません。XeFM は一覧表示のためにすでにそれらを集めているので、ネットワークドライブ上の巨大なディレクトリでも、キーによる余分なコストは発生しません。

`name` は**ペインに表示されているとおりの**名前で、並べ替えの基準にしたいのはこちらです。アクセント付きの文字や日本語の文字は、ディスクにどう保存されていても、1 つの書き方にそろえて渡されます。検索結果のペインでは、検索したフォルダーの下のパス全体、つまり行に表示されているのと同じテキストになります。ファイルそのものにアクセスする必要があるときは `path` を使ってください。

比較できるものなら何を返してもかまいません。文字列、数値、あるいは複数段階の順序には**タプル**を返します。タプルは要素ごとに比較されるので、`(e.size, e.name)` は「サイズ順、同じサイズの中では名前順」という意味になります。返す値は、*ほかの*すべてのエントリについて返す値と比較できなければなりません。あるエントリでは数値を返し、別のエントリではテキストを返すと、並べ替えができません。

処理する**必要がない**ことが 2 つあります。ディレクトリは常に先頭に来ますし、昇順・降順は自動的に適用されます。キーが決めるのは、1 つのグループの中の順序だけです。

### 組み込みのソートを置き換える

4 つの組み込みのソート（`filename`、`extension`、`size`、`timestamp`。ダイアログの行の名前を小文字にしたもの）のいずれかの名前を指定すると、それを置き換えます。それには `"override": True` が必要です。タイプミスで Filename の意味が知らないうちに変わってしまわないようにするためです。

```python
import locale, re
locale.setlocale(locale.LC_COLLATE, "")     # your system's own ordering

def by_system_order(entry):
    # digit runs as numbers, everything else through the system's ordering
    parts = re.split(r"(\d+)", entry.name)
    return [int(p) if i % 2 else locale.strxfrm(p) for i, p in enumerate(parts)]

SORT_KEYS = {"filename": {"key": by_system_order, "override": True}}
```

置き換えたソートは、新しいものを指定しない限り、元の行とラベルをそのまま使います。

### エントリのそのほかの項目

| | |
|---|---|
| `label` | ダイアログとメニューに表示する行のテキスト（既定は指定した名前） |
| `explain` | ダイアログが順序の下に表示する例の行。その順序がどんな並びになるかを書きます |
| `hotkey` | ダイアログでそのソートを直接適用する文字。新しい行には、ほかの行が使っていなければラベルの頭文字が割り当てられ、使われていれば何も割り当てられません。矢印キーは常に使えます |

### うまくいかないとき

失敗するキーや、互いに比較できない値を返すキーがあると、並べ替え全体が無効になります。ペインはファイル名順に戻り、そのことをログペインに 1 回だけ表示します。一覧表示が失敗することはなく、ファイルごとに 1 つずつメッセージを出してログをあふれさせることもありません。

キーはバックグラウンドスレッドで実行されることがあるので、メインスレッドにいることを前提とする処理をしてはいけません。渡されたエントリに対する計算や文字列処理だけにとどめてください。

---

## 自分のフィルター：`FILTERS`

ペインのフィルター（**View → Filter…**）はワイルドカードのパターン（1 つ、またはスペースで区切った複数のパターン、`*.jpg *.png`）を受け付けますが、パターンで尋ねられるのは名前のことだけです。「画像ファイル」「今日触ったもの」「100 MB を超えるもの」は*ファイル*についての問いで、パターンでは表せません。そこで、フィルターも自分で書けるようにしています。

各エントリは Filter ダイアログの固定の行になり、**clear filter** のすぐ下、以前にそこで入力したパターンの上に並びます。そのため、自分で定義したフィルターは、もともと属していない履歴の中で古くなって下へ流れていくことはなく、常に同じ場所にあります。

簡単なほうはパターンで、これまで手で入力していたのと同じものです。

```python
FILTERS = {
    "images": ["*.jpg", "*.jpeg", "*.png", "*.gif"],    # any one of them matches
}
```

もう 1 つは関数です。エントリを 1 つ受け取り、それを表示するかどうかを返します。

```python
import time

FILTERS = {
    "today": {"label": "Modified today",
              "match": lambda e: e.mtime >= time.time() - 24 * 3600},
    "big": {"label": "Over 100 MB", "match": lambda e: e.size > 100 << 20},
    "no-mates": {"label": "Files with no .txt beside them",
                 "match": lambda e: not e.path.with_suffix(".txt").exists()},
}
```

`label` は行のテキストで、既定は指定した名前です。

### 受け取るもの

ソートキーに渡されるのと同じエントリです。`name`、`path`、`suffix`、`stem`、`is_dir`、`is_file`、`is_link`、`size`、`mtime` を持っています。`size` や `mtime` を読んでもコストはかかりません。XeFM は一覧表示のためにすでにそれらを集めているので、ネットワークドライブ上の巨大なディレクトリに対するフィルターでも余分なコストは発生しません。`name` は**ペインに表示されているとおりの**名前です。ファイルそのものにアクセスする必要があるときは `path` を使ってください。

入力したパターンの場合とまったく同じく、**ディレクトリは常に表示されます。** ディレクトリを隠すフィルターは、これから開こうとしていたフォルダーを奪ってしまうからです。したがって、関数が決めるのはどの*ファイル*を表示するかだけです。「ディレクトリだけ」は `"match": lambda e: False` と書きます。

### 名前が表示される場所

フィルターは名前で記憶されるので、ステータスバーには裏にあるパターンではなく `Filter: Images` と表示されます。また、フィルターが有効な間に始めた内容検索（**View → Search Content…**）は、ペインに表示されているファイル（`match` 関数による絞り込みも含みます）だけを正確に対象にします。名前には `*`、`?`、`[` を含められません。XeFM は*入力した*フィルターをパターンそのものとして記憶するので、どちらとも読める名前は区別がつかなくなるからです。ワイルドカードは `pattern` に書き、フィルターにはふつうの名前を付けてください。

自分で定義した名前は、フィルターの入力欄の履歴にも入りません。すでに行があるので、記録すると 2 回表示されてしまうからです。

### うまくいかないとき

失敗したフィルターで失われるのは一覧表示ではなくフィルターです。ペインはすべてを表示し、そのことをログペインに 1 回だけ表示します。これは意図した方向です。ディレクトリの半分を黙って隠してしまうフィルターがあると、誰も気づかないうちにファイルが操作の対象に紛れ込むことになるからです。

ソートキーと同じく、`match` はバックグラウンドスレッドで実行されることがあるので、計算、文字列処理、すぐに答えの出るファイルシステムへの問い合わせだけにとどめてください。

---

## ファイルリストに表示するもの：`ATTRIBUTES`、`LAYOUTS`、`LAYOUT_EXTRAS`（Preview）

`ATTRIBUTES` は、XeFM が各エントリについて知ることのできる値（Git の状態、行数など）を追加します。値は自分の関数がバックグラウンドで計算します。`LAYOUTS` は行の見せ方を決めます。いつもの列のうちどれを、どの順に、どう書くかです。`LAYOUT_EXTRAS` は、その上にフォルダーの中身に応じた情報を加えます。列の文字の横に付ける印や、独自の列で、当てはまる場所で表示され、タブごとに切り替えられます。詳しくは専用のページ [ファイルリストのレイアウト](FILE_LIST_LAYOUTS_FEATURE.ja.md) を参照してください。

自分の関数からは、XeFM がすでに持っている値を `entry.attr('git')` で読めます。値を計算することも待つこともなく、値が届くまでは `None` を返すので、アクションの中でもソートキーの中でも同じように軽く使えます。

## 自分の画像形式：`IMAGE_DECODERS`（Preview）

画像ビューアーは、XeFM に同梱されたデコーダーよりも多くの形式をすでに読み込めます。マシン自体に尋ねるからです。macOS ではシステムのデコーダーが HEIC、JPEG XL、カメラの RAW を扱い、Windows ではインストールされているイメージングコーデックが使われ、ターミナルでは Pillow と、追加した Pillow プラグインが使われます。HEIC がまだ読めない環境でも、`~/.xefm/requirements.txt` に `pillow-heif` の行を書いて同期する（[追加の Python ライブラリ](PYTHON_PACKAGES_FEATURE.ja.md)）だけで対応できます。

残るのは、XeFM が同梱していないライブラリでしか読めない形式です。ファイルのバイト列から画像を作る関数を書き、拡張子を指定してください。

```python
import io

def open_svg(data):
    import cairosvg                   # pip install cairosvg
    from PIL import Image
    return Image.open(io.BytesIO(cairosvg.svg2png(bytestring=data)))

class Config:
    IMAGE_DECODERS = {'.svg': open_svg}
```

### 受け取るものと返すもの

関数には、パスではなくファイルの**バイト列**が渡されます。そのため、1 つのデコーダーで、ディスク上の画像も、zip の中の画像も、S3 バケット上の画像も、一時ファイルにコピーすることなく同じように扱えます。`PIL.Image` を返すか、「これは読めない」という意味で `None` を返してください（すでに生のピクセルを持っていて、XeFM がまた分解するだけの `PIL.Image` をわざわざ作りたくない場合は、`puikit.image.RasterImage` も受け付けます）。

### 登録すると引き受けることになる

XeFM は、マシン上の何かが実際にデコードできる形式に対してだけ画像ビューアーを提供します。そのため、画像ビューアーで開いたファイルは必ず画像が表示され、「表示できません」というカードになることはありません。拡張子を登録するとその集合に追加されます。`.svg` で `Enter` を押したときに、テキストではなく画像が開くのはそのためです。

XeFM がすでに読める拡張子を指定すると、そのデコーダーがあなたのものに**置き換わり**ます。形式の読み込み方を変える方法はこれしかないので、`override` フラグは求められません。エントリを書くこと自体がその意思表示です。

### うまくいかないとき

デコーダーが失敗しても、失われるのはその画像だけです。ビューアーはメタデータのカードに理由を表示し、ログペインにはトレースバックが出ます。ここではカードで失敗するのが正しい方向です。フィルターと違い、デコードできない画像には正直な代わりのものがないからです。

ソートキーと同じく、デコーダーはバックグラウンドスレッドで実行されることがあるので、UI に触れてはいけません。また、このドキュメントの中で最も時間がかかるのもデコーダーです。RAW のデコードには数秒かかります。

プラットフォームごとの形式の一覧など、詳しくは [`doc/IMAGE_VIEWER_FEATURE.md`](IMAGE_VIEWER_FEATURE.ja.md) を参照してください。

---

## 自分のシンタックスハイライト：`LEXERS`（Preview）

テキストビューアーは、数百の言語を知っていてファイル名から言語を選ぶ [Pygments](https://pygments.org/) でファイルに色を付けます。`LEXERS` は、Pygments が誤るファイルのためのものです。Pygments の知らない拡張子や、Pygments が別の言語に割り当てている拡張子などです。

```python
from autocad_lexers import DclLexer       # ~/.xefm/extensions/autocad_lexers.py

class Config:
    LEXERS = {
        '*.dcl': DclLexer,      # your own lexer
        '*.mnl': 'newlisp',     # a lexer Pygments already has, for another suffix
    }
```

### キー：どのファイルか

Pygments の書き方と同じファイル名のパターンです。`'*.dcl'`、`'Jenkinsfile'`、`'*.conf.in'` など。拡張子だけ（`'.mnl'`）を書くと `'*.mnl'` と同じ意味になります。マッチングでは大文字と小文字を区別しないので、`DIALOG.DCL` は `*.dcl` のファイルです。正確な名前はワイルドカードより優先され、どちらもマッチする 2 つのワイルドカードの間では、後のエントリが優先されます。

### 値：どのレキサーか

**名前** — Pygments が持っている任意のレキサーです。`pygmentize -L lexers` で一覧が表示されます。各行のコロンより前にある名前が使えるものです。Pygments がすでに読める言語として別の拡張子に色を付けるには、これだけで済みます。

**クラス** — 自分のレキサーです。[Pygments のガイド](https://pygments.org/docs/lexerdevelopment/)に書かれているとおりに書く普通の Pygments のレキサーで、XeFM のものは何も含みません。

```python
# ~/.xefm/extensions/autocad_lexers.py
from pygments.lexer import RegexLexer
from pygments.token import Comment, Keyword, Text

class DclLexer(RegexLexer):
    name = 'DCL'
    aliases = ['dcl']
    tokens = {
        'root': [
            (r'//.*?$', Comment.Single),
            (r'\w+', Keyword),
            (r'\s+', Text),
            (r'.', Text),
        ],
    }
```

設定を再読み込みしたときに編集が反映されるよう、[`~/.xefm/extensions/`](#自分のモジュールxefmextensions) に置いてください。普通の Pygments なので、AI アシスタントに「<言語> の Pygments レキサー」を頼めば、そのまま使えるものが手に入ります。

クラスに `filenames` 属性があっても、それは**使われません**。どのファイルに色を付けるかは `LEXERS` のキーだけで決まるので、`config.py` を見ればすべてがわかります。一方、`aliases` は使われます。クラスを `LEXERS` に入れると、その名前を値としても使えるようになります（`'*.dclx': 'dcl'`）。

### Pygments より優先する

エントリは Pygments 自身の選択より先に参照されます。たとえば Pygments は `*.dcl` を Clean 言語に割り当てていますが、上のエントリによって AutoCAD の DCL になります。Pygments のプラグインパッケージとしてインストールしたレキサーにはエントリはまったく不要です。Pygments がすでに見つけてくれます。

### うまくいかないとき

存在しないレキサーを指定したエントリや、レキサーでない値は、ログペインに 1 行出したうえで読み飛ばされ、残りは読み込まれます。出力が元のファイルを再現しないレキサーの場合、そのファイルは位置がずれて表示されるのではなく、色なしで表示されます。Pygments がインストールされていなければ何も色付けされず、`LEXERS` はそのことをログペインに 1 回表示します。

---

## 自分の場所：`PATH_SCHEMES`

設定では、ディレクトリではないブラウズ可能な場所を追加できます。Windows のレジストリ、ブックマークのデータベース、デバイスの一覧など、フォルダーとファイルとして見せられるものなら何でもかまいません。クラスを 1 つ書いて名前を付ければ、`reg://` はペインで開ける場所、`jump_to_path` で移動できる場所、`FAVORITES` に入れられる場所になります。

```python
import io
from xefm.path_base import ReadOnlyPathImpl, UriStatResult

class NotesPathImpl(ReadOnlyPathImpl):
    def exists(self):  ...
    def is_dir(self):  ...
    def iterdir(self): ...      # yield self.child(name)
    def stat(self):    ...      # return UriStatResult(size=…, mtime=…, is_dir=…)
    def open(self, mode='r', buffering=-1, encoding=None,
             errors=None, newline=None): ...

class Config:
    PATH_SCHEMES = {'notes': NotesPathImpl}
```

必要なのは 5 つのメソッドだけです。パスの演算、親、名前、グロブ、書き込みの拒否は基底クラスが提供します。レジストリブラウザーの例や、どのオーバーライドが安定版かを含む詳しい手順は、[`doc/VIRTUAL_FOLDERS_FEATURE.md`](VIRTUAL_FOLDERS_FEATURE.ja.md) にあります。

---

## 自分のモジュール：`~/.xefm/extensions/`

`~/.xefm/extensions/` は Python の import パスに含まれているので、ここまでの節で説明したもの（`PATH_SCHEMES` のクラス、アーカイブ形式、アクションのセットなど）は、それぞれ独立したファイルに置いて `config.py` から import できます。

```
~/.xefm/
├── config.py
└── extensions/
    ├── box.py              # import box
    └── mail/               # import mail.eml_archive
        ├── __init__.py
        └── eml_archive.py
```

```python
import box

class Config:
    PATH_SCHEMES = {'box': box.BoxPathImpl}
```

このディレクトリがなければ、XeFM が起動時に作成します。

**設定を再読み込みすると、これらも import し直されます。** モジュールを編集して **Tools ▸ Reload Configuration** を実行すれば、編集したコードが実行されます。再起動は不要です。

**名前が衝突したときは Python 自身のモジュールが優先されます。** このディレクトリは import パスの*末尾*に追加されるので、ここに置いた `email.py` や `queue.py` が XeFM のほかの部分で標準ライブラリを壊すことはありません。ただし、それらを import することもできません。名前を変えてください。

**パスに含まれるのは `extensions/` だけです。** `~/.xefm/` 自体は含まれません（含めると `config.py` が `config` として import できてしまい、ありふれすぎた名前を占有することになります）。XeFM が別プロセスとして実行する[外部プログラム](EXTERNAL_PROGRAMS_FEATURE.ja.md)を置く `~/.xefm/tools/` も含まれません。

**パッケージにする。** ここにあるディレクトリに `xefm-extension.toml` を置くと、それは[拡張パッケージ](EXTENSIONS_FEATURE.ja.md)になります。XeFM が `config.py` に何も書かなくてもアクション、フック、テーマを組み込んでくれ、`xefm ext install` で共有・インストールできるようになります。

**別の場所に置く。** バージョン管理下にあるなど、拡張機能を専用のプロジェクトディレクトリに置いている場合は、`config.py` の先頭で自分でパスに追加してください。

```python
import sys
sys.path.append('/Users/me/src/xefm-extensions')
```

---

## 知っておくべきこと

**コードは UI スレッドで実行され、XeFM はその完了を待ちます。** 遅いアクションは、戻るまでウィンドウを固まらせます。アクションは手早く済ませてください。時間のかかる処理は `ctx.run_task()` に任せ、外部プログラムは `ctx.run_program()` で起動します。

**プロンプトは処理を止めません。** XeFM はダイアログのために止まることがないので、`ctx.input`、`ctx.choose`、`ctx.confirm` はすぐに戻り、答えをコールバックに渡します。アクションの残りの処理はコールバックの中に書いてください。

```python
def rename_to_lowercase(ctx):
    entry = ctx.pane.focused
    if entry is None:
        return

    def go(ok):
        if ok:
            entry.path.rename(entry.path.with_name(entry.name.lower()))
            ctx.pane.refresh()

    ctx.confirm(f"Rename {entry.name} to lowercase?", on_result=go)
```

**長いリストには検索できる選択画面を使います。** `ctx.choose` は小さなボックスを開きます。入力すると選択位置がジャンプし、1 秒ほど何もしないと入力した内容は忘れられます。少数の選択肢には向いていますが、探す必要のあるリストには向きません。`type='filter'` を渡すと、代わりに組み込みの Favorites や History のリストと同じダイアログになります。スクロールするリストの上にフィルター欄があり、アクティブなペインの上に表示されます。ファイルペインのインクリメンタルサーチと同じクエリ（スペース区切りのトークン、ワイルドカード、Migemo。ローマ字を入力すれば日本語のラベルが見つかります）を受け付け、消すまでそのクエリを保持します。

```python
BOOKMARKS = [("work", "/Users/me/src"), ("写真", "/Users/me/Pictures")]

def go_to_bookmark(ctx):
    def jump(index):
        if index is not None:
            ctx.pane.cd(BOOKMARKS[index][1])

    ctx.choose("Bookmarks", [f"{n}  —  {p}" for n, p in BOOKMARKS],
               type="filter", on_result=jump)
```

同じ理由で、`pane.cd()` と `pane.refresh()` も非同期です。ディレクトリはワーカースレッドで読み込まれるので、呼び出した直後は `pane.entries` が一時的に空になります。新しい一覧は、次の行ではなく、後で実行するアクションか `directory_changed` フックから読んでください。

**間違えても失うのはログ 1 行だけです。** アクションやフックの中で発生した例外は捕捉され、トレースバックとともにログに記録されて捨てられます。XeFM は動き続けます。`ACTIONS` や `EVENT_HOOKS` の不正なエントリは警告となってそのエントリだけが読み飛ばされ、設定の残りは読み込まれます。

**1 つの設定で両方のプラットフォームに対応します。** この API にはウィジェットやバックエンドのことは何も出てこないので、同じ設定がターミナルでもデスクトップのウィンドウでもまったく同じように動作します。

**このバージョンにはないもの：** *ビューアー*の中で割り当てる関数（ビューアーのキーは割り当てを変更できますが、割り当てる関数はファイルリストのアクションでなければなりません）、独自のビューアーやレンダラー、関数によるフィルターの条件、ウィジェットツリーへのアクセス。いずれも後から追加できる形になっています。

---

## 関連項目

- [`doc/KEY_BINDINGS_FEATURE.md`](KEY_BINDINGS_FEATURE.ja.md) — キー表記の構文、修飾キー、選択の要件
- [`doc/CONFIGURATION_FEATURE.md`](CONFIGURATION_FEATURE.ja.md) — `config.py` のそのほかのすべて
- [`doc/EXTERNAL_PROGRAMS_FEATURE.md`](EXTERNAL_PROGRAMS_FEATURE.ja.md) — 外部プログラムの実行。XeFM を拡張するもう 1 つの方法
- [`doc/VIRTUAL_FOLDERS_FEATURE.md`](VIRTUAL_FOLDERS_FEATURE.ja.md) — `PATH_SCHEMES` の全容と、レジストリブラウザーの実例
- [`doc/TEXT_VIEWER_FEATURE.md`](TEXT_VIEWER_FEATURE.ja.md) — `LEXERS` が色を付ける場所
- [`doc/dev/CUSTOMIZATION_API_IMPLEMENTATION.md`](dev/CUSTOMIZATION_API_IMPLEMENTATION.md) — 実装のしくみ
