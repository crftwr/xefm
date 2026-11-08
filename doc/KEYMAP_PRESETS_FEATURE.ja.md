# キーマッププリセット

[English](KEYMAP_PRESETS_FEATURE.md) \| 日本語

XeFM には、**プリセット** と呼ぶ完全なキーマップが 4 つあります。既定のものはなく、XeFM を初めて起動したときにどれを使うかを尋ねます。

| プリセット | 文字キー単独 | コマンドの割り当て先 |
|--------|--------------|-----------------|
| **AFX style** | コマンドを実行 | 文字キー（`C`、`M`、`K`、`V`、…） |
| **Orthodox** | ファイルを検索 | ファンクションキー（`F3`、`F5`、`F8`、…） |
| **OS native** | ファイルを検索 | Finder やエクスプローラーのキー（`Cmd`/`Ctrl`-`C`、`F2`、`Delete`、…） |
| **Vim style** | コマンドを実行 | Vim 風のキー（`hjkl`、`gg`、`yy`、`dd`、`/`、…） |

**Tools → Advanced → Keymap…** でいつでも切り替えられます。初回起動時と同じダイアログが、現在のプリセットに印が付き、Cancel ボタンがある状態で開きます。変更はすぐに反映され、ヘルプダイアログ（`F1`）、メニュー、ステータスバーに新しいキーが表示されます。選んだプリセットは次回以降のセッションでも使われます。

## 初回起動

まだプリセットを選んでいないと、XeFM はプリセットごとにボタンが並んだ **Keymap** ダイアログを表示して起動します。プリセットのないバージョンから更新した後の最初の起動でも同じです。このダイアログには Cancel がなく、`Esc` でも閉じません。続けるにはどれかを選んでください。後から Tools → Advanced → Keymap… で切り替えられます。

