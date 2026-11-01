# メニューバー

[English](MENU_BAR_FEATURE.md) \| 日本語

## 概要

デスクトップ（GUI）モードでは、XeFM はネイティブのメニューバーを表示するので、キーボードに加えてマウスでもファイルマネージャーを操作できます。メニューは XeFM のキーボードアクションをそのまま反映しています。どのメニュー項目もキーバインドと同じアクションを実行し、各項目のショートカット表示は **現在のキーマップから** 生成されます。そのため、`~/.xefm/config.py` でキーを割り当て直すと、メニューもそれに合わせて更新されます。

## 対応プラットフォーム

- **macOS のデスクトップモード**：ネイティブの `NSMenu` メニューバー。
- **Windows のデスクトップモード**：ウィンドウのネイティブの Win32 メニューバー。
- **ターミナルモード**：ウィンドウ内の最上行に並ぶメニュー帯。

メニューの構成とショートカットはどれでも同じです。

## メニューバーを使う

### デスクトップモードを起動する

インストールした **XeFM** アプリを、macOS では Launchpad か Spotlight から、Windows ではスタートメニューから開きます。[デスクトップモードガイド](DESKTOP_MODE_GUIDE.ja.md#デスクトップアプリのパッケージのインストール)を参照してください。（XeFM の開発中は、チェックアウトから `python3 -m xefm --backend gui` で同じウィンドウを開けます。）

### メニューバーの操作

- **マウス**：メニューのタイトルをクリックし、項目をクリックします。
- **キーボード**：どの項目も、メニューを開かずに、そのショートカット（項目の横に表示されます）で直接実行できます。

### キーボードでメニューを開く（ターミナルモード）

ターミナルモードでは、`menu` アクションで最初のメニューが開きます（Windows のターミナルでは、デスクトップのメニューバーと同じく、**Alt** を単独で押して離すことでも開けます）。Windows のターミナルでは、**Alt+文字** でメニューのタイトルの頭文字から直接メニューを開けます。File は **Alt+F**、Edit は **Alt+E**、Go は **Alt+G**、Select は **Alt+S**、View は **Alt+V**、Tools は **Alt+T**、Help は **Alt+H** です。（ほかのターミナルでは、Alt 単独や Alt+文字の組み合わせが確実には届きません。そこでは `menu` アクションと矢印キーを使ってください。）

メニューを開いている間は次のキーが使えます。

- **←/→** でバー上のメニュー間を移動し（端で反対側に回り込みます）、**Alt+文字** でそのメニューへ直接移動します。
- **↑/↓** で開いているメニュー内を移動します。
- **文字だけ** を押すと、頭文字で項目を選びます。一致が 1 つならすぐに実行し、複数あればハイライトがそれらを順にたどります（目的の項目で Enter を押します）。
- サブメニューのある項目で **→** を押すとサブメニューが開き、**←** で抜けます。
- **Enter** でハイライトされた項目を実行します。
- **Esc**（あるいはもう一度 `menu` のキーを押すか、ほかの場所をクリック）でメニューを閉じます。

メニューを開くキーは `~/.xefm/config.py` の `menu` アクションなので、ほかのアクションと同じように割り当て直せます。独自に `Alt-<letter>` の組み合わせを割り当てた場合は、そちらがメニューのアクセラレーターより優先されます。デスクトップモードでは、OS のメニューバーがキーボード操作をネイティブに処理します（Windows では Alt）。

## 使えるメニュー

XeFM には **File**、**Edit**、**Go**、**Select**、**View**、**Tools**、**Help** の 7 つのメニューがあります。Windows のターミナルでは、どれも Alt とその頭文字で直接開けます。

各項目には、そのアクションに実際に割り当てられているキーが表示されます。そのため、以下の表ではキーの代わりに **アクション** を示しています。キーは `F1` を押すか、メニューを見て確認してください。どのアクションにどのキーがあるかはキーマッププリセットによって異なります。[キーマッププリセット](KEYMAP_PRESETS_FEATURE.ja.md#すべてのキーの一覧)を参照してください。

### File メニュー

| 項目 | アクション |
|------|--------|
| Open | `open_item` |
| Open With ▸ Viewer | `view_file` |
| Open With ▸ Text Editor | `edit_file` |
| Open With ▸ Default App | `open_with_os` |
| Open With ▸ Choose App… | `open_with` — [アプリケーションを選んで開く](OPEN_WITH_FEATURE.ja.md)を参照 |
| Details… | `file_details` |
| Reveal in File Manager | `reveal_in_os` |
| New Folder… | `create_directory` *（何も選択していないとき）* |
| New File… | `create_file` |
| Rename ▸ Rename… | `rename` |
| Rename ▸ Rename in Editor… | `rename_in_editor` |
| Duplicate | `duplicate_files` |
| Copy to Other Pane | `copy_files` |
| Move to Other Pane | `move_files` *（ファイルを選択しているとき）* |
| Copy to… | `copy_files_to` |
| Move to… | `move_files_to` |
| Move to Trash… / Move to Recycle Bin… | `delete_files` — [ゴミ箱](TRASH_FEATURE.ja.md)を参照 |
| Delete Permanently… | `delete_permanently` |
| Archive ▸ Create… | `create_archive` |
| Archive ▸ Extract… | `extract_archive` |
| *（`'file'` を指定した自分の `MENU_ITEMS`）* | 3 つまではここに並び、それより多いと **Custom ▸** の下にまとまる |
| Quit | `quit` |

### Edit メニュー

クリップボードに入るものはすべてここにあります。

| 項目 | アクション |
|------|--------|
| Copy | `clipboard_copy` — [ファイルクリップボード](FILE_CLIPBOARD_FEATURE.ja.md)を参照 |
| Cut | `clipboard_cut` |
| Paste | `clipboard_paste` |
| Show Clipboard… | `clipboard_show` *（既定でキー未割り当て）* |
| Clear Clipboard | `clipboard_clear` *（既定でキー未割り当て）* |
| Copy Name(s) | `copy_names` |
| Copy Full Path(s) | `copy_paths` |
| Copy Log Selection | `copy_log_selection` *（既定でキー未割り当て。ログに選択範囲があるときは Copy のキーがこれを行います）* |
| Copy All Logs | `copy_log_all` *（既定でキー未割り当て）* |

ログの項目は、ファイルペインの下にあるログペインに対して働きます。前者はマウスで選択したログのテキストを、後者はバッファー全体を取り込みます。[ログ](LOGGING_FEATURE.ja.md#ログをクリップボードにコピーする)を参照してください。

### Go メニュー

| 項目 | アクション |
|------|--------|
| Parent Directory | `go_parent` |
| Root Directory | `go_root` |
| Go to Favorite… | `favorites` |
| Add to Favorites… | `add_favorite` |
| Jump to Path… | `jump_to_path` |
| Drives… | `drives` |
| Connect to Server… | `connect_server` |
| History… | `history` |
| Back | `go_back` |
| Forward | `go_forward` |
| Switch Pane | `switch_pane` |
| New Tab | `new_tab` — [フォルダータブ](FOLDER_TABS_FEATURE.ja.md)を参照 |
| Open in New Tab | `open_in_new_tab` |
| Close Tab | `close_tab` |
| Next Tab | `next_tab` |
| Previous Tab | `prev_tab` |
| Open List → From Clipboard | `open_list_from_clipboard` *（既定でキー未割り当て）* — [ファイルリスト](FILE_LIST_IMPORT_FEATURE.ja.md)を参照 |
| Open List → From Command… | `open_list_from_command` *（既定でキー未割り当て）* |
| Open List → From File | `open_list_from_file` *（既定でキー未割り当て）* — ファイルの右クリックメニューの **Open as List** でも可 |

### Select メニュー

| 項目 | アクション |
|------|--------|
| Toggle Selection | `toggle_select_down` |
| Select to Cursor | `select_range` |
| Select All Items | `select_all` |
| Clear Selection | `unselect_all` |
| Select by Pattern… | `select_by_pattern` — [パターンで選択](SELECT_BY_PATTERN_FEATURE.ja.md)を参照 |
| Unselect by Pattern… | `unselect_by_pattern` |
| Select Same Extension | `select_same_extension` |
| Compare and Select… | `compare_selection` |
| Compare Selected Files… | `diff_files` |
| Compare Directories… | `diff_directories` |

### View メニュー

| 項目 | アクション |
|------|--------|
| Find… | `isearch` |
| Filter… | `filter` |
| Search Files… | `find_files` |
| Search Content… | `find_in_files` |
| Search Spotlight… / Search Windows Search… | `index_search` — [OS のインデックス検索](OS_INDEX_SEARCH_FEATURE.ja.md)を参照 |
| Search Tags… | `find_by_tag` *（既定でキー未割り当て）* — [ファイルのタグ](FILE_TAGS_FEATURE.ja.md)を参照 |
| Reread | `reread` |
| Show Hidden Files | `toggle_hidden` |
| Layout ▸ | （サブメニュー：すべてのレイアウト。`choose_layout` でも可）— [ファイルリストのレイアウト](FILE_LIST_LAYOUTS_FEATURE.ja.md)を参照 |
| Show ▸ | （サブメニュー：追加の情報ごとの Auto / On / Off。Tags と、`LAYOUT_EXTRAS` や拡張パッケージが加えるもの。`choose_extras` でも可） |
| Resolve Attribute… | `resolve_attribute` *（既定でキー未割り当て）* — フォルダーの合計サイズなど、頼まれたときだけ求める属性。[ファイルリストのレイアウト](FILE_LIST_LAYOUTS_FEATURE.ja.md)を参照 |
| Sort By ▸ | （サブメニュー：Name / Extension / Size / Date。`quick_sort_*` アクションでも可。その下に Reverse Sort（メニューのみ）） |
| Theme ▸ | （サブメニュー：Next Theme（`toggle_color_scheme`、*既定でキー未割り当て*）、その下にインストール済みのテーマ） |
| Quick View | `quick_view` — [クイックビュー](QUICK_VIEW_FEATURE.ja.md)を参照 |
| Flat View | `flat_view` — [フラット表示](FLAT_VIEW_FEATURE.ja.md)を参照 |

### Tools メニュー

| 項目 | アクション |
|------|--------|
| Command Palette… | `command_palette` |
| Background Jobs… | `jobs` — [バックグラウンドジョブ](BACKGROUND_JOBS_FEATURE.ja.md)を参照 |
| Find Similar Files… | `find_similar` *（既定でキー未割り当て）* — [類似ファイルの検索](FIND_SIMILAR_FILES_FEATURE.ja.md)を参照 |
| External Programs… | `programs` |
| Subshell Here | `subshell` *（デスクトップモードではターミナルウィンドウで）* |
| Edit Configuration… | `edit_config` *（既定でキー未割り当て）* |
| Reload Configuration | `reload_config` *（既定でキー未割り当て）* |
| Advanced ▸ Keymap… | AFX スタイル、Orthodox、OS ネイティブ、Vim スタイルから、それぞれの説明を見ながら選びます — [キーマッププリセット](KEYMAP_PRESETS_FEATURE.ja.md)を参照 |
| Advanced ▸ Extensions… | `extensions` *（既定でキー未割り当て）* — [拡張パッケージ](EXTENSIONS_FEATURE.ja.md)を参照 |
| Advanced ▸ Check for Extension Updates… | `check_extension_updates` *（既定でキー未割り当て）* |
| Advanced ▸ Install Extension… | `install_extension` *（既定でキー未割り当て）* — フォルダー、`.zip`、URL、または `github:owner/repo` |
| Advanced ▸ Sync Python Packages | `sync_python_packages` *（既定でキー未割り当て）* — [追加の Python ライブラリ](PYTHON_PACKAGES_FEATURE.ja.md)を参照 |

Advanced には、一度だけ、あるいはときどき設定するものが入っています。ここにあるものはすべてコマンドパレットにもあります。

### Help メニュー

| 項目 | アクション |
|------|--------|
| Keyboard Shortcuts… | `help` |
| Tip of the Day… | *（メニューのみ）* |
| About XeFM | *（メニューのみ）* |

> 注：AFX スタイルでは、`create_directory` と `move_files` が 1 つのキーを共有していて、状況に合うほうを実行します。何も選択していなければ新しいフォルダーの作成、ファイルを選択していれば移動です。これはキーバインドの性質であり、メニューは両方を反映しています。

## メニュー項目の状態

項目は状況に応じて有効・無効が切り替わります。たとえば **Copy/Move/Delete** と **Create Archive** には選択が必要で、**Rename**、**View**、**Details** にはフォーカスされた項目が必要です。**Parent Directory** はファイルシステムのルートでは無効になります。無効な項目はグレー表示されます。

## キーボードショートカット

### ショートカット表示の作られ方

各メニュー項目には、そのアクションに割り当てられた最初のキーが表示用に整形されて表示されます。1 文字のキーはそのまま、特殊キーは名前で（`Enter`、`Backspace`、`Tab`）、修飾キーの組み合わせは `Cmd-`、`Shift-`、`Alt-` の接頭辞で表されます。表示はキーマップからその場で読み取られるので、設定でアクションのキーを割り当て直すと、メニューのショートカットも自動的に更新されます。また、表示は描画される環境に従うので、"Open with Default App" は macOS アプリとターミナルとで違うキーを表示することがあります（[キーマッププリセット](KEYMAP_PRESETS_FEATURE.ja.md#すべてのキーの一覧)を参照）。

### ショートカットを使う

メニューを開く必要はありません。ショートカットを押せばアクションが直接実行されます。メニューは機能を見つけるためと、マウスで操作するためにあります。

## 使用例

### 新しいフォルダーを作る
**File → New Folder…**（`create_directory`）を開き、名前を入力して確定します。

### 反対側のペインにファイルをコピーする
ファイルを選択し（**Select → Toggle Selection**）、**File → Copy to Other Pane**（`copy_files`）を選びます。

### テーマを変える
**View → Theme ▸** を開いて 1 つ選ぶか、**View → Theme ▸ Next Theme** を選んで次のテーマに切り替えます。

## トラブルシューティング

### メニューバーが表示されない
XeFM をデスクトップモードで実行しているか確認してください。ターミナルモードでは、メニューは最上行に並ぶ帯です。

### メニュー項目がグレー表示になっている
そのアクションは現在の状況では使えません（例：選択がないときの Copy や、ルートでの Parent Directory）。選択や場所を変えれば有効になります。

### ショートカットが効かない
表示されるショートカットは、`~/.xefm/config.py` でそのアクションに現在割り当てられているキーです。文字だけのキーは、大文字と小文字のどちらで書いても Shift なしのキーです（`q` と `Q` は同じキーバインドです）。`Shift-Q` と表示されているショートカットには Shift が必要です。キーバインドをカスタマイズしている場合は確認してください。[キーバインド](KEY_BINDINGS_FEATURE.ja.md)を参照してください。

## 関連機能

- [キーバインド](KEY_BINDINGS_FEATURE.ja.md) — メニューが反映しているキーマップ
- [設定](CONFIGURATION_FEATURE.ja.md) — キーバインドのカスタマイズ
- [メニューシステム](dev/MENU_SYSTEM.md) — メニューシステムの開発者向けドキュメント
