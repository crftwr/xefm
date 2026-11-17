# 外部ターミナル（デスクトップモード）

[English](EXTERNAL_TERMINAL_FEATURE.md) \| 日本語

ターミナルモードでは、XeFM はターミナルを必要とするものに自分のターミナルを貸します。サブシェル（`subshell`、Shift-X）や、`'options': {'terminal': True}` を指定した `PROGRAMS` のエントリ（`vim`、`less`、REPL など）です。デスクトップアプリには自前のターミナルがないので、代わりにターミナルを開きます。現在のディレクトリで、シェルまたはそのプログラムを実行する新しいターミナルウィンドウです。

そのため、同じ `config.py` がどちらのモードでも動きます。違いは次のとおりです。

- **XeFM は待ちません。** ターミナルウィンドウは独立したアプリケーションです。XeFM は動き続け、そこで行った変更は、戻ったときの更新ではなく、ファイル監視によってペインに反映されます。
- **環境はスナップショットです。** `XEFM_*` 変数（ペインのディレクトリ、選択項目、`XEFM_ACTIVE`）と `[XeFM]` プロンプトマーカーは、ターミナルモードのサブシェルとまったく同じく、ウィンドウを開いた時点で設定されます。その後の XeFM での変更には追従しません。
- **ローカルディレクトリのみ**です。ターミナルモードと同じです。

`terminal: True` のプログラムがエラーで終了した場合は、Enter を押すまでウィンドウが開いたままになり、最後の出力を読めるようにします。サブシェルは、シェルが終了したときにそのターミナルが普段するのと同じようにウィンドウを閉じます。

## ターミナルを選ぶ

`~/.xefm/config.py` の `TERMINAL` でアプリケーションを選びます。その中で動くシェルはこれまでどおり `SUBSHELL` で選びます。

`None` のままにしておくと、代わりに XeFM 自身のターミナルで動きます。ウィンドウの中でペインの上に描画され、閉じるとペインに戻ります。このターミナルは libghostty の上で動き、macOS 版と Windows 版のアプリには libghostty が同梱されています。pip でインストールした XeFM が libghostty を見つけられるのは、システムのライブラリパスにインストールされている場合だけです。見つからない環境では、プラットフォームの既定のものが開きます。

| プラットフォーム | 既定 |
|---|---|
| macOS | Terminal.app |
| Windows | インストールされていれば Windows Terminal（`wt.exe`）、なければ新しいコンソールウィンドウ |

XeFM 自身のターミナルではなくターミナルアプリケーションを使うには、そのコマンドラインを指定します。XeFM が実行したいものは末尾の引数として付け加えられるので、ターミナルにコマンドを実行させるときと同じ形で指定してください。

```python
TERMINAL = ['open', '-a', 'iTerm']        # macOS: an app that runs a script it opens
TERMINAL = ['wezterm', 'start', '--']     # takes the command as trailing arguments
TERMINAL = ['alacritty', '-e']
TERMINAL = ['wt.exe', '-w', '0', 'nt']    # Windows Terminal: a tab in the current window
```

文字列でもかまいません（`'wezterm start --'`）。シェルと同じように分割されます。スペースを含む Windows のパスにはリストを使ってください。

## 何も開かない場合

ログペインに理由が表示されます。

- *No terminal configured: set TERMINAL* — プラットフォームに既定のターミナルがありません。設定してください。
- *Terminal not found: …* — `TERMINAL` のコマンドがインストールされていないか、`PATH` 上にありません。

## 関連項目

- [外部プログラム](EXTERNAL_PROGRAMS_FEATURE.ja.md) — `PROGRAMS` と `terminal: True`
- [ユーザーガイド — サブシェル](XEFM_USER_GUIDE.ja.md#サブシェル) — プロンプトマーカーと `SUBSHELL`
