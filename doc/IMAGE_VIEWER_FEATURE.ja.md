# 画像ビューアー

[English](IMAGE_VIEWER_FEATURE.md) \| 日本語

XeFM には画像ビューアーが内蔵されています。画像にカーソルを合わせて `view_file`（または **Enter**）を実行すると、ウィンドウ全体に画像が開きます。XeFM から離れることなく、ズーム、パン、同じディレクトリ内のほかの画像への移動ができます。

## 開き方

| アクション | 動作 |
|--------|--------------|
| `view_file` | フォーカスのあるファイルを表示します。画像なら画像ビューアーで開きます |
| `open_item` | 同上。ほかに `enter` のルールがないファイルの場合 |

対応している形式：PNG、JPEG、GIF、BMP、WebP、TIFF、ICO、TGA、netpbm 系（PPM/PGM/PBM/PNM）。

## 操作

ビューアー自身のフッターにキーが表示され、ビューアー内で `F1` を押すとすべてのキーが一覧できます。

| アクション | 動作 |
|--------|--------------|
| `image_viewer.zoom_in` | 拡大 |
| `image_viewer.zoom_out` | 縮小 |
| `image_viewer.zoom_reset` | 画像全体をウィンドウに合わせる |
| `image_viewer.pan_*` | パン（拡大中） |
| マウスのドラッグ | パン |
| マウスのスクロール | 拡大／縮小 |
| `image_viewer.next` / `.prev` | 次／前の画像 |
| `Home` / `End` | 最初／最後の画像 |
| `F1` | キーのヘルプ |
| `quit` / `Esc` | 閉じる |

ズームは*フィット*（画像全体がウィンドウに収まる状態）から始まり、1 段階ごとに 25% ずつ、最大 40 倍まで拡大します。端を越えてパンしようとしても、ズームの倍率が下がるのではなく境界で止まります。別の画像に移ると、ズームとパンはリセットされます。

ヘッダーには、ファイル名、一覧内での位置（`2/7`）、ピクセル単位の寸法、ファイルサイズが表示され、拡大中は現在の倍率も表示されます。

## 前／次への移動

`↓` と `↑` は、**ビューアーを開いたペインの画像**を、そこに表示されている順にたどります。つまり、ソート順とフィルターがそのままビューアーに引き継がれ、画像でないファイルは飛ばされます。一覧は両端で折り返します。

ペインのカーソルも一緒に動きます。別の画像に移ると（`Home`／`End` を含めて）、ファイル一覧のカーソルもそのファイルに移るので、ビューアーを閉じたときには、ちょうど見ていた画像の上にいます。

一覧はビューアーを開いた時点で固定されるので、バックグラウンドでディレクトリが更新されても、一覧がずれることはありません。新しいファイルを反映するには、いったん閉じて開き直してください。

## CRT / Pip-Boy テーマ

画面のポストエフェクト（グロー、走査線、ブルーム）があるテーマでは、画像を開いている間はエフェクトが止まり、フィルターがかかった画像ではなく実際のピクセルが見えます。ビューアーを閉じると自動で元に戻ります。

## ターミナルでの表示

すべてのターミナルが画像を表示できるわけではありません。XeFM は、使っているターミナルが対応しているインライン画像プロトコルを使います。

| ターミナル | プロトコル |
|----------|----------|
| kitty、Ghostty、WezTerm、Konsole | kitty graphics |
| iTerm2、mintty | iTerm2 inline images |
| foot、contour、mlterm、xterm（`-ti vt340`） | sixel |

**デスクトップアプリ**では、ターミナルが何であれ、画像は常に表示されます。

これらのプロトコルのどれにも対応していないターミナル（特に Terminal.app や VS Code のターミナル）では、画像の代わりに、形式、寸法、ファイルサイズを示すカードが表示されます。移動はできますが、拡大するものがないのでズームとパンは表示されません。画像そのものを見るには、上の表のターミナルを使うか、デスクトップアプリを使うか、`open_with_os` でファイルを OS の画像ビューアーに渡してください。