更新した場合で、これまで使ってきたキーをそのまま使いたいときは **AFX style** を選んでください。`config.py` に古いキーマップがまるごとコピーされている場合があります。ほかのプリセットを選ぶ前に、[以前の XeFM の config.py](#以前の-xefm-の-configpy) を読んでください。

## AFX style

1 つの文字キーで 1 つのコマンドを実行する、日本の 1 キー操作型ファイラーの流儀です。X68000 のファイルマネージャーに始まり、Windows の AFX（あふ）、そして cfiler へと受け継がれてきました。XeFM はそのどれかをキーごとに真似るのではなくこの流儀に従っているので、細かい点は AFX と異なります。たとえば削除は `K` です。

反対側のペインへのコピーと移動、削除、アーカイブの作成は、選択項目があるときだけ動作します。選択項目がないときは、同じ `M` で新しいフォルダーを作成します。すべてのキーは[下の表](#すべてのキーの一覧)にあります。

## Orthodox

古典的な 2 画面ファイルマネージャーに共通する配置です。文字キーでコマンドを実行することはありません。文字や数字を入力すると、その文字で[インクリメンタルサーチ](XEFM_USER_GUIDE.ja.md)が開き、`r` `e` `p` と打てば `report.txt` に移動します。検索は、それらのファイルマネージャーのクイックサーチと同じように閉じます。

- `↑` / `↓` で前／次の一致箇所に移動し、`Backspace` で 1 文字削除します。
- `Esc` で検索を閉じ、カーソルは一致した項目に残ります。
- **それ以外のキーを押すと、検索を閉じてそのキー本来の動作をします。** `Enter` は一致した項目を開き、`F5` はコピーし、`F3` は表示する、といった具合で、先に検索を抜けるための余分なキー操作は要りません。
- タイムアウトはありません。検索を閉じるキーを押すまで開いたままです。

一致の判定はほかのインクリメンタルサーチと同じです。入力した文字列は名前のどこにあってもよく、ローマ字で日本語の名前を探せます。I-Search キーで検索を開いた場合は、どのプリセットでもその検索独自のキーが使えます。一致した項目を順に選択でき、Enter か Esc を押すまで開いたままです。

キーは、XeFM に同じコマンドがある限り Total Commander の既定に従っています。

`F5`、`F6`、`F8` は選択した項目に対して、何も選択していなければカーソル位置の項目に対して動作します。

すべてのキーは[下の表](#すべてのキーの一覧)にあります。Total Commander にキーがないコマンドには、このプリセットでもキーがありません（表の Orthodox 列の —）。それらもコマンドパレット（`Ctrl-Shift-P`）にあり、ほとんどはメニューにもあります。キーに割り当てるには、`KEY_BINDINGS` で設定してください。

ファンクションキーと修飾キー付きのファンクションキーにはターミナルのシーケンスがあるので、この配置はデスクトップアプリだけでなくターミナルでも使えます。ただし、ターミナルがいくつかのキーを自分で使ってしまうことはあります。macOS の Terminal.app は、**Use Option as Meta key** をオンにしないと `Alt-<key>` を送りません。また、ノートパソコンのキーボードではファンクションキーに `fn` が必要な場合があります。どれかのキーが何もしないときは、割り当て直してください。

`rename` の `Ctrl-M` はデスクトップアプリで使えます。Windows では Windows Terminal と従来のコンソールウィンドウでも使えます。それ以外のターミナルは `Ctrl-M` を `Enter` として送るので、そこでは `Shift-F6` を使ってください。

## OS native

macOS の Finder と Windows のエクスプローラーが使うキーです。ほかのファイルマネージャーからではなく、それらから XeFM に移ってきた場合に使ってください。Orthodox と同じく、文字キーでコマンドを実行することはありません。文字を入力すると検索になり、これは Finder とエクスプローラーが名前でファイルを選ぶ方法と同じです。

Finder とエクスプローラーには 2 画面向けの操作がないので、それらにはどの 2 画面ファイルマネージャーでも使われるファンクションキーを使います。`F3` で表示、`F4` で編集、`F5` で反対側のペインへコピー、`F6` で移動、`F8` で削除です。macOS では、`Enter` は Finder のように名前の変更をするのではなく、ほかのプリセットと同じく開く操作になります。

**ターミナルでは。** 選んだプリセットはデスクトップアプリとターミナルの両方に適用されます。ターミナルは `Command` を送れず、`Ctrl-Shift-N` と `Ctrl-N` を区別できないので、ターミナルではこのプリセットはそれらのキーの代わりのキーを使います。[下の表](#すべてのキーの一覧)では、OS native の欄の 1 行目がターミナルでのキーで、*macOS アプリ*、*Windows アプリ* で始まる行は、そのデスクトップアプリでキーが異なる場合のキーです。それ以外は同じです。

## Vim style

Vim 風のファイルマネージャーで使われるような Vim 風のキーです。`hjkl` で移動し、`gg`、`yy`、`dd` のような 2 キーのコマンドを使い、`/` で検索します。AFX style と同じく文字キーでコマンドを実行し、文字を入力しても検索にはなりません。

すべてのキーは[下の表](#すべてのキーの一覧)にあります。

`F3`–`F8` は 2 画面ファイルマネージャーのファンクションキーに従っています。テキストビューアーでも同じように移動できます。`j` / `k` / `h` / `l`、`gg` / `G`、ページ単位の `Ctrl-F` / `Ctrl-B`（と `Ctrl-D` / `Ctrl-U`、`Space`）、`/` で検索、`q` か `ZZ` で閉じます。

2 キーのコマンドは[キーシーケンス](KEY_BINDINGS_FEATURE.ja.md#キーシーケンス)です。途中まで入力している間は、ステータスバーに最初のキー（`g …`）が表示され、`Esc` で取り消せます。最初のキーはどれも単独では何も実行しないので、`KEY_SEQUENCE_TIMEOUT` を待つことはありません。

Vim や Vim 風のファイルマネージャーとの違いは次のとおりです。

- `v` はビジュアルモードを開始しません。最も近い選択項目からカーソルまでの範囲を選択するので、`t` で始点を選択し、移動してから `v` を押します。
- `dd` はシステムのゴミ箱へ移し、`p` は `yy` でコピーしたものか `x` で切り取ったものを貼り付けます。ヤンクしたものを移動する `P` はありません。`x` で切り取ってから `p` を押してください。
- ファイル一覧では `q` 単独では何もせず、`ZZ` で終了します。テキストビューアーでは `q` でビューアーを閉じます。
- `/` は XeFM のインクリメンタルサーチで、正規表現ではなく、一致した項目を選択することもありません。

## すべてのキーの一覧

各プリセットが割り当てているすべてのキーを、XeFM 自身のキーマップの表から読み出したものです。最初の列はアクション名で、`KEY_BINDINGS` やコマンドパレットで使う名前です。どのプリセットでもキーのないアクション（次のテーマへの切り替えなど）は載せていません。メニューかコマンドパレットから実行するか、`KEY_BINDINGS` でキーを割り当ててください。XeFM の中では、`F1` で自分の `KEY_BINDINGS` を反映した実際のキーを確認できます。

- **—** は、そのプリセットにそのアクションのキーがないことを表します。
- *macOS アプリ*、*Windows アプリ* で始まる行は、そのデスクトップアプリでキーがターミナルと異なる場合のキーです。
- AFX style、Orthodox、OS native の列では、文字キーをヘルプダイアログと同じように書いています。`C` は C キー、`Shift-C` はシフトを押した C キーです。Vim style の列は Vim の書き方に従っています。`c` は C キー、`G` は `Shift-G`、`gg` は 2 回押すことを表します。
- *（選択項目があるときだけ）*、*（選択項目がないときだけ）* は AFX style の選択の条件です。`M` は選択項目を移動し、何も選択していないときは新しいフォルダーを作成します。

### ファイル一覧

| アクション名 | 動作 | AFX style | Orthodox | OS native | Vim style |
|---|---|---|---|---|---|
| **カーソルの移動** | | | | | |
| `cursor_up` | カーソルを 1 つ上へ | `↑` | `↑` | `↑` | `k`、`↑` |
| `cursor_down` | カーソルを 1 つ下へ | `↓` | `↓` | `↓` | `j`、`↓` |
| `page_up` | カーソルを 1 ページ上へ | `PgUp` | `PgUp` | `PgUp` | `Ctrl-B`、`PgUp` |
| `page_down` | カーソルを 1 ページ下へ | `PgDn` | `PgDn` | `PgDn` | `Ctrl-F`、`PgDn` |
| `half_page_up` | カーソルを半画面上へ | — | — | — | `Ctrl-U` |
| `half_page_down` | カーソルを半画面下へ | — | — | — | `Ctrl-D` |
| `cursor_top` | 先頭の項目へ | `Ctrl-Home` | `Home`、`Ctrl-Home` | `Home`、`Ctrl-Home` | `gg`、`Home`、`Ctrl-Home` |
| `cursor_bottom` | 最後の項目へ | `Ctrl-End` | `End`、`Ctrl-End` | `End`、`Ctrl-End` | `G`、`End`、`Ctrl-End` |
| `switch_pane` | 左右のペインを切り替え | `Tab` | `Tab` | `Tab` | `Tab`、`Space` |
| `nav_left` | 左のペインへ移動、または親ディレクトリへ | `←` | `←` | `←` | `←` |
| `nav_right` | 右のペインへ移動、または親ディレクトリへ | `→` | `→` | `→` | `→` |
| **フォルダーと場所** | | | | | |
| `open_item` | ファイルを開く、またはディレクトリに入る | `Enter` | `Enter`、`Ctrl-PgDn` | `Enter`<br>macOS アプリ：`Enter`、`Cmd-↓` | `l`、`gl`、`Enter` |
| `go_parent` | 親ディレクトリへ | `Backspace` | `Backspace`、`Ctrl-PgUp` | `Backspace`、`Alt-↑`<br>macOS アプリ：`Cmd-↑`、`Backspace`、`Opt-↑` | `h`、`gh`、`Backspace` |
| `go_root` | 現在のドライブや場所のルートへ | `\` | `Ctrl-\` | `\` | `\` |
| `go_back` | 前に表示していたディレクトリへ戻る | `Alt-←`<br>macOS アプリ：`Cmd-[`、`Opt-←` | `Alt-←` | `Alt-←`<br>macOS アプリ：`Cmd-[`、`Opt-←` | `Ctrl-O`、`Alt-←` |
| `go_forward` | 戻ったあと、もう一度進む | `Alt-→`<br>macOS アプリ：`Cmd-]`、`Opt-→` | `Alt-→` | `Alt-→`<br>macOS アプリ：`Cmd-]`、`Opt-→` | `Alt-→` |
| `history` | 最近訪れたディレクトリへ | `H` | `Alt-↓` | `Alt-↓` | — |
| `jump_to_path` | 入力したパスへ移動 | `Shift-J` | — | `Ctrl-L`、`Alt-D`<br>macOS アプリ：`Cmd-Shift-G`、`Ctrl-L` | `gp` |
| `favorites` | お気に入りのディレクトリやファイルへ | `J` | `Ctrl-D` | — | `'` |
| `add_favorite` | お気に入りに追加、または選択項目にタグを付ける | `B` | — | — | — |
| `drives` | ドライブとボリュームを表示 | `D` | `Alt-F1`、`Alt-F2` | — | — |
| `connect_server` | ネットワーク上のサーバーへ接続 | `Shift-D` | `Ctrl-F`、`Ctrl-N` | — | — |
| `open_with_os` | OS の既定のアプリで開く | `Ctrl-O`<br>macOS アプリ：`Cmd-Enter`、`Ctrl-O`<br>Windows アプリ：`Ctrl-Enter`、`Ctrl-O` | `Ctrl-O`<br>macOS アプリ：`Cmd-Enter`、`Ctrl-O`<br>Windows アプリ：`Ctrl-Enter`、`Ctrl-O` | `Ctrl-O`<br>macOS アプリ：`Cmd-Enter`、`Ctrl-O`<br>Windows アプリ：`Ctrl-Enter`、`Ctrl-O` | `gx` |
| `reveal_in_os` | OS のファイルマネージャーで表示 | `Ctrl-R` | — | — | `Ctrl-R` |
| `sync_current_to_other` | 反対側のペインのディレクトリへ移動 | `O` | — | — | — |
| `sync_other_to_current` | このディレクトリを反対側のペインに表示 | `Shift-O` | — | — | — |
| **選択** | | | | | |
| `toggle_select_down` | 選択を切り替えて下へ移動 | `Space` | `Insert`、`Space` | `Space`、`Insert`<br>macOS アプリ：`Ctrl-Space`、`Insert` | `Insert` |
| `toggle_select_in_place` | カーソルを動かさずに選択を切り替え | — | — | — | `t` |
| `select_range` | 最も近い選択項目からカーソル位置までを選択 | `Shift-Space` | `Shift-Space` | `Shift-Space` | `v`、`Shift-Space` |
| `select_all` | すべての項目を選択 | `Home` | `Ctrl-A` | `Ctrl-A`<br>macOS アプリ：`Cmd-A`、`Ctrl-A` | — |
| `unselect_all` | 選択をすべて解除 | `End` | `Ctrl--` | — | `Esc` |
| `toggle_select_files` | すべてのファイルの選択を切り替え | `A` | `*` | — | — |
| `toggle_select_items` | すべての項目の選択を切り替え | `Shift-A` | — | — | — |
| `select_by_pattern` | パターンに合うファイルを選択 | `'` | `+` | `'` | — |
| `unselect_by_pattern` | パターンに合うファイルの選択を解除 | `"` | `-` | `"` | `"` |
| `select_same_extension` | カーソル位置のファイルと同じ拡張子のファイルをすべて選択 | — | `Alt-+` | — | — |
| `compare_selection` | 反対側のペインと比較して選択 | `W` | `Shift-F2` | — | — |
| `cursor_next_selected` | 次の選択項目へ | `Ctrl-↓` | — | `Ctrl-↓` | `Ctrl-↓` |
| `cursor_prev_selected` | 前の選択項目へ | `Ctrl-↑` | — | `Ctrl-↑` | `Ctrl-↑` |
| **ファイル操作** | | | | | |
| `copy_files` | 選択項目を反対側のペインへコピー | `C`（選択項目があるときだけ） | `F5` | `F5` | `F5` |
| `move_files` | 選択項目を反対側のペインへ移動 | `M`（選択項目があるときだけ） | `F6` | `F6` | `F6` |
| `copy_files_to` | 選択項目を入力したディレクトリへコピー | `Shift-C`（選択項目があるときだけ） | — | — | — |
| `move_files_to` | 選択項目を入力したディレクトリへ移動 | `Shift-M`（選択項目があるときだけ） | — | — | — |
| `duplicate_files` | 選択項目をその場で複製 | — | `Shift-F5` | — | — |
| `delete_files` | 選択項目をゴミ箱へ（ゴミ箱がない場所では削除） | `K`、`Del`（選択項目があるときだけ） | `F8`、`Del` | `Del`、`F8`<br>macOS アプリ：`Cmd-Backspace`、`Del`、`F8` | `dd`、`Del`、`F8` |
| `delete_permanently` | 選択項目をゴミ箱を使わずに削除 | `Shift-K`、`Shift-Del`（選択項目があるときだけ） | `Shift-F8`、`Shift-Del` | `Shift-Del`、`Shift-F8`<br>macOS アプリ：`Cmd-Opt-Backspace`、`Shift-Del`、`Shift-F8` | `DD`、`Shift-Del`、`Shift-F8` |
| `rename` | カーソル位置の項目の名前を変更、選択項目は一括リネーム | `R` | `Shift-F6`、`Ctrl-M` | `F2` | `cw` |
| `rename_in_editor` | 選択項目の名前を TEXT_EDITOR で編集して変更 | `Shift-R` | — | — | — |
| `create_file` | 新しいファイルを作成 | `Shift-E` | `Shift-F4` | — | — |
| `create_directory` | 新しいディレクトリを作成 | `M`（選択項目がないときだけ） | `F7` | `F7`<br>macOS アプリ：`Cmd-Shift-N`、`F7`<br>Windows アプリ：`Ctrl-Shift-N`、`F7` | `F7` |
| `create_archive` | 選択項目からアーカイブを作成 | `P`（選択項目があるときだけ） | `Alt-F5` | — | — |
| `extract_archive` | 選択したアーカイブを展開 | `U` | `Alt-F9`、`Alt-F6` | — | — |
| **ファイルクリップボードと名前のコピー** | | | | | |
| `clipboard_copy` | ファイルをクリップボードへコピー | `Ctrl-C`、`Y`<br>macOS アプリ：`Cmd-C`、`Ctrl-C`、`Y` | `Ctrl-C` | `Ctrl-C`<br>macOS アプリ：`Cmd-C`、`Ctrl-C` | `yy`、`Ctrl-C` |
| `clipboard_cut` | ファイルをクリップボードへ切り取り | `Ctrl-X`、`Shift-Y`<br>macOS アプリ：`Cmd-X`、`Ctrl-X`、`Shift-Y` | `Ctrl-X` | `Ctrl-X`<br>macOS アプリ：`Cmd-X`、`Ctrl-X` | `x`、`Ctrl-X` |
| `clipboard_paste` | クリップボードの内容をこのフォルダーに貼り付け | `Ctrl-V`、`G`<br>macOS アプリ：`Cmd-V`、`Ctrl-V`、`G` | `Ctrl-V` | `Ctrl-V`<br>macOS アプリ：`Cmd-V`、`Ctrl-V` | `p`、`Ctrl-V` |
| `copy_names` | ファイル名をクリップボードへコピー | `Ctrl-N` | — | `Ctrl-N` | `Ctrl-N` |
| `copy_paths` | フルパスをクリップボードへコピー | `Ctrl-P` | `Ctrl-P` | `Ctrl-P`<br>macOS アプリ：`Cmd-Opt-C`、`Ctrl-P`<br>Windows アプリ：`Ctrl-Shift-C`、`Ctrl-P` | `Ctrl-P` |
| **表示・編集・比較** | | | | | |
| `view_file` | カーソル位置のファイルを内蔵ビューアーで表示 | `V` | `F3` | `F3` | `e`、`F3` |
| `quick_view` | カーソル位置の項目を反対側のペインでプレビュー | `Shift-V` | `Ctrl-Q` | `Alt-P`<br>macOS アプリ：`Space`、`Opt-P` | `w` |
| `edit_file` | 設定したテキストエディターで編集 | `E` | `F4` | `F4` | `F4` |
| `file_details` | カーソル位置の項目の詳細を表示 | `I` | `Alt-Enter` | `Alt-I`<br>macOS アプリ：`Cmd-I`、`Opt-I`<br>Windows アプリ：`Alt-Enter`、`Alt-I` | `Ctrl-G` |
| `diff_files` | 2 つのファイルを左右に並べて比較 | `=` | `=` | `=` | — |
| `diff_directories` | 2 つのディレクトリを再帰的に比較 | `Shift-=` | — | `Shift-=` | `Shift-=` |
| **検索・フィルター・ソート** | | | | | |
| `isearch` | インクリメンタルサーチ | `F` | — | — | `/` |
| `search_next` | 直前のインクリメンタルサーチの次の一致へ | — | — | — | `n` |
| `search_prev` | 直前のインクリメンタルサーチの前の一致へ | — | — | — | `N` |
| `find_files` | ファイル名で検索 | `Shift-F` | `Alt-F7` | `Ctrl-F`<br>macOS アプリ：`Cmd-F`、`Ctrl-F` | — |
| `find_in_files` | ファイルの内容を検索 | `Shift-G` | — | — | — |
| `index_search` | このフォルダー以下を OS のインデックスで検索 | `Ctrl-F` | — | — | — |
| `filter` | ファイル名のパターンで一覧を絞り込み | `;` | `Ctrl-S` | `;` | `=` |
| `clear_filter` | ファイル名のフィルターを解除 | `:` | `Ctrl-F10` | `:` | `zr` |
| `flat_view` | このディレクトリ以下のすべてのファイルを 1 つの一覧で表示 | `Shift-B` | `Ctrl-B` | — | — |
| `toggle_hidden` | 隠しファイルの表示を切り替え | `.` | `.` | `.`<br>macOS アプリ：`Cmd-Shift-.`、`.` | `za` |
| `increase_font_size` | XeFM を終了するまで文字を大きくする | macOS アプリ：`Cmd-+`、`Cmd-=`<br>Windows アプリ：`Ctrl-+`、`Ctrl-=` | macOS アプリ：`Cmd-+`、`Cmd-=` | macOS アプリ：`Cmd-+`、`Cmd-=`<br>Windows アプリ：`Ctrl-+`、`Ctrl-=` | macOS アプリ：`Cmd-+`、`Cmd-=`<br>Windows アプリ：`Ctrl-+`、`Ctrl-=` |
| `decrease_font_size` | XeFM を終了するまで文字を小さくする | macOS アプリ：`Cmd--`<br>Windows アプリ：`Ctrl--` | macOS アプリ：`Cmd--` | macOS アプリ：`Cmd--`<br>Windows アプリ：`Ctrl--` | macOS アプリ：`Cmd--`<br>Windows アプリ：`Ctrl--` |
| `reset_font_size` | 文字の大きさを `FONT_SIZE` に戻す | macOS アプリ：`Cmd-0`<br>Windows アプリ：`Ctrl-0` | macOS アプリ：`Cmd-0`<br>Windows アプリ：`Ctrl-0` | macOS アプリ：`Cmd-0`<br>Windows アプリ：`Ctrl-0` | macOS アプリ：`Cmd-0`<br>Windows アプリ：`Ctrl-0` |
| `sort` | ソートダイアログを開く | `S` | — | — | `S` |
| `quick_sort_name` | 名前でソート | `1` | `Ctrl-F3` | — | — |
| `quick_sort_ext` | 拡張子でソート | `2` | `Ctrl-F4` | — | — |
| `quick_sort_size` | サイズでソート | `3` | `Ctrl-F6` | — | — |
| `quick_sort_date` | 更新日時でソート | `4` | `Ctrl-F5` | — | — |
| **タブ・ペイン・ログ** | | | | | |
| `new_tab` | このペインの同じ場所に新しいタブを開く | `T` | `Ctrl-T` | `Ctrl-T`<br>macOS アプリ：`Cmd-T`、`Ctrl-T` | — |
| `open_in_new_tab` | カーソル位置のディレクトリを新しいタブで開く | `Shift-T` | `Ctrl-↑` | — | — |
| `close_tab` | このペインの現在のタブを閉じる | `Ctrl-W` | `Ctrl-W` | `Ctrl-W`<br>macOS アプリ：`Cmd-W`、`Ctrl-W` | `Ctrl-W` |
| `next_tab` | このペインの次のタブへ | `Ctrl-PgDn` | `Ctrl-Tab` | `Ctrl-PgDn` | `Ctrl-PgDn` |
| `prev_tab` | このペインの前のタブへ | `Ctrl-PgUp` | `Ctrl-Shift-Tab` | `Ctrl-PgUp` | `Ctrl-PgUp` |
| `adjust_pane_left` | 左のペインを狭く | `[` | `[` | `[` | `[` |
| `adjust_pane_right` | 左のペインを広く | `]` | `]` | `]` | `]` |
| `reset_pane_boundary` | ペインの境界を中央に戻す | `-` | — | `-` | `-` |
| `adjust_log_up` | ログペインを広く | `{` | `{` | `{` | `{` |
| `adjust_log_down` | ログペインを狭く | `}` | `}` | `}` | `}` |
| `reset_log_height` | ログペインの高さを元に戻す | `_` | — | `_` | `_` |
| `scroll_log_up` | ログを 1 行上へスクロール | `Shift-↑` | `Shift-↑` | `Shift-↑` | `Shift-↑` |
| `scroll_log_down` | ログを 1 行下へスクロール | `Shift-↓` | `Shift-↓` | `Shift-↓` | `Shift-↓` |
| `scroll_log_page_up` | ログを 1 ページ上へスクロール | `Shift-←` | `Shift-←` | `Shift-←` | `Shift-←` |
| `scroll_log_page_down` | ログを 1 ページ下へスクロール | `Shift-→` | `Shift-→` | `Shift-→` | `Shift-→` |
| **メニュー・ツール・終了** | | | | | |
| `help` | 画面に表示中のもののキーバインドを表示 | `F1` | `F1` | `F1` | `F1` |
| `command_palette` | すべてのアクションを名前で探して実行 | `Ctrl-T` | `Ctrl-Shift-P` | `Ctrl-K`<br>macOS アプリ：`Cmd-Shift-P`、`Ctrl-K`<br>Windows アプリ：`Ctrl-Shift-P`、`Ctrl-K` | `:`、`Ctrl-T` |
| `menu` | メニューバーを開く | `F10`、`Alt` | `F9`、`F10`、`Alt` | `F10`、`Alt` | `F10`、`Alt` |
| `context_menu` | カーソル位置の項目のコンテキストメニューを開く | `/`、`Apps` | `Shift-F10`、`Apps` | `Shift-F10`、`Apps` | `Apps`、`Shift-F10` |
| `context_menu_dir` | 現在のディレクトリのコンテキストメニューを開く | `?`、`Shift-Apps` | `?`、`Shift-Apps` | `?`、`Shift-Apps` | `?`、`Shift-Apps` |
| `programs` | 外部プログラムを実行 | `X` | — | — | — |
| `subshell` | このディレクトリでサブシェルを開く | `Shift-X` | — | — | `s` |
| `jobs` | バックグラウンドジョブの一覧 | `Ctrl-G` | `Ctrl-G` | `Ctrl-G` | — |
| `reread` | 両方のペインのディレクトリを読み直す | — | `F2`、`Ctrl-R` | `Ctrl-R` | `Ctrl-L` |
| `redraw` | 画面を再描画 | `F5` | — | — | — |
| `quit` | XeFM を終了、またはビューアーを閉じる | `Q` | `Alt-F4` | `Ctrl-Q` | `ZZ`、`ZQ` |
| `quit_app` | どこからでも XeFM を終了（タスクの実行中だけ確認） | macOS アプリ：`Cmd-Q`<br>Windows アプリ：`Alt-F4` | macOS アプリ：`Cmd-Q`<br>Windows アプリ：`Alt-F4` | macOS アプリ：`Cmd-Q`<br>Windows アプリ：`Alt-F4` | macOS アプリ：`Cmd-Q`<br>Windows アプリ：`Alt-F4` |

### ビューアーとダイアログ

ここに挙げたキーは、欄に断りがない限りどのプリセットでも同じです。どのビューアーも `Esc` で閉じ、`quit`、`help`、`isearch`、`edit_file` はファイル一覧の表と同じキーで使えます。Vim style では、テキストビューアーを `q` でも閉じられます。

Orthodox と OS native では、ファイル一覧で文字を入力すると検索になるので、`isearch` にキーがありません。代わりにテキストビューアーとファイル差分ビューアーでは、手本にしているビューアーの検索キーを使います。Orthodox は Total Commander の Lister、OS native は各プラットフォーム標準の検索キーです。「次を検索」と「前を検索」は検索バーを開いている間も使え、バーを閉じたあとに押すと、直前の検索でバーを開き直して次または前の一致へ移動します。

**テキストビューアー**

| アクション名 | 動作 | キー |
|---|---|---|
| `text_viewer.scroll_up` | 1 行上へスクロール | AFX style、Orthodox、OS native：`↑`<br>Vim style：`k`、`↑` |
| `text_viewer.scroll_down` | 1 行下へスクロール | AFX style、Orthodox、OS native：`↓`<br>Vim style：`j`、`↓` |
| `text_viewer.page_up` | 1 ページ上へスクロール | AFX style、Orthodox、OS native：`PgUp`<br>Vim style：`Ctrl-B`、`Ctrl-U`、`PgUp` |
| `text_viewer.page_down` | 1 ページ下へスクロール | AFX style、Orthodox、OS native：`PgDn`<br>Vim style：`Ctrl-F`、`Ctrl-D`、`PgDn`、`Space` |
| `text_viewer.scroll_top` | 先頭へ | AFX style、Orthodox、OS native：`Home`<br>Vim style：`gg`、`Home` |
| `text_viewer.scroll_bottom` | 末尾へ | AFX style、Orthodox、OS native：`End`<br>Vim style：`G`、`End` |
| `text_viewer.scroll_left` | 左へスクロール（折り返しなしのとき） | AFX style、Orthodox、OS native：`←`<br>Vim style：`h`、`←` |
| `text_viewer.scroll_right` | 右へスクロール（折り返しなしのとき） | AFX style、Orthodox、OS native：`→`<br>Vim style：`l`、`→` |
| `toggle_wrap` | 行の折り返しを切り替え | `W` |
| `toggle_view_mode` | 整形表示と生テキスト表示を切り替え | `M` |
| `change_encoding` | テキストのエンコーディングを選ぶ | `Shift-E` |
| `isearch` | インクリメンタルサーチ | AFX style：`F`<br>Orthodox：`F7`<br>OS native：`Ctrl-F`（macOS アプリ：`Cmd-F`、`Ctrl-F`）<br>Vim style：`/` |
| `text_viewer.search_next` | 直前の検索の次の一致へ | AFX style、Vim style：—<br>Orthodox：`F3`<br>OS native：`F3`（macOS アプリ：`Cmd-G`、`F3`） |
| `text_viewer.search_prev` | 直前の検索の前の一致へ | AFX style、Vim style：—<br>Orthodox：`Shift-F3`<br>OS native：`Shift-F3`（macOS アプリ：`Cmd-Shift-G`、`Shift-F3`） |

**画像ビューアー**

| アクション名 | 動作 | キー |
|---|---|---|
| `image_viewer.next` | ファイル一覧の次の画像 | `↓` |
| `image_viewer.prev` | ファイル一覧の前の画像 | `↑` |
| `image_viewer.first` | ファイル一覧の最初の画像 | `Home` |
| `image_viewer.last` | ファイル一覧の最後の画像 | `End` |
| `image_viewer.zoom_in` | 拡大 | `+`、`=` |
| `image_viewer.zoom_out` | 縮小 | `-`、`_` |
| `image_viewer.zoom_reset` | 画像全体をウィンドウに合わせる | `0` |
| `image_viewer.pan_up` | 上へスクロール（拡大中） | `Shift-↑` |
| `image_viewer.pan_down` | 下へスクロール（拡大中） | `Shift-↓` |
| `image_viewer.pan_left` | 左へスクロール（拡大中） | `Shift-←` |
| `image_viewer.pan_right` | 右へスクロール（拡大中） | `Shift-→` |

**ファイル差分ビューアー**

| アクション名 | 動作 | キー |
|---|---|---|
| `file_diff.next_block` | 次の差分ブロック | `n` |
| `file_diff.prev_block` | 前の差分ブロック | `Shift-N` |
| `file_diff.scroll_up` | 1 行上へスクロール | `↑` |
| `file_diff.scroll_down` | 1 行下へスクロール | `↓` |
| `file_diff.page_up` | 1 ページ上へスクロール | `PgUp` |
| `file_diff.page_down` | 1 ページ下へスクロール | `PgDn` |
| `file_diff.scroll_top` | 先頭へ | `Home` |
| `file_diff.scroll_bottom` | 末尾へ | `End` |
| `file_diff.scroll_left` | 左へスクロール | `←` |
| `file_diff.scroll_right` | 右へスクロール | `→` |
| `isearch` | インクリメンタルサーチ | AFX style：`F`<br>Orthodox：`F7`<br>OS native：`Ctrl-F`（macOS アプリ：`Cmd-F`、`Ctrl-F`）<br>Vim style：`/` |
| `file_diff.search_next` | 直前の検索の次の一致へ | AFX style、Vim style：—<br>Orthodox：`F3`<br>OS native：`F3`（macOS アプリ：`Cmd-G`、`F3`） |
| `file_diff.search_prev` | 直前の検索の前の一致へ | AFX style、Vim style：—<br>Orthodox：`Shift-F3`<br>OS native：`Shift-F3`（macOS アプリ：`Cmd-Shift-G`、`Shift-F3`） |

**ディレクトリ差分ビューアー**

| アクション名 | 動作 | キー |
|---|---|---|
| `dir_diff.cursor_up` | カーソルを上へ | `↑` |
| `dir_diff.cursor_down` | カーソルを下へ | `↓` |
| `dir_diff.page_up` | カーソルを 1 ページ上へ | `PgUp` |
| `dir_diff.page_down` | カーソルを 1 ページ下へ | `PgDn` |
| `dir_diff.cursor_top` | 先頭の行へ | `Home` |
| `dir_diff.cursor_bottom` | 最後の行へ | `End` |
| `dir_diff.expand` | カーソル位置のディレクトリを開く | `→` |
| `dir_diff.collapse` | ディレクトリを閉じる、または親へ | `←` |
| `dir_diff.activate` | ディレクトリを開く、またはファイルの差分を表示 | `Enter` |
| `dir_diff.switch_side` | アクティブな側を切り替え | `Tab` |
| `dir_diff.next_change` | 次の差分 | `n` |
| `dir_diff.prev_change` | 前の差分 | `Shift-N` |
| `dir_diff.rescan` | 両方のツリーを読み直す | `r` |
| `dir_diff.split_left` | 中央の境界を左へ | `[` |
| `dir_diff.split_right` | 中央の境界を右へ | `]` |
| `dir_diff.toggle_identical` | 両側で同じ項目の表示を切り替え | `d` |
| `dir_diff.sync` | 同期：アクティブな側から計画を作る、または実行する | `s` |
| `dir_diff.cycle_sync_action` | カーソル位置の項目の同期方法を切り替え | `Space` |
| `copy_files` | 選択項目を反対側のペインへコピー | AFX style：`C`（選択項目があるときだけ）<br>Orthodox、OS native、Vim style：`F5` |
| `move_files` | 選択項目を反対側のペインへ移動 | AFX style：`M`（選択項目があるときだけ）<br>Orthodox、OS native、Vim style：`F6` |
| `delete_files` | 選択項目をゴミ箱へ（ゴミ箱がない場所では削除） | AFX style：`K`、`Del`（選択項目があるときだけ）<br>Orthodox：`F8`、`Del`<br>OS native：`Del`、`F8`（macOS アプリ：`Cmd-Backspace`、`Del`、`F8`）<br>Vim style：`dd`、`Del`、`F8` |
| `view_file` | カーソル位置のファイルを内蔵ビューアーで表示 | AFX style：`V`<br>Orthodox、OS native：`F3`<br>Vim style：`e`、`F3` |

**インクリメンタルサーチのバー**

| アクション名 | 動作 | キー |
|---|---|---|
| `isearch.next_match` | 次の一致へ | `↓` |
| `isearch.prev_match` | 前の一致へ | `↑` |
| `isearch.toggle_select_down` | 選択を切り替えて次の一致へ | `Ctrl-Space` |
| `isearch.select_matches` | すべての一致を選択（もう一度押すと解除） | `Ctrl-A` |
| `isearch.accept` | 現在の一致で止める | `Enter` |
| `isearch.cancel` | 取り消してカーソルを元に戻す | `Esc` |

**一覧ダイアログ**（お気に入り、ドライブ、履歴、外部プログラム、フィルターの入力）

| アクション名 | 動作 | キー |
|---|---|---|
| `remove_list_item` | ハイライト中の項目を一覧から削除 | `Shift-Del` |
| `describe_list_item` | ハイライト中の項目のヘルプを表示 | `F1` |

**検索ダイアログ**（ファイル名検索、内容検索）

| アクション名 | 動作 | キー |
|---|---|---|
| `options` | 検索オプションを開く | `Ctrl-O`、`F9` |

## 自分のキーバインドが優先される

`config.py` の `KEY_BINDINGS` には、プリセットに対する **自分の変更** を書きます。どのエントリも、どのプリセットを使っていても、そのアクションのキーを置き換えます。書かなかったアクションはプリセットのキーのままです。XeFM が新しい `config.py` に書き込む `KEY_BINDINGS` が、コメントアウトされた例だけになっているのはそのためです。

自分で割り当てたキーは、プリセットがそのキーを割り当てていたアクションからも外されるので、そのアクションを探して空にする必要はありません。`'toggle_color_scheme': ['Shift-T']` だけで十分です。AFX の `Shift-T`（新しいタブで開く）は反応しなくなり、ヘルプやメニューにもそこでは表示されなくなります。

ファイル一覧だけに割り当てたキーは、共通のアクションではほかの場所にもそのまま残ります。`'view_file': ['Q']` にすると、ファイル一覧では `Q` でファイルが開き、ビューアーでは `Q` で閉じるのも変わりません。選択の条件を付けて割り当てたキーは、反対の条件のものには影響しません。`{'keys': ['C'], 'selection': 'none'}` としても、選択したファイルを `C` でコピーする動作は残ります。

```python
KEY_BINDINGS = {
    'reload_config': ['F12'],   # F12 reloads the config, under every preset
    'quit': [],                 # nothing quits by key
}
```

### 以前の XeFM の config.py

プリセットができる前は、`config.py` に AFX style の表全体のコピーが書かれていました。AFX style のもとでは、このコピーは何も変えません。ほかのプリセットのもとでは、その中のすべてのエントリがプリセットのキーを置き換えるので、`C` は検索ではなくコピーのままになります。プリセットを切り替えると、`config.py` がいくつのアクションを置き換えているかがログに表示され、最初のいくつかの名前も示されます。

ほかのプリセットを使うには、変更するつもりのなかったエントリを削除してください。キーを一度も変更していないなら、すべて削除して `KEY_BINDINGS = {}` にしてください。

## config.py で選ぶ

```python
KEY_PRESET = 'orthodox'   # or 'afx', 'native', or 'vim'
```

このプリセットの最初の名前だった `'default'` も引き続き使え、`'afx'` を意味します。

`config.py` の `KEY_PRESET` はメニューより優先され、メニューで変えようとするとその旨が表示されます。初回起動時の質問も省略されます。ダイアログとメニューで決めたいときは `None` のままにしてください。

## 関連項目

- [キーバインド](KEY_BINDINGS_FEATURE.ja.md)：個々のキーの変更
- [コマンドパレット](COMMAND_PALETTE_FEATURE.ja.md)：あらゆるコマンドとそのキーを探す
