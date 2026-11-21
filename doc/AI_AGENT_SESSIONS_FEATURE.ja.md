# AI エージェントのセッション

[English](AI_AGENT_SESSIONS_FEATURE.md) \| 日本語

XeFM は、ファイルマネージャーの隣で AI コーディングエージェントを、専用の[ターミナルセッション](TERMINAL_FEATURE.ja.md)として開けます。エージェントは自分が XeFM の中で動いていることを知っていて、あなたが見ているものを読み、XeFM が開ける場所ならどこでも検索し、見つけたものを見せ、ファイルを変える前にあなたに確認します。

| アクション | メニュー |
|--------|------|
| `agent` | Tools → AI Agent Here |
| `ask_agent` | Tools → Ask AI Agent… |

`agent` はどのキーマッププリセットでも `>` です（エージェントのコマンドラインが出すプロンプトの記号）。`ask_agent` は既定ではキーが割り当てられていません。変えるには[キーバインド](KEY_BINDINGS_FEATURE.ja.md)と[キーマッププリセット](KEYMAP_PRESETS_FEATURE.ja.md)を参照してください。

## 必要なもの

エージェントのコマンドラインプログラムです。インストールとサインインは、それぞれ自分で済ませておきます。XeFM はエディターを起動するのと同じようにそれを起動するだけで、アカウント、認証情報、モデルには触れません。Claude Code（`claude`）、Codex（`codex`）、GitHub Copilot CLI（`copilot`）、Antigravity CLI（`agy`。Gemini CLI の後継）は最初から設定されています。ほかのエージェントは wiki にあります（[ほかのエージェント](#ほかのエージェント)を参照）。

## セッションを開く

- **AI Agent Here**（`agent`）は、アクティブなペインのディレクトリでエージェントを起動します。何でも尋ねてかまいません。「このファイル」「これら」と言えば、エージェントは XeFM が表示しているものを読みます。
- **Ask AI Agent…**（`ask_agent`）は、まず依頼を尋ねます（[登録した依頼](#登録した依頼agent_prompts)から選ぶか、打ち込みます）。そして、その依頼とディレクトリ、選択項目（なければカーソル位置の項目）を添えてエージェントを起動します。

`AGENTS` のエージェントが 1 つもインストールされていない（プログラムが `PATH` にない）間は、どちらもメニューで無効になります。キーやコマンドパレットから使うと、どのプログラムが見つからないかをログペインに表示します。インストールすれば、再起動しなくても使えるようになります。

エージェントが複数設定されていれば、XeFM はどれを使うかを尋ねます。**Screens…** の一覧にも、**New shell in ~/...** の隣に、エージェントごとの行（**New Claude Code in ~/...**）があります。セッションには、ほかのターミナルセッションと同じく専用の画面がつきます。**Screens…** でファイルマネージャーとの間を切り替えられ、離れている間もエージェントは動き続けます。画面の一覧では、その行にエージェントが自分のタイトルとして付けた名前（`✳ Claude Code`）が表示されます。

ターミナルモードでは、XeFM はサブシェルと同じくエージェントにターミナルを渡して待ちます。そこでエージェントが動いている間、XeFM はペインについての問い合わせと検索には答えますが、エージェントに何かを見せたり、あなたに何かを尋ねたりはできません。それにはデスクトップアプリが必要です。

## エージェントに渡すもの

- **`xefm` スキル**。エージェントが動いている XeFM そのものの版です。[`xefmctl`](XEFMCTL_FEATURE.ja.md) の使い方、XeFM の設定と拡張機能の仕組みが書かれています。エージェント自身のフォルダーには何もインストールしません。セッションを起動するたびにスキルを渡します。
- XeFM の中で作業するための**ルール**。まず `xefmctl state` を使う、推測せずに表示されているものを読む、ファイルは `xefmctl` を通してだけ変え、変更のたびにあなたが確認できるようにする、完全には削除しない、結果は XeFM で見せる、といったものです。あなた自身のルール（`AGENT_RULES`）は XeFM のルールのあとに続きます。
- **[`xefmctl`](XEFMCTL_FEATURE.ja.md)**。このエージェントのセッションからの依頼であることを XeFM に伝える鍵が付いています。

## エージェントにできないこと

ルールは無視されることがあります。そこで、エージェントが何を決めても、次の 2 つは必ず守られます。

- **XeFM がすべての変更を確認します。** `xefmctl` で頼まれたコピー、移動、ゴミ箱への移動は、`CONFIRM_*` の設定でオフにしていても、その操作自身の確認ダイアログ（項目の一覧付き）を XeFM に出し、あなたが許可したときだけ実行されます。終わるか取り消されると、XeFM はエージェントの画面に戻ります。`xefmctl delete` は拒否され（ゴミ箱なら元に戻せます）、`delete_permanently` アクションも同様です。エージェントが `xefmctl invoke` で実行するアクションも先に確認し、削除はゴミ箱への移動になります。エージェントがこのコンピューターのディスクの外（サーバー、クラウドストレージ、アーカイブ）を初めて読むときは、残りのセッションの間それを許すかどうかを XeFM が尋ねます。
- **エージェント自身のシェルを制限します**（Claude Code、Copilot、Antigravity）。ファイルを削除・移動するコマンド（`rm`、`rmdir`、`mv`、`unlink`、`shred`、`git clean`。Copilot と Antigravity では PowerShell の `Remove-Item`、`Move-Item`、`del` などの仲間も）を権限の設定で拒否するので、そうした変更は `xefmctl` を通ることになります。Codex にはこうした設定を渡す手段がありません。Codex のシェルで何を実行できるかは、XeFM の外と同じく Codex 自身のサンドボックスと承認の設定で決まります。

ファイルを任せられるエージェントでこの 2 つを外すには、そのエントリに `'restrict': False` を設定します。

## エージェントの設定：`AGENTS`

```python
AGENTS = [
    {'name': 'Claude Code', 'command': ['claude'], 'preset': 'claude-code'},
    {'name': 'Codex', 'command': ['codex'], 'preset': 'codex'},
    {'name': 'Copilot', 'command': ['copilot'], 'preset': 'copilot'},
    {'name': 'Antigravity', 'command': ['agy'], 'preset': 'antigravity'},
]

# Your own rules, added after XeFM's in every session.
AGENT_RULES = "Never touch ~/Documents/Taxes. Answer in Japanese."
```

| キー | 内容 |
|---|---|
| `name` | メニューと画面の一覧での名前 |
| `command` | プログラムとその引数のリスト（またはシェルと同じように分割される文字列） |
| `preset` | `'claude-code'`：スキル、ルール、権限の設定を Claude Code に渡す引数を XeFM が加える。`'codex'`：XeFM が Codex にルールを渡し、そのルールでスキルの場所を伝える。`'copilot'`：スキル、ルール、実行させないコマンドを XeFM が GitHub Copilot CLI に渡す。`'antigravity'`：スキル、ルール、権限の設定を XeFM が Antigravity CLI に渡す |
| `restrict` | `True`（既定）：上の制限をかける。`False`：かけない |
| `settings` | Claude Code と Antigravity：XeFM の設定の代わりに渡す設定。そのエージェント自身の書式で書く。例：Claude Code なら `{'permissions': {'deny': ['Bash(rm:*)']}}`、Antigravity なら `{'permissions': {'deny': ['command(rm)']}}` |
| `env` | 追加の環境変数 |
| `prompt_args` | プリセットなしの場合：`ask_agent` が依頼のために加えるもの（既定は `['{prompt}']`） |

エージェントにほかのオプションを渡すには、`command` に加えます：`['claude', '--model', 'opus']`。

`codex` プリセットはセッションの間 Codex の `developer_instructions` を設定するので、`~/.codex/config.toml` に書いたものはそこでは使われません。どのセッションにも伝えたいことは `AGENT_RULES`（または Codex 自身の `AGENTS.md`）に書いてください。

Copilot と Antigravity は、あるフォルダーで初めて起動したときに、そのフォルダーを信頼するかどうかを尋ねます。セッションの中で答えてください。

`config.py` に自分の `AGENTS` がある場合は、そちらが使われます。Codex、Copilot、Antigravity を使うには、その中にその行を加えてください。

### 登録した依頼：`AGENT_PROMPTS`

よく頼むことを登録しておくと、**Ask AI Agent…** に一覧で出ます。選ぶか、自分で打ち込みます。エージェントにはディレクトリと選択項目も渡るので、「these files」はあなたが選んだものを指します。

```python
AGENT_PROMPTS = {
    'Summarize': 'Summarize these files, a few lines each.',
    'Sort photos by month': 'Move these photos into folders named YYYY-MM by the date taken.',
    'Review': {'prompt': 'Review the uncommitted changes here.', 'agent': 'Claude Code'},
}
```

依頼は文字列か、`prompt` と `agent`（`AGENTS` のエントリの `name`。指定すると、尋ねずにそのエージェントに送ります）を持つテーブルです。設定のテンプレートには、ほかの例がコメントアウトした状態で入っています。[拡張パッケージ](EXTENSIONS_FEATURE.ja.md)も依頼を追加できます（`[contributes.agent_prompts]`）。`AGENT_PROMPTS` はプレビューです。

### ほかのエージェント

プリセットのないエージェントには、`command`（と `prompt_args`）の中のプレースホルダーを通して必要なものを渡します。XeFM はセッションを起動するときにそれを埋めます。

| プレースホルダー | 置き換わるもの |
|---|---|
| `{skills_dir}` | `xefm` スキル（`xefm/SKILL.md`）を入れたスキルフォルダー |
| `{skill_dir}` | `xefm` スキル自体のフォルダー |
| `{plugin_dir}` | 同じスキルを Claude Code のプラグインとして入れたフォルダー |
| `{rules}` / `{rules_file}` | ルールのテキスト / ルールを書いた Markdown ファイル |
| `{settings_file}` | 指定した `settings` の JSON ファイル（指定がなければ空） |
| `{prompt}` | `ask_agent` の依頼 |

これらをどう受け取るかはエージェントごとに違います。wiki のページ [AI agents](https://github.com/crftwr/xefm/wiki/AI-agents) に、ほかのエージェントのエントリを、それを使っている人たちが書いて保守しています。`xefmctl` への XeFM 自身の制限は、どのエージェントにもかかります。

## 関連項目

- [xefmctl](XEFMCTL_FEATURE.ja.md)：エージェントが使うコマンド
- [AI エージェント向けの XeFM スキル](AGENT_SKILL_FEATURE.ja.md)：自分で動かすエージェントにスキルをインストールする
- [ターミナル](TERMINAL_FEATURE.ja.md)：ターミナルセッションと画面
