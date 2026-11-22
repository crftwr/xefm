# xefmctl

[English](XEFMCTL_FEATURE.md) \| 日本語

XeFM が起動したシェル（サブシェル、[ターミナルセッション](TERMINAL_FEATURE.ja.md)、`PROGRAMS` のエントリ、[AI エージェントのセッション](AI_AGENT_SESSIONS_FEATURE.ja.md)）では、`xefmctl` コマンドでその XeFM とやり取りできます。実行した時点での状態を問い合わせ、その XeFM のファイルマネージャーを操作します。

いちばんの利用者は、隣で作業する AI エージェントです。あなたが見ているものを読み、XeFM が開ける場所ならどこでも検索し、見つけたものを見せ、何かを変える前にあなたに確認します。自分のシェルスクリプトから使うこともできます。

## コマンド

ペインについてのコマンドは `pane` で始まり、それ以外はすることの名前がついています。名前は XeFM 自身の名前にそろえてあります。`pane cd` はアクションの `ctx.pane.cd` と同じことをし、検索をするコマンドには、その検索を開くアクションの名前がついています（`find-files`、`find-in-files`）。

| コマンド | すること |
|---|---|
| `xefmctl state` | 両方のペイン（ディレクトリ、カーソル、選択項目、フィルター）、表示中の画面、ペインの上に開いているもの。まずこれを使います |
| `xefmctl pane path` / `entries` / `focused` / `selected` | ペインのディレクトリ、項目、カーソル位置の項目、選択項目 |
| `xefmctl pane cd [PATH] [--focus NAME]` | ペインを `PATH`（既定はシェルのディレクトリ）に移動。ファイルを指定すると、そのフォルダーに移動してカーソルをそのファイルに置く |
| `xefmctl pane select PATTERN...` / `unselect` | 名前かグロブで項目を選択（選択解除）。`--all` ですべての項目 |
| `xefmctl pane open-list PATH...` | パスをペインに[一覧](FILE_LIST_IMPORT_FEATURE.ja.md)として表示。`-` で標準入力から読む |
| `xefmctl pane refresh` / `activate` | ペインを読み直す。ペインをアクティブにする |
| `xefmctl pane pick [--prompt TEXT]` | XeFM でいつもどおり項目を選んでもらい、Enter を押したらそれを表示する（Esc で取り消し） |
| `xefmctl entries [URL...]` | XeFM が開ける場所にあるフォルダーの中身。`--recursive` で下のフォルダーも |
| `xefmctl find-files PATTERN [URL...]` | フォルダーの下にある、名前が一致するファイル |
| `xefmctl find-in-files PATTERN [URL...]` | フォルダーの下のファイルで一致する行（`--case`、`--word`、`--regex`） |
| `xefmctl index-search QUERY [URL...]` | OS のインデックス。macOS は Spotlight、Windows は Windows Search |
| `xefmctl find-similar --method METHOD [URL...]` | [似たファイル](FIND_SIMILAR_FILES_FEATURE.ja.md)のグループ（`identical`、`image`、`video`、`audio`。`--threshold`）。1 行に 1 ファイルを、グループの番号付きで |
| `xefmctl path-scheme list` | ローカルディスクのほかに XeFM が開ける場所の種類。`PATH_SCHEMES` と拡張機能が加えたものも |
| `xefmctl read URL` / `fetch URL [LOCAL]` | ファイルのテキスト。ローカルディスクへのファイルのコピー |
| `xefmctl view FILE [--line N]` | `FILE` をファイルマネージャーの画面の XeFM のビューアーで開く。そこに開いていたビューアーと入れ替わる |
| `xefmctl diff A B` | 2 つのファイル、または 2 つのフォルダーを比べる |
| `xefmctl show-markdown FILE` | Markdown を XeFM のビューアーで表示。`-` で標準入力から読む |
| `xefmctl copy SOURCE... --to DIR` / `move` | XeFM 自身のコピー（移動）で、競合ダイアログ付きでコピー（移動）する |
| `xefmctl trash PATH...` / `delete` | OS のゴミ箱に移動する。完全に削除する |
| `xefmctl rename --plan FILE` | JSON のプラン（`[{"path": ..., "name": ...}]`）にある名前に、XeFM の名前変更の確認画面であなたが確かめてから変更する |
| `xefmctl tag list` / `tag add NAME PATH...` / `tag remove NAME PATH...` | XeFM が知っているタグ。[タグ](FILE_TAGS_FEATURE.ja.md)を付ける、外す（`--tag` で複数、`--color` で新しいタグの色） |
| `xefmctl attribute list` / `attribute get PATH...` | すべての属性。項目の属性の値を、その場で計算して（`--attributes a,b`） |
| `xefmctl confirm` / `choose` / `input` | XeFM であなたに尋ね（はい・いいえ、一覧からひとつ、1 行のテキスト）、答えを表示する |
| `xefmctl message TEXT` | ログペインに 1 行書く |
| `xefmctl action list` / `action show NAME` | すべてのアクションと、その説明とキー。ひとつのアクションの詳細 |
| `xefmctl invoke NAME` | ファイルマネージャーの画面でキーを押したのと同じようにアクションを実行する |
| `xefmctl screen list` / `screen show ID` | 画面の一覧。画面を表示する（ファイルマネージャーは `files`） |
| `xefmctl terminal-session list` / `start` / `close ID` | XeFM のターミナルセッション |
| `xefmctl help [COMMAND]` | すべてのコマンド、またはひとつのコマンドの詳細 |

