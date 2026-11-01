# アプリケーションを選んで開く

[English](OPEN_WITH_FEATURE.md) \| 日本語

**Open With** は、Finder や Explorer の「このアプリケーションで開く」と同じように、今回どのアプリケーションでファイルを開くかを尋ねます。それ以外のときに `open_with_os` が何をするかは、これまでどおり既定のアプリケーションと[ファイルの関連付け](FILE_ASSOCIATIONS_FEATURE.ja.md)の `open` ルールが決めます。Open With は、別のものを使いたいときのためのものです。

## 使い方

**File → Open With ▸ Choose App…**（アプリケーションを選ぶ）を選ぶか、[コンテキストメニュー](CONTEXT_MENU_FEATURE.ja.md)の **Open With…** を選ぶか、[コマンドパレット](COMMAND_PALETTE_FEATURE.ja.md)から `open_with` を実行します。どのキーマッププリセットでもキーは割り当てられていません。よく使う場合は `KEY_BINDINGS` でキーを割り当ててください（[キーバインド](KEY_BINDINGS_FEATURE.ja.md)を参照）。

アクティブなペインの上にアプリケーションの一覧が開きます。文字を入力すると絞り込まれ、`Enter` を押すと、選択されたファイル（選択がなければカーソル位置のファイル）を強調表示中のアプリケーションで開きます。一覧の下の行には、実行するコマンドかアプリケーションの場所が表示されます。そのファイルの OS の既定のアプリケーションには、右側に `default` と表示されます。

ファイルの種類ごとに最後に選んだアプリケーションは、次回一覧の先頭に表示されます。XeFM を再起動しても覚えています。

## 一覧に表示されるもの

次の 2 種類のエントリが、この順に並びます。

1. **自分で設定したプログラム** — ファイルにマッチする `FILE_ASSOCIATIONS` ルールの `open_with` リスト（後述）。
2. **OS のアプリケーション** — Finder（macOS）、Explorer（Windows）、デスクトップのファイル種類データベース（Linux、`gio` 経由）がそのファイルに対して提示するもの。

OS のアプリケーションは、デスクトップアプリと、手元のコンピューターで動いているターミナルアプリで表示されます。SSH 経由では表示されません。開いても、手元ではなく接続先のマシンで開いてしまうからです。Linux のターミナルアプリでは、グラフィカルセッション（`DISPLAY` または `WAYLAND_DISPLAY`）も必要です。

### 複数のファイル

複数のファイルを選択しているときは、そのファイル**すべて**を開けるアプリケーションだけが表示され、選んだアプリケーションにすべてのファイルが 1 回の起動で渡されます。たとえば写真と PDF を一緒に選ぶと、両方を開けるものが表示されます。すべてを開けるものがない場合、XeFM は *No app can open all selected files.* と表示します。

`'*'` ルールのプログラムはすべてのファイルにマッチするので、常に表示されます。エディターや 16 進ビューアーを置くのに向いています。

### 対象外のもの

- **ディレクトリ。** Open With はファイルを開きます。
- **リモートやアーカイブ内のファイル。** アプリケーションにはこのコンピューター上のファイルが必要です。先にファイルをコピーしてください。対象外のファイルはそれぞれログペインに名前が表示され、残りのファイルは開かれます。

## 自分のプログラムを追加する

`~/.xefm/config.py` の `FILE_ASSOCIATIONS` ルールに `open_with` リストを書きます。各エントリは [`PROGRAMS`](EXTERNAL_PROGRAMS_FEATURE.ja.md) のエントリと同じ形です。`name`、`command` のリスト、省略可能な `options` からなります。

```python
FILE_ASSOCIATIONS = [
    {
        'pattern': ['*.jpg', '*.png'],
        'open': ['open', '-a', 'Preview'],
        'open_with': [
            {'name': 'GIMP', 'command': ['open', '-a', 'GIMP']},
            {'name': 'Pixelmator', 'command': ['open', '-a', 'Pixelmator Pro']},
        ],
    },
    {
        'pattern': '*',
        'open_with': [
            {'name': 'VS Code', 'command': ['code']},
            {'name': 'Hex view', 'command': ['hexyl'], 'options': {'terminal': True}},
        ],
    },
]
```

- **マッチしたルールすべてのリストが加わります。** 最初にマッチしたルールが使われる `open`、`view`、`edit` とは異なります。リストは上から順につなげられるので、上の例の写真には GIMP、Pixelmator、VS Code、Hex view が表示されます。
- **同じ名前が 2 回書かれた場合は、最初のエントリが使われます。** そのため、特定のルールで、そのファイル向けに別のコマンドを指定できます。
- **ファイルはコマンドの末尾にフルパスで追加されます。** プログラムはアクティブなペインのディレクトリで、`PROGRAMS` のエントリと同じ `XEFM_*` 環境変数付きで実行されます。
- **`'terminal': True`** を指定すると、プログラムにターミナルを渡して終了を待ちます。`less` や `hexyl` のような全画面のツール向けです。デスクトップアプリでは代わりにターミナルウィンドウで開きます（[外部ターミナル](EXTERNAL_TERMINAL_FEATURE.ja.md)を参照）。指定しない場合、プログラムはバックグラウンドで実行され、出力はログペインに表示されます。

## Open With と外部プログラム

[外部プログラム](EXTERNAL_PROGRAMS_FEATURE.ja.md)（`programs`）は、カーソルが何の上にあっても `PROGRAMS` のエントリをすべて表示します。Git コマンド、ディスク使用量のレポート、`XEFM_*` を読むスクリプトなど、XeFM の状態に対して動くコマンドのためのものです。Open With はファイルに合うものだけを表示します。ファイルをアプリケーションで開くためのものです。

## 関連項目

- [ファイルの関連付け](FILE_ASSOCIATIONS_FEATURE.ja.md) — ファイルの種類ごとの `open`、`view`、`edit`
- [外部プログラム](EXTERNAL_PROGRAMS_FEATURE.ja.md) — `PROGRAMS` と `terminal` オプション
- [メニューバー](MENU_BAR_FEATURE.ja.md) — **Choose App…** の場所
