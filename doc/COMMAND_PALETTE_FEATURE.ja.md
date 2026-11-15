# コマンドパレット

[English](COMMAND_PALETTE_FEATURE.md) \| 日本語

**Ctrl-T**（または **Tools → Command Palette…**）を押すと、ファイルリストが扱えるすべてのアクションを検索し、選んだものを実行できます。

```
┌ Command Palette ───────────────────────────────────────┐
│ 🔍  [copy                                            ] │
│                                                        │
│ copy_names                                     Ctrl-N  │
│ copy_paths                                     Ctrl-P  │
│ copy_files                                          C  │
│ copy_files_to                                 Shift-C  │
│ copy_log_all                                           │
│                                                        │
│ Copy the file name(s) to the clipboard                 │
├────────────────────────────────────────────────────────┤
│ ↑/↓ select · Enter choose · F1 help · Esc cancel       │
└────────────────────────────────────────────────────────┘
```

## 含まれるもの

- ファイルリストのすべてのアクション。`duplicate_files`、`focus_left`、`copy_log_all` のように、キーもメニュー項目もないものも含みます。
- すべての画面に共通するアクション（`quit`、`help`、`isearch`、`edit_files`）。
- `config.py` の `ACTIONS` に書いた自作のアクション。

ビューアーの中でしか意味のないアクション（テキストビューアーのスクロール、画像のズームなど）は一覧に出ません。そのビューアーを開いて **F1** を押すと、そのキーを確認できます。

## 使い方

- 名前の一部を**入力**すると一覧が絞り込まれます。スペースで区切った単語は、順序に関係なくすべて一致する必要があります。`sel all` で `select_all` と `toggle_select_items` が見つかります。ほかのすべての選択画面と同じく、Migemo によってローマ字で日本語の名前も見つかり、よく一致するものほど上に並びます。`copy` では `clipboard_copy` より `copy_files` が上に来ます。
- **↑/↓**、**Page Up/Page Down** で一覧を移動します。
- **Enter** で、ハイライトされたアクションをアクティブなペインに対して実行します。
- **F1** で、ハイライトされたアクションのヘルプページを開きます。何をするか、割り当てられたキー、選択項目が必要かどうか、そして自作のアクションの場合は関数の docstring が表示されます。**Esc** でページを閉じると、入力した検索語と位置はそのままでパレットに戻ります。
- **Esc** でパレットを閉じます。

各行の右側には、そのアクションに割り当てられたキーが表示されます。そのため、パレットはどのキーで何ができるかを調べるいちばん手早い方法でもあります。一覧の下の行には、ハイライトされたアクションの説明が表示されます。

選択項目が必要なアクションもパレットから実行でき、カーソル位置の項目に対して動作するか、実行できない理由を表示します。メニューから選んだときと同じです。

## パレット、メニューバー、F1 ヘルプ

| | |
|---|---|
| **メニューバー** | 主な操作をグループ分けして、見て回るためのもの |
| **F1 ヘルプ** | 現在の画面のすべてのキーを、読んで覚えるためのもの |
| **コマンドパレット** | どのアクションでも、名前の一部で見つけて実行するためのもの |

## 変更できるキー

```python
KEY_BINDINGS = {
    'command_palette': ['Ctrl-T'],      # open the palette (file list)
    'describe_list_item': ['F1'],       # help for the highlighted row (inside the palette)
}
```

`describe_list_item` は検索可能な一覧の選択画面に属するので、`remove_list_item` と同じく、修飾キー付きのキーか、文字を入力しないキーでなければなりません。入力したすべての文字は検索欄が受け取るからです。

## 自作のアクションに説明を付ける

docstring を書きます。その 1 行目が一覧の下に表示され、空行のあとの段落が **F1** で開くページになります。

```python
def open_in_vscode(ctx):
    """Open the focused item in VS Code.

    Works on directories too — VS Code opens them as a workspace.
    """
    ctx.run_program(['code', str(ctx.pane.focused.path)])


class Config:
    ACTIONS = {
        'open_in_vscode': open_in_vscode,
    }
```

アクションの書き方は[カスタマイズ](CUSTOMIZATION_FEATURE.ja.md)を参照してください。