各コマンドのオプションは `xefmctl help COMMAND` で確認できます。

### XeFM が開ける場所ならどこでも

`entries`、`find-files`、`find-in-files`、`read`、`fetch`、`view`、`diff`（とファイルを操作するコマンド）には、このコンピューターのパスのほか、XeFM が開けるものなら何でも渡せます。`ssh://host/path`、`s3://bucket/key`、アーカイブの中のファイル（`archive:///path/a.zip#inner/file`）、[仮想フォルダー](VIRTUAL_FOLDERS_FEATURE.ja.md)です。接続は XeFM が持っているので、シェルに SSH の鍵やクラウドの認証情報は要りません。

### ペインから項目を取る：`--from`

XeFM 自身のアクションがペインから項目を取るところでは、コマンドには項目を渡します。引数でいくつでも渡せ、`--from` を付ければペインから取ります。

- `--from pane`：ペインのフォルダー。一覧（検索結果、[ファイルリスト](FILE_LIST_IMPORT_FEATURE.ja.md)）を表示しているペインでは、その一覧の項目。
- `--from selection`：選択している項目。何も選択していなければカーソル位置の項目。アクションが対象にするものと同じです。

項目を取るどのコマンドでも意味は同じです。検索、`entries`、`find-similar`、`copy`、`move`、`trash`、`delete`、`tag add`、`tag remove`、`attribute get` です。項目をどこから取っても、フォルダーはその下を探し、ファイルはそのファイル自体を見ます。たとえば `xefmctl find-in-files TODO --from selection` は、選択したファイルと、一緒に選択したフォルダーの下を探します。項目も `--from` もなければ、場所を見るコマンドはペインのフォルダーを使います。

### 見つけたものを見せる

`entries` や検索に `--show` を付けると、見つけたものがアクティブなペイン（`--pane` で別のペインも指定できます）に一覧として表示されます。XeFM 自身の検索と同じく、ソート、絞り込み、操作ができます。`find-similar --show` は、グループをペインにツリーとして開きます。

### どのペインか

`--pane active`（既定）、`--pane other`、`--pane left`、`--pane right` です。

### スクリプトとエージェント向け

- どのコマンドも、`--json` を付けると 1 行に 1 つずつ JSON オブジェクトを出力します。空白や改行を含むパスでも曖昧になりません。
- 検索は、見つけたそばから出力します。`--limit N` で `N` 件で止まり、Ctrl-C で中断できます。
- パスを複数取るコマンドでは、`-` で標準入力から読みます。1 行に 1 つのパスでも、別の `xefmctl --json` が出力した JSON の行でもかまいません：`xefmctl find-files '*.log' --json | xefmctl trash -`。
- `copy`、`move`、`trash`、`delete`、`rename`、`tag add`、`tag remove` は、始めた時点で戻ります。`--wait` を付けると終わるまで待ち、結果を伝えます（`rename` とタグは 1 行に 1 項目ずつ、その結果付きで）。
- 終了ステータス：0 は完了、1 は失敗（またはあなたが「いいえ」と答えた）、2 はコマンドの誤り、3 は XeFM に届かない、4 は XeFM が取り込み中、5 は拒否、6 は XeFM がこのシェルの終了を待っている(後述)です。拒否するときは、その理由を、エージェントがそのままあなたに伝えられる言葉で返します。