`PUIKIT_TERM_GRAPHICS` 環境変数（`kitty`、`iterm2`、`sixel`、`none`）で、プロトコルを強制したり無効にしたりできます。XeFM の判定が外れたときや、これらのシーケンスを横取りする `tmux`／`screen` の中で使うときに便利です。

```bash
PUIKIT_TERM_GRAPHICS=none xefm     # never try to draw images inline
PUIKIT_TERM_GRAPHICS=sixel xefm    # force sixel
```

## 形式

PNG、JPEG、GIF、BMP、WebP、TIFF、ICO、TGA、PNM 系に加えて、**AVIF**、**JPEG 2000**、**PSD**、**QOI**、**ICNS**、**DDS**、**CUR**、**APNG**、**PCX** に対応しています。これらはすべて XeFM に同梱されている [Pillow](https://python-pillow.org/) によるものなので、どのプラットフォームでも同じように使えます。

**HEIC、JPEG XL、カメラの RAW はマシンによって異なります。** XeFM はこれらのデコーダーを持たず、システムに任せているためです。

| | macOS | Windows | Linux |
|---|---|---|---|
| HEIC / HEIF | 対応（内蔵） | Store の *HEIF Image Extensions* と、HEIC の実際の中身をデコードする *HEVC Video Extensions* があれば対応 | [requirements.txt](PYTHON_PACKAGES_FEATURE.ja.md) に `pillow-heif` |
| AVIF | 対応 | 対応 | 対応 |
| JPEG XL | 対応（内蔵） | Windows にコーデックがあれば対応（最近のビルドにはあります） | [requirements.txt](PYTHON_PACKAGES_FEATURE.ja.md) に `pillow-jxl-plugin` |
| カメラの RAW（DNG、CR2、NEF、ARW…） | 下記参照 | 下記参照 | 下記参照 |

macOS では、プレビューや Quick Look と同じデコーダーで画像が描画されます。Windows では、インストールされている画像コーデックで描画されます。そのため、スマートフォンで撮った HEIC は、Mac なら何も設定せずに、Windows なら Store の拡張機能を入れたマシンで開けます。Linux では `pip install` 1 回で済みます。

**これは XeFM のバージョンではなく、マシンごとに決まります。** デスクトップアプリもターミナルアプリも同じ結果になります。Mac のターミナルで XeFM を実行しても HEIC は開き、システムのデコーダーで描画されてターミナルのインライン画像プロトコルに渡されます。（画像をまったく表示できないターミナルは別の問題です。上の*ターミナルでの表示*を参照してください。）

**Windows の列はバージョンの一覧ではありません。** XeFM がそこで提供するのは、マシンに実際にある WIC 画像コーデックです。それは Windows のビルド*と*、どの Store 拡張機能がインストールされているかによって決まるので、同じ XeFM を動かしている 2 台のマシンで結果が違うこともありえます。XeFM は決めつけずに起動時に問い合わせるので、この表で示せるのはどこを確認すればよいかだけです。（Windows 11 ビルド 26200 のあるマシンでの計測：デコーダー 14 個、拡張子 65 個。その中には、Store パッケージを何も入れていない JPEG XL も含まれていました。）

**XeFM が提供するのは、マシン上の何かが読める形式だけです。** `.heic` が画像ビューアーで開くなら、必ず画像が表示されます。「表示できません」というカードになることはありません。HEIC のデコーダーがないマシンでは、そのファイルは単に画像として扱われず、`view_file` はそのファイルに対してほかに設定してあるものにフォールバックします（下の*代わりに外部ビューアーで開く*を参照）。

### 形式を自分で追加する

カメラの RAW、SVG、DICOM など、どんな形式も設定に数行書くだけで追加できます。ファイルのバイト列を画像に変換する関数を書き、拡張子を指定します。

```python
import io

def open_raw(data):
    import rawpy                      # listed in ~/.xefm/requirements.txt
    from PIL import Image
    with rawpy.imread(io.BytesIO(data)) as raw:
        return Image.fromarray(raw.postprocess())

class Config:
    IMAGE_DECODERS = {
        '.dng': open_raw,
        '.cr2': open_raw,
        '.nef': open_raw,
    }
```

拡張子を登録すると、ビューアーがその形式を*提供する*ようにもなるので、`.dng` の上で `Enter` を押すと画像が開くようになります。関数が受け取るのはパスではなくファイルのバイト列なので、同じデコーダーが zip の中や S3 バケット上の画像にも使えます。XeFM がすでに読める拡張子を指定すると、そのデコーダーが自分のものに置き換わります。

詳しくは `doc/CUSTOMIZATION_FEATURE.md` を参照してください。設定ファイルの `IMAGE_DECODERS` のセクションに実例があります。

## 必要なもの

Pillow は XeFM に同梱されていて、上の一覧のほとんどをデコードします。Pillow のビルド済みパッケージがないマシン（32 ビット ARM の Linux など）では、XeFM は Pillow なしでインストールされます。そのような場合やほかの理由で Pillow がない場合でも、ビューアーは開き、移動もできますが、画像の代わりにメタデータのカードが表示されます。Pillow を手動でインストールすれば画像が表示されるようになります。

## リモートとアーカイブ内の画像

S3 上や SSH 越しの画像、アーカイブ内の画像も、ほかの画像と同じように開け、その途中でディスクに何かが書き込まれることはありません。バイト列はそのままデコーダーに渡されます。（唯一の例外は、OS にしか読めない形式です。たとえば `pillow-heif` のないマシンで zip の中にある HEIC を開く場合です。そのときは、ビューアーを開いている間だけ一時ファイルに置かれ、閉じると削除されます。）

## 代わりに外部ビューアーで開く

既定では、`view_file` は内蔵ビューアーを使い、`open_with_os` はファイルを OS のアプリに渡します。`view_file` も外部プログラムに送るには、設定の `FILE_ASSOCIATIONS` で `view` のエントリにそのプログラムを指定します。

```python
FILE_ASSOCIATIONS = [
    {
        'pattern': ['*.jpg', '*.jpeg', '*.png', '*.gif'],
        'open|view': ['open', '-a', 'Preview'],   # V leaves XeFM again
        'edit': ['open', '-a', 'GIMP'],
    },
]
```

`'view': None`（既定）にすると内蔵ビューアーが選ばれます。

> **アップグレードする場合：** 以前の XeFM の出荷時の既定では、`view` がプレビューに送られていました。既存の設定はそのまま保たれるので、`view_file` でまだプレビューが開き、XeFM の中で見たい場合は、上のようにそのエントリを変更してください。

## キーのカスタマイズ

ズーム、移動、パンのキーは、設定の `KEY_BINDINGS` で割り当てを変更できます。

```python
KEY_BINDINGS = {
    'image_viewer.zoom_in':      ['+', '='],
    'image_viewer.zoom_out':     ['-', '_'],
    'image_viewer.zoom_reset':   ['0'],
    'image_viewer.next':         ['DOWN'],
    'image_viewer.prev':         ['UP'],
    'image_viewer.pan_up':    ['Shift-UP'],
    'image_viewer.pan_down':  ['Shift-DOWN'],
    'image_viewer.pan_left':  ['Shift-LEFT'],
    'image_viewer.pan_right': ['Shift-RIGHT'],
}
```

`Home`／`End` は `image_viewer.first` と `image_viewer.last` というアクションで、同じように割り当て直せます。`KEY_BINDINGS` に書かなければ `Home`／`End` のままです。

設定がこれらのアクションより古い場合（`KEY_BINDINGS` にこれらがない場合）、ビューアーは以前のキーのままです。`n`／`p` で画像を移動し、矢印キーだけでパンします。現在の既定に切り替えるには、上のエントリを追加してください。

## 関連項目

- `doc/dev/IMAGE_VIEWER_IMPLEMENTATION.md` — 内部の仕組み
- `doc/CUSTOMIZATION_FEATURE.md` — 設定で定義できるさまざまなものの 1 つとしての `IMAGE_DECODERS`
- `doc/TEXT_VIEWER_FEATURE.md` — 画像以外のすべてを表示するビューアー
