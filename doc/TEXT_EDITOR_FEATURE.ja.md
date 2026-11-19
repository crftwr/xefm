# テキストエディターとの連携

[English](TEXT_EDITOR_FEATURE.md) \| 日本語

XeFM はファイルをそのままテキストエディターに渡せます。ファイルにカーソルを合わせるか、複数を選択して **File → Open With ▸ Text Editor**（`edit_files`）を選んでください。エディターが動いている間 XeFM は脇に退き、保存して終了すると自動で戻ってきます。ファイル名を引数に取るエディターなら何でも使えます。

## 使い方

1. 編集したいファイルにカーソルを移動するか、複数のファイルを選択します。
2. **File → Open With ▸ Text Editor**（`edit_files`）を選びます。選択項目がある場合は、選択したファイルすべてが 1 回の起動でエディターに渡される（`vim a.txt b.txt`）ので、すべてのファイルを 1 つのセッションで扱えます。
3. 編集して保存し、エディターを終了します。XeFM は元の状態に再描画されます。

SSH や S3 のペインにあるファイルも編集できます。XeFM はローカルのコピーを編集させ、保存するたびにアップロードします。[リモート編集](REMOTE_EDIT_FEATURE.ja.md)を参照してください。アーカイブ内のファイルは読み取り専用で、その場では編集できません。ディレクトリ（と親ディレクトリの `..`）は編集できず、試みると警告が表示されます。ほかのものと一緒に選択されている場合は、単にスキップされます。`edit_file` は、何を選択していても、カーソルのあるファイルだけを編集します（どのプリセットでもキーは割り当てていません）。`edit_files` のキーはキーマッププリセットによって異なります（[キーマッププリセット](KEYMAP_PRESETS_FEATURE.ja.md#すべてのキーの一覧)を参照してください）。設定の `KEY_BINDINGS` で割り当てを変更することもできます。

## 使われるエディター

`edit_files` や `edit_file` を実行したとき、XeFM は次のようにエディターを選びます。

1. **`FILE_ASSOCIATIONS` に一致する `edit` のエントリ**があれば、それが優先されます。たとえば画像は画像エディターに、`.md` ファイルは Markdown アプリに送る、といったことができます。エントリが明示的に `None` に設定されている場合、その種類のファイルにはエディターが*なく*、XeFM はほかにフォールバックしません。[ファイルの関連付け](FILE_ASSOCIATIONS_FEATURE.ja.md)を参照してください。
2. **それ以外の場合は `TEXT_EDITOR` 設定項目**が使われます。

`TEXT_EDITOR` は `~/.xefm/config.py` で設定します。

```python
class Config:
    TEXT_EDITOR = 'nano'   # your preferred editor
```

エディターに引数が必要な場合は、設定をリストで書きます。各要素が 1 つの引数で、コマンドラインに入力するのとまったく同じです。

```python
class Config:
    TEXT_EDITOR = ['code', '--wait']          # terminal: wait for the tab to close
    TEXT_EDITOR = ['wt', 'nt', 'vim']         # vim in a new Windows Terminal tab
    TEXT_EDITOR = [r'C:\Program Files\Vim\vim.exe']   # a path with spaces
```

Windows でコマンドを完全なパスで書く場合は、必ずリストの形式を使ってください。普通の文字列は POSIX シェルと同じ方法で分割されるため、バックスラッシュが消えてしまいます。

ターミナルモードでは、XeFM はエディターの終了を待ちます。エディターを別の場所で開くランチャー（`wt` や、待機フラグなしの GUI エディター）はファイルを渡した時点ですぐに戻るので、XeFM は編集が終わったときではなく、すぐに戻ってきます。そのあとで保存した内容は、外部からのほかの変更と同じように反映されます。[ファイル監視](FILE_MONITORING_FEATURE.ja.md)を参照してください。

デスクトップアプリでは、XeFM はエディターのために止まりません。エディターは専用のウィンドウで開き、`code --wait` や `subl -w` のような待機フラグを付けても、XeFM のウィンドウは操作できるままです。ターミナルのエディターは、指定すればそこで XeFM 自身のターミナルのターミナルセッションとして動きます。

```python
class Config:
    TEXT_EDITOR = {'command': 'vim', 'terminal': True}
```

すると XeFM は、ターミナルモードと同じように編集が終わったことがわかります。Edit Configuration はエディターの終了時に設定を読み直します。`'terminal': False` はターミナルモードで逆の働きをし、GUI のエディターは画面を使わずにバックグラウンドで起動します。[ターミナル](TERMINAL_FEATURE.ja.md#どのコマンドにターミナルが渡されるか)を参照してください。

出荷時の既定は XeFM の動かし方によって異なり、ターミナルでは `vim`、デスクトップアプリでは VS Code（`code`）です。よく使われるのは `vim`、`nano`、`emacs`、`code`（VS Code）、`subl`（Sublime Text）、`gedit` などです。ターミナルモードでは画面を引き継げるターミナル用のエディター（vim、nano、emacs）がおすすめです。デスクトップアプリでは GUI エディターがよく合います。

設定したエディターが見つからない場合やエラーで終了した場合は、XeFM がそれを報告し、ファイルの表示に戻ります。

## 関連項目

- [リモート編集](REMOTE_EDIT_FEATURE.ja.md) — SSH や S3 上のファイルの編集
- [エディターで名前を変更](RENAME_IN_EDITOR_FEATURE.ja.md) — 名前を編集して多数のファイルの名前を変更する
- [ファイルの関連付け](FILE_ASSOCIATIONS_FEATURE.ja.md) — ファイルの種類ごとのエディターとビューアー
- [差分ビューアー](DIFF_VIEWER_FEATURE.ja.md) — `TEXT_DIFF` で外部のマージ／差分ツールを設定する
- [テキストビューアー](TEXT_VIEWER_FEATURE.ja.md) — **File → Open With ▸ Viewer**（`view_file`）による読み取り専用の表示
