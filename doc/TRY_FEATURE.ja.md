# 使い捨てのホームで XeFM を試す

[English](TRY_FEATURE.md) \| 日本語

`xefm try` は、一時的なホームフォルダーの中でターミナル版の XeFM を起動します。自分の `~/.xefm`（設定、お気に入り、拡張機能）は読まれることも変更されることもなく、一時的なホームは XeFM の終了時に削除されます。次のような用途に使えます。

- インストールする前に**拡張機能を試す**
- 変更を自動で**テストする**：スクリプトがキーを押し、画面の表示内容を保存します
- README やリリースノート用に**デモを録画する**

## 手で試す

```bash
xefm try                              # plain XeFM
xefm try --ext ./hello-xefm           # with an extension package
xefm try --config ~/.xefm/config.py   # with a copy of your config
```

XeFM はこのターミナルで開きます。キーマッププリセットは選択済みで、Tip of the Day はオフになっています。左のペインにはいくつかのサンプルファイルが開きます。いつもどおりに XeFM を終了してください。

| オプション | 動作 |
|---|---|
| `--ext SOURCE` | この拡張パッケージをインストールします。フォルダー、`.zip`、`https://` の zip、`github:owner/repo` のいずれかです。複数指定するには繰り返します |
| `--config FILE` | XeFM のテンプレートの代わりにこの `config.py` を使います。XeFM はコピーを使うので、元のファイルは変更されません |
| `--keymap afx` / `orthodox` / `native` / `vim` | [キーマッププリセット](KEYMAP_PRESETS_FEATURE.ja.md)（既定：`afx`） |
| `--left DIR`、`--right DIR` | サンプルの代わりにこれらのフォルダーを開きます |
| `--keep-home` | 一時的なホームを残し、その場所を表示します |

## スクリプトを実行する

```bash
xefm try --ext ./hello-xefm --keys steps.json --screens out/ --record demo.cast
```

`--keys` を付けると、XeFM は見えないところで専用のターミナルの中で動き、スクリプトに従います。各ステップのあとで画面をテキストとして保存します。スクリプトが終わると終了するので、待ったままのものは残りません。スクリプトはステップの JSON リストです。

```json
[
  {"intent": "open the command palette", "keys": ["Ctrl-T"]},
  {"intent": "find the action", "keys": [{"text": "hello"}]},
  {"intent": "run it", "keys": ["Enter"]}
]
```

- スクリプトが送るキーはプリセットのキーです。`Ctrl-T` は、ここでの既定である AFX スタイルではコマンドパレットを開きますが、どのプリセットでもそうとは限りません（[キーマッププリセット](KEYMAP_PRESETS_FEATURE.ja.md#すべてのキーの一覧)を参照）。
- キーは `Ctrl-T`、`Shift-Down`、`Enter`、`Esc`、`F5`、`a` のように書きます。`{"text": "..."}` はテキストを入力し、`{"pause": 2}` は 2 秒待ちます。
- 各ステップは、キーを送ったあと、画面の変化が止まるまで最大 10 秒待ちます。`"patience": 30` とするともっと長く待ちます。
- `intent` はそのステップの目的を書くものです。ステップと一緒に保存され、録画ではチャプターのタイトルになります。

| オプション | 動作 |
|---|---|
| `--screens DIR` | 画面の保存先（既定：`try-screens/`） |
| `--record FILE` | セッション全体を asciicast ファイルとしても録画します |
| `--size COLSxROWS` | ターミナルのサイズ（既定：`120x40`） |

`--screens` フォルダーの中身：

- `00.txt` は XeFM 起動直後の画面、`01.txt`、`02.txt`、… は各ステップのあとの画面です。画面の下の `--- highlighted ---` 以下には、選択したファイル、カーソル位置のメニュー項目、ステータスバーなど、色付きの背景で描かれた部分が、それぞれの行と列とともに並びます。
- `steps.jsonl` にはステップごとに 1 行が書かれます。キー、画面が落ち着いたかどうか、強調表示されていたもの、そのステップの間に XeFM が記録したすべてのメッセージ（エラーを含む）です。

録画は `asciinema play demo.cast` で再生でき、[agg](https://github.com/asciinema/agg) を使えば GIF にできます：`agg demo.cast demo.gif`

スクリプトには追加のパッケージ（`pip install 'quality-loop[tui]'`）が必要です。手で試す使い方と同じく、macOS、Linux、Windows で動きます。

### 知っておきたいこと

- 画面はプレーンテキストです。色が残るのは各画面の下の強調表示の一覧だけなので、選択を灰色で示すテーマではそこに現れません。
- 長いタスクの実行中は、その進捗のために画面が変化し続けるので、ステップは待ち時間の上限いっぱいまで待ちます。タスク中にキーを押す（キャンセルする）には、それらを待機と一緒に 1 つのステップに入れてください：`["Enter", {"pause": 1}, "Esc"]`
- ここでクリップボードにコピーしても、システムのクリップボードには届きません。

## 関連項目

- [拡張パッケージ](EXTENSIONS_FEATURE.ja.md)
- [AI エージェント向けの XeFM スキル](AGENT_SKILL_FEATURE.ja.md) — このスキルは、アシスタントが `xefm try` を使って自分の作業を確認する方法を教えます
