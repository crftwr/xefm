# 拡張パッケージ

[English](EXTENSIONS_FEATURE.md) \| 日本語

拡張パッケージは、XeFM にアクション、イベントフック、テーマ、ソート順、フィルター、画像形式、ロケーション、シンタックスハイライトを追加するフォルダーです。これらは `config.py` で追加できるのと同じ種類のものですが、`config.py` に 1 行も書く必要はありません。パッケージは 1 つの単位としてインストール、共有、無効化、削除できます。

拡張機能は、`config.py` によるカスタマイズと同じ API（バージョン 1）の上で動作します（[カスタマイズ](CUSTOMIZATION_FEATURE.ja.md)を参照）。その大部分は安定版です。プレビューと記された部分はまだ変わる可能性があり、`xefm ext check` はパッケージが使っているプレビューの部分をすべて一覧表示します。マニフェストでは、`[contributes.actions]`、`sort_keys`、`filters`、`path_schemes`、`key_suggestions` が安定版で、`menus`、`event_hooks`、`image_decoders`、`lexers`、`themes`、`agent_prompts`、`[settings]`、`[requires]`、`updates`、`agent_guide` がプレビューです。

## 拡張機能を探す

Wiki の [Extensions](https://github.com/crftwr/xefm/wiki/Extensions) ページに、公式パッケージとほかの人が書いたパッケージの両方を含め、利用できるものが一覧されています。

XeFM プロジェクト自身の拡張機能は [crftwr/xefm-extensions](https://github.com/crftwr/xefm-extensions) にあります。ほかの人の拡張機能と同じ公開 API で書かれているので、真似できる例としても役立ちます。それぞれに使い方を書いた README があり、各リリースは `compute-hash-v0.1.0` のようなタグです。インストール元に `@<tag>` を付けなければ最新のリリースがインストールされ、付ければそのリリースに固定できます。

## インストールと管理

シェルからは次のように操作します。pip/pipx/uv や Homebrew でのインストール、macOS アプリ、Windows アプリのどれでも同じです。

```bash
xefm ext install ~/Downloads/hello-xefm.zip   # a .zip
xefm ext install ./hello-xefm                 # a folder
xefm ext install github:someone/hello-xefm    # a GitHub repository: its newest release, or @ref
xefm ext install github:crftwr/xefm-extensions/compute-hash   # one package of several in a repository
xefm ext install https://example.com/hello-xefm.zip

xefm ext list                 # what is installed, and whether it will load
xefm ext disable hello-xefm   # keep it, but don't load it
xefm ext enable hello-xefm
xefm ext uninstall hello-xefm # asks whether to delete its data too
xefm ext sync                 # reinstall anything listed but missing
xefm ext settings hello-xefm  # its settings class, ready to paste into config.py
xefm ext guide hello-xefm     # its guide for AI agents, if it has one

xefm ext outdated             # which packages have a newer version
xefm ext upgrade              # install the newer versions (asks first)
xefm ext upgrade compute-hash # just this one
```

XeFM の中では次のように操作します。

- インストールするには、**Tools ▸ Advanced ▸ Install Extension…** を選び、パッケージの場所を貼り付けます。`github:crftwr/xefm-extensions/compute-hash`、`https://` の zip の URL、パスなど、`xefm ext install` が受け付けるものなら何でも使えます。カーソルがパッケージのフォルダーや `.zip` の上にあれば、そのパスがすでに入力されているので、Enter でインストールできます。相対パスはアクティブなペインのフォルダーを基準にします。
- **Tools ▸ Advanced ▸ Extensions…** は、どのパッケージが読み込まれたか、読み込まれなかったものはその理由を表示します。
- **Tools ▸ Advanced ▸ Check for Extension Updates…** は新しいバージョンを探し、アップグレードを提案します。

### 新しいバージョン

パッケージは、新しいバージョンがどこで公開されるかを自分で示します（`updates` フィールド。[公開](#公開と新しいバージョンの取得元)を参照）。どのようにインストールしたかは関係ありません。ダウンロードした zip からインストールしたパッケージでも、どこを見ればよいかを知っています。Compute Hash がその例です。

XeFM が自分から確認しに行くことはありません。確認には GitHub への接続が必要なので、`xefm ext outdated`、`xefm ext upgrade`、または **Check for Extension Updates…** を実行したときにだけ行われます。アップグレードはインストールと同じ検査を通ります。より新しい XeFM を必要とするバージョンはその旨を表示して拒否され、手元のバージョンがインストールされたまま残ります。無効にしたパッケージは無効のままです。

公開場所を示していないパッケージは確認できず、コマンドがその旨を表示します。確認に GitHub のアカウントやトークンは要りません。同じリポジトリで公開されているパッケージはまとめて確認されます。

起動時に XeFM は、オンラインに接続することなく、何からも再インストールできないパッケージについて警告します。今はもうないファイルからインストールされ、`updates` もないパッケージです。そのパッケージは引き続き動作します。ただ、別のマシンで、あるいは `extensions/` が失われた後に `xefm ext sync` を実行しても、それを元に戻せません。

インストールの前に、XeFM はパッケージを検査し、各項目がどのコードを実行するかも含めて、追加されるものをすべて表示します。拡張機能はあなたの権限で XeFM の中で動作し、サンドボックスはありません。信頼できるパッケージだけをインストールしてください。

シェルからパッケージをインストール、アップグレード、または有効化した後は、設定を再読み込みする（**Tools ▸ Reload Configuration**）か、XeFM を再起動してください。XeFM の中から行った場合は、設定は自動的に再読み込みされます。

### 自分の config.py が常に優先されます

パッケージと自分の `config.py` の両方が同じアクション、テーマ、フィルター、ロケーション、そのほかのエントリを定義している場合は、自分のエントリが使われます。パッケージのエントリはスキップされ、ログにその旨が記録されます。

パッケージはキーを *提案する* だけです。提案されたキーが使われるのは、そのアクションに自分でキーを割り当てておらず、そのキーがまだ使われていない場合だけです。そうでなければ `KEY_BINDINGS` で割り当ててください。どのアクションもコマンドパレットから実行できます。

### 設定

設定を持つパッケージは、自分の `config.py` にあるクラスから設定を読み込みます。`Config` と同じ書き方をしてください。基底クラスも import もない、普通のクラスです。

```python
class CommandPaletteConfig:
    MAX_ITEMS = 30

class Config:
    ...
```

クラス名は、パッケージ ID をパスカルケースにして `Config` を付けたものです。たとえば `command-palette` は `CommandPaletteConfig` になります。パッケージは別の名前を選ぶこともできます。`xefm ext list` で各パッケージのクラス名がわかります。

`xefm ext settings <id>` は、すべての設定項目とその既定値を含む、そのまま貼り付けられるクラスを出力します。書かなかった設定項目は既定値のままです。

XeFM は次の 2 つの場合にログで警告します。

- **パッケージにない設定項目**（打ち間違いなど）。警告には実際にある設定項目が一覧されます。
- **どのインストール済みパッケージにも対応しない `…Config` クラス**（クラス名のつづり間違いなど）。

パッケージをアンインストールしても、そのクラスは使われないまま `config.py` に残り、設定はそのまま読み込まれます。

### ファイルの置き場所

| 何を | どこに |
|---|---|
| パッケージ | `~/.xefm/extensions/<id>/`（自分のモジュールと並んで） |
| 何がどこからインストールされ、有効かどうか | `~/.xefm/extensions.toml` |
| パッケージ自身のファイル | `~/.xefm/extension-data/<id>/` |
| パッケージが記憶している状態 | XeFM の状態データベース |

保存しておく価値があるのは `extensions.toml` です。これを別のマシンにコピーして `xefm ext sync` を実行すれば、パッケージがもう一度取得されます。再インストールで `extension-data/` が変更されることはありません。

## パッケージを書く

いちばん手早い始め方はひな形を使うことです。1 つのアクション、設定、テストを含み、最初から検査に通るパッケージが作られます。

```bash
xefm ext new hello-xefm
```

### AI アシスタントと一緒に

XeFM は AI エージェント向けのスキル `xefm` を提供しています。パッケージの作成、検査、インストールまでを順に案内します（自分の `config.py` の編集も扱います）。マニフェスト、コードが使ってよい API、設定、依存関係、テストを扱い、パッケージに問題がなくなるまでエージェントに `xefm ext check` を実行させます。[Agent Skills](https://agentskills.io) を読み込めるエージェントなら、どれでも使えます。

スキルのインストールはエージェント自身に任せられます。[AI エージェント向け XeFM スキル](AGENT_SKILL_FEATURE.ja.md)のページ (https://crftwr.github.io/xefm/doc/AGENT_SKILL_FEATURE.html) をエージェントに渡し、スキルをインストールするよう頼んでください。リリースページから `xefm-X.Y.Z-skill.zip` をダウンロードし、自分でエージェントのスキルフォルダーに展開することもできます。そのページで両方の方法を説明しています。

その後、機能を頼みます（「〜する XeFM 拡張機能を作って」）。エージェントがスキルに従えば、出来上がったものは以下の要件を満たします。`xefm ext check` がそのすべてを検証するので、検査に問題がなければそれが確認できます。

### 公開と、新しいバージョンの取得元

パッケージを GitHub にプッシュします。何かをアップロードする必要はありません。`github:owner/repo@ref` で任意のタグ、ブランチ、コミットをインストールでき、`github:owner/repo` だけなら最新のリリース（リリースがなければデフォルトブランチ）がインストールされます。バージョンは **タグ** です。

- リポジトリのルートにあるパッケージ：`v0.2.0`
- サブディレクトリにあるパッケージ（`github:crftwr/xefm-extensions/compute-hash` のように、1 つのリポジトリに複数あるうちの 1 つ）：ID を先頭に付けて `compute-hash-v0.2.0`

`[extension]` の `updates` は、新しいバージョンがどこで公開されるかを `github:owner/repo` または `github:owner/repo/path/to/package` の形で、`@ref` なしで示します。これはインストール方法ではなくパッケージに属するものなので、ダウンロードした zip からインストールしたコピーでも、次のバージョンがどこにあるかを知っています。最初のリリースから設定してください。これを持たないバージョンは、利用者を次のバージョンへ案内できません。

リリースには、タグと同じ名前のアセット（`compute-hash-v0.2.0.zip`。中身はパッケージのフォルダー）としてパッケージを添付することもできます。添付されていれば XeFM はリポジトリ全体ではなくそれをダウンロードし、パッケージをファイルとして欲しい人もそこから入手できます。添付がなければ、XeFM はそのタグのリポジトリ全体をダウンロードし、パッケージの部分だけを使います。

Wiki の [Extensions](https://github.com/crftwr/xefm/wiki/Extensions) ページに載せてもらうには、[Show and tell](https://github.com/crftwr/xefm/discussions/categories/show-and-tell) ディスカッションカテゴリーに、リポジトリへのリンク、1 行の説明、インストール元を添えて投稿してください。

### 構成

パッケージは、マニフェストと、コードを実行する場合は Python パッケージを含むフォルダーです。

```
hello-xefm/
  xefm-extension.toml
  hello_xefm/
    __init__.py
    actions.py
    settings.py
```

```toml
[extension]
id = "hello-xefm"
version = "0.1.0"
api_version = 1                       # the XeFM API it was written for
# optional:
name = "Hello"
description = "Says hello"
min_xefm = "1.8.0"
backends = ["desktop", "tui"]         # default: both
platforms = ["macos", "windows", "linux"]   # default: all
updates = "github:someone/hello-xefm" # where newer versions are published
agent_guide = "AGENT.md"              # how AI agents should use it (Preview)

[contributes.actions]
"hello.greet" = { entry = "hello_xefm.actions:greet", description = "Say hello" }

[contributes.key_suggestions]
"hello.greet" = ["Ctrl-Shift-G"]

[settings]
defaults = "hello_xefm.settings:Settings"
# config_class = "HelloConfig"        # default: derived from the id

[requires]
programs = ["ffmpeg"]                 # missing → its actions say so when run
host_packages = ["PIL"]               # must already be in this XeFM build
python_packages = ["PyYAML>=6"]       # installed from PyPI by the sync
```

```python
# hello_xefm/actions.py
from xefm.user_api import extension


def greet(ctx):
    """Say hello in the log."""
    me = extension(__name__)
    times = me.state.get("times", 0) + 1
    me.state.set("times", times)
    ctx.message(f"{me.settings.GREETING} (#{times})")
```

```python
# hello_xefm/settings.py
class Settings:
    GREETING = "Hello"
```

コードは `module:name` の形で参照されるだけです。XeFM がそれを import するのはパッケージを読み込むときだけで、検査のときには import しません。

### パッケージが追加できるもの

各 `[contributes.<kind>]` テーブルは、`config.py` の同名のテーブルに取り込まれます。各エントリが何をするかは [カスタマイズ](CUSTOMIZATION_FEATURE.ja.md) を参照してください。

| 種類 | 取り込み先 | エントリ |
|---|---|---|
| `actions` | `ACTIONS` | `"mod:func"`、または `{ entry = "mod:func", description = "..." }` |
| `event_hooks` | `EVENT_HOOKS` | `"mod:func"`、またはそのリスト |
| `sort_keys` | `SORT_KEYS` | `"mod:name"` |
| `filters` | `FILTERS` | `"mod:name"`、または `{ globs = ["*.png"] }` のようなテーブル |
| `image_decoders` | `IMAGE_DECODERS` | `"mod:name"` |
| `path_schemes` | `PATH_SCHEMES` | `"mod:Class"` |
| `lexers` | `LEXERS` | Pygments のエイリアス、または `{ entry = "mod:LexerClass" }` |
| `themes` | `THEMES` | `config.py` と同じ色のテーブル |
| `menus` | `MENU_ITEMS` | `{ menus = ["file", "context"], label = "...", when = "entry" }`（パッケージ自身のアクション用） |
| `agent_prompts` | `AGENT_PROMPTS` | 依頼の文（`"Summarize these files."`）、または `{ prompt = "...", agent = "Claude Code" }` |
| `key_suggestions` | `KEY_BINDINGS` | キーのリスト（パッケージ自身のアクション用） |

テーマ、glob フィルター、レクサーのエイリアス、メニュー、キーの提案だけを持つパッケージは、コードをまったく実行しません。

アクションには `hello.greet` のように `<something>.<name>` の形で名前を付けてください。ドットのない名前には警告が出て、組み込みアクションの名前は拒否されます。各アクションには、マニフェストか関数の docstring で説明を付けてください。コマンドパレットがそれを表示し、AI エージェントもそれでアクションを知ります（`xefmctl action show`）。どちらもないアクションには警告が出ます。

### AI エージェント向けのガイド

XeFM の中で作業する [AI エージェント](AI_AGENT_SESSIONS_FEATURE.ja.md)は、`xefmctl action list` であなたのアクションを見つけ、それぞれの説明を読みます。ひとつの説明では伝えきれないこと（どんなときにパッケージを使うか、アクションどうしをどう組み合わせるか、設定でどう変わるか、出力をどう読むか）は、パッケージの中の Markdown ファイルに書き、`agent_guide` でその名前を指定します（プレビュー）。

```toml
[extension]
agent_guide = "AGENT.md"
```

エージェントはパッケージのどのアクションでも `xefmctl action show` でこれを読め、`xefm ext guide <id>` でも表示できます。エージェントに向けて、何をどの順で実行するか、何をしてはいけないかを書いてください。README は人向けのままにしておきます。

### コードに渡されるもの

`xefm.user_api.extension(__name__)` は、パッケージのハンドルを返します。

- `id`、`version`
- `settings` — パッケージの既定値に、ユーザーの設定クラスを重ねたもの
- `state` — `get(key, default)`、`set(key, value)`、`delete(key)`、`keys()`。値は JSON で表せるものなら何でもよく、どのスレッドからでも安全に使えます
- `data_dir` — `~/.xefm/extension-data/` の下にあるパッケージのフォルダー。最初に使うときに作られます

パッケージはモジュール自身の名前から見つけられるので、コードのどこからでも、いつでも使えます。アクションの中でも、アクションが戻った後に応答するプロンプトのコールバックの中でも、バックグラウンドタスクの中でも、ソートキーの中でも使えます。読み込まれたパッケージの外（`config.py` の中）では `None` を返します。

（以前のプレビューには、アクションの実行中にだけ設定される `ctx.extension` があったため、プロンプトのコールバックでは `None` になっていました。これは廃止され、`xefm ext check` が代わりのものを示します。）

### パッケージを検査する

```bash
xefm ext check ./hello-xefm
xefm ext check ~/Downloads/hello-xefm.zip
xefm ext check github:crftwr/xefm-extensions/compute-hash
```

検査は `xefm ext install` が受け付けるものなら何でも受け付けるので、ダウンロードしたファイルやリンクから直接、インストールする前にパッケージを検査できます。最初に、パッケージが追加するものを一覧表示します。インストールが確認を求める前に表示するものと同じ一覧です。

```
Hello 0.1.0 (hello-xefm) adds:
  action: hello.greet  (runs hello_xefm.actions:greet)
  installs Python package from PyPI: PyYAML>=6
```

検査は、パッケージのコードを一切実行せずにマニフェストを検証します。報告される問題には、それぞれ関係するマニフェストのフィールドが示されます。

```
error: xefm-extension.toml: contributes.actions."hello.greet".entry: module hello_xefm.actions has no top-level 'greet'
```

検査はパッケージの Python ファイルも、やはり実行せずに読み込みます。

- **エラー：** `ctx._app` のような非公開の名前（`self` 以外のオブジェクトで `_` から始まるもの）を使うこと、または `xefm.user_api` と `xefm.path_base` 以外の XeFM モジュールを import すること。この 2 つからも、公開されているのはそれぞれの `__all__` にある名前だけです。それ以外に含まれているものは XeFM 内部のもので、それを使うこともエラーになります。メッセージには使ってよい名前が一覧されます。こうしたコードは今は動いても、どのリリースで壊れてもおかしくありません。
- **警告：** `print()`（出力が届くことはないので `ctx.message` を使ってください）と、`sys.path` の変更。また、非推奨の API を使うことも警告されます。その API は引き続き動作し、警告には代わりのものが示され、早くとも次の XeFM マイナーリリースまでは削除されません。

`_vendor/` フォルダーの下にあるファイルはスキップされます。

最後に、パッケージが使っている API のうち、まだプレビューであるものをすべて一覧表示します。マニフェストのセクション、import している名前、`ctx` のメソッドなどです。

```
preview: xefm-extension.toml: contributes.menus: Preview, may change in any release
preview: hello_xefm/actions.py:42: ctx.run_task — Preview, may change in any release
2 Preview API(s) in use; everything else this package uses is stable.
```

これらは問題ではありません。プレビューを使うのは構いませんし、これらの行しかないパッケージはインストールでき、読み込まれます。これらの行は、XeFM のリリース後にパッケージのどの部分を変更する必要が出るかもしれないかを教えてくれます。パッケージを安定版の部分だけに保つには、`--stable-only` を付けて検査してください。これらがエラーとして報告されます。

```bash
xefm ext check --stable-only ./hello-xefm
```

同じことは実行時にも表示されます。パッケージがプレビューの関数を初めて呼び出すと、XeFM はパッケージと関数の名前を記した 1 行をログペインに書き出します。また、起動時に拡張機能を一覧する行には、それぞれが使っているプレビューのマニフェストセクションが示されます。

パッケージがインストール可能なら、終了ステータスは 0 です。インストールは同じ検査を実行し、エラーが見つかれば何もインストールしません。

### パッケージを試す

```bash
xefm try --ext ./hello-xefm
```

このコマンドは、そのパッケージだけを入れた XeFM をターミナルで起動するので、インストールする前にそのメニュー、ダイアログ、タスクを確認できます。一時的なホームフォルダーで動作するので、自分の `~/.xefm`、その設定、ほかの拡張機能に触れることはありません。いつもどおり XeFM を終了すると、一時的なホームは削除されます。AI アシスタントは、キーのスクリプトを添えて同じコマンドを使います。[使い捨てのホームで XeFM を試す](TRY_FEATURE.ja.md)を参照してください。

### 依存関係

- **PyPI のライブラリ**（PyYAML、numpy、rawpy など。コンパイルが必要かどうかは問いません）：`python_packages` に列挙し、普通に import します。これらは `~/.xefm/requirements.txt` と同じ同期（[追加の Python ライブラリ](PYTHON_PACKAGES_FEATURE.ja.md)）で、共有の 1 つのディレクトリにインストールされ、ほかのすべての拡張機能や自分自身のものと一緒に依存関係が解決されます。
- **XeFM がすでに同梱しているライブラリ**（たとえば Pillow）：`host_packages` に列挙します。
- **小さな純 Python のヘルパー：** 自分のパッケージの中に同梱して（`hello_xefm/_vendor/`）、そこから import することもできます。同梱したライブラリには同期もネットワークも必要ありません。読み込まれたすべてのパッケージは 1 つの Python プロセスを共有するので、トップレベルのモジュール名は 1 つのパッケージにしか属せません。`foo` を提供するパッケージが 2 つあれば拒否され、標準ライブラリのモジュールを隠してしまう名前も拒否されます。
- **外部プログラム：** `programs` に列挙します。

`python_packages` のエントリは普通の要件指定です。プロジェクト名、省略可能な `[extras]`、バージョン指定子、`;` によるマーカーを書けます。pip のオプション（`--index-url`）、URL、パスは検査で拒否されるので、どの拡張機能も pip のダウンロード元を差し替えることはできません。

ユーザーから見ると次のようになります。

- インストール時には、各パッケージが "installs Python package from PyPI" の下に表示されます。続いて `xefm ext install` は同期するかどうかを尋ねます（`-y` を付ければそのまま同期します）。XeFM の Install Extension は、インストールの直後に同期します。
- 列挙されたパッケージがちょうどそのとおりに同期でインストールされるまで、その拡張機能は読み込まれず、ログには Sync Python Packages が必要だと表示されます。
- 2 つの拡張機能（あるいは拡張機能と XeFM 自身）が、同時にはインストールできないバージョンを必要とする場合、同期は失敗し、ログにその拡張機能の名前が表示されます。
- 拡張機能をアンインストールまたは無効化しても、そのパッケージは次の同期まで残り、`xefm ext` は同期が必要だと表示します。

## 知っておきたいこと

- アクションとフックは、`config.py` の場合と同じく UI スレッドで動作します。そこから時間のかかる外部プログラムを実行すると、終わるまでウィンドウが固まります。
- 検査に通らなかったり import に失敗したりしたパッケージは、丸ごとスキップされ、理由がログに記録されます。一部だけが読み込まれることはありません。
- このバージョンにはカタログがありません。パッケージはフォルダー、zip、リポジトリからインストールします。