```sh
cp $(xefmctl pane selected) /tmp               # names without spaces
xefmctl pane selected -0 | xargs -0 du -sh
xefmctl pane cd .                              # bring the active pane here
xefmctl find-in-files TODO ~/src --show        # the hits, as a list in the pane
xefmctl view build.log --line 120
xefmctl confirm "Delete the 3 old backups?" && xefmctl trash backup-*.zip
xefmctl pane pick --prompt "Which photos?" | xefmctl tag add Trip -
xefmctl find-similar --method image --from selection --show
```

## 手でできることだけ

ファイルマネージャーを変えるコマンドは、その画面でキーが届く状態のときに受け付けます。

- ペインがいちばん上なら、何でも受け付けます。
- ペインの上にビューアーが開いているときは、ファイル一覧のアクション以外を受け付けます。`view` はそのビューアーを閉じてから新しいものを開くので、2 つ開くことはありません。
- ファイルマネージャーの画面でダイアログ、メニュー、コマンドパレットが開いているときは、何も受け付けません。何が開いているかを示すメッセージとともに拒否します。それを閉じてから、コマンドをもう一度実行してください。

コマンドが開くもの（ビューアー、質問）は、ファイルマネージャーの画面に開き、XeFM はあなたをそこに連れて行きます。エージェントのために出した質問なら、答えたあとエージェントのターミナルに戻ります。

## サブシェルがターミナルを使っている間

ターミナルモードでは、サブシェルやターミナルプログラムが動いている間 XeFM は待っているので、読むだけのコマンドしか使えません。`state`、`pane` の読み取り、`entries`、検索、`find-similar`、`read`、`fetch`、`list` の付くコマンド、`attribute get` です。検索の `--show` は無視されます。ほかのコマンドは、シェルが終わるまで XeFM が中断していることを伝えて終了ステータス 6 で終わり、戻ってから使えるようになります。`xefmctl state` もそのことを示し、`xefmctl help` は XeFM の画面を使うコマンドに `*` を付けます。そのシェルで動くエージェントは、結果をターミナルに表示し、質問はチャットでします。

シェルを起動した XeFM が終了していれば、どのコマンドもそう伝えます。

## Microsoft Store のパッケージ

Windows では、Microsoft Store のアプリの中にあるプログラム（XeFM 自身の Python など）を起動できるのは XeFM 本体だけです。XeFM が起動したシェル（cmd、PowerShell、Git Bash のどれでも）からは実行できません。XeFM が代わりに起動するプログラムには影響しません。`PROGRAMS` のエントリ、**Open With**（[アプリケーションを選んで開く](OPEN_WITH_FEATURE.ja.md)）、`ctx.run_program` は、ほかのインストール方法と同じように動きます。

それでも `xefmctl` はどのシェルでも動きます。Store の XeFM は `xefmctl` をアプリ実行エイリアス経由で実行するからです。`xefmctl` がエイリアスがオフになっていると伝えたら、Windows の **設定 > アプリ > アプリの詳細設定 > アプリ実行エイリアス** で XeFM の `xefmctl.exe` をオンにし、XeFM を再起動してください。このエイリアスにより、XeFM が起動していないシェルの `PATH` にも `xefmctl` が入りますが、そこでは XeFM が起動したシェルではないと伝えます。

## 関連項目

- [AI エージェントのセッション](AI_AGENT_SESSIONS_FEATURE.ja.md)：エージェントのセッションができること、できないこと
- [ターミナル](TERMINAL_FEATURE.ja.md)：サブシェル、ターミナルセッション、画面
- [ファイルリスト](FILE_LIST_IMPORT_FEATURE.ja.md)：ペインに表示するパスの一覧
