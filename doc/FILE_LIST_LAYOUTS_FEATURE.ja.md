# ファイルリストのレイアウト

[English](FILE_LIST_LAYOUTS_FEATURE.md) \| 日本語

ファイルリストの行に何を表示するかは、組み合わせて使う 2 つのもので決まります。

- **レイアウト**は、行の見せ方です。名前、拡張子、サイズ、日付といったいつもの列のうちどれを、どの順に並べ、それぞれをどう書くかを決めます。好みやペインの幅で決まるものなので、タブごとに選び、フォルダーを移っても変わりません。XeFM に付属するのは **Default** の 1 つで、`config.py` で別のものを足せます。日付を `13:24` と書くもの、拡張子を名前と一緒に表示するもの、名前とサイズだけのものなどです。
- **追加の情報**（extra）は、フォルダーの中身に応じて加わる情報です。システムがタグを管理している場所でのタグ、作業ツリーの中での Git の状態、拡張パッケージが持ち込むものなどがあります。追加の情報はそれぞれ、どこで使うかを自分で知っていて、列の文字の横に印を付けたり列を足したりします。タブのレイアウトの上に、いくつでも同時に表示できます。組み込みのものは **Tags**（名前の後ろの色付きの点）の 1 つです。

レイアウトや追加の情報が表示する値を**属性**と呼びます。名前、拡張子、サイズ（フォルダーは計算済みの合計）、日付、タグは組み込みで、`config.py` や拡張パッケージで独自のものを足せます。

> **プレビュー。** `ATTRIBUTES`、`LAYOUTS`、`DEFAULT_LAYOUT`、`LAYOUT_EXTRAS` は、どのリリースでもまだ変わる可能性があります。設定でこれらを使うと、XeFM はそのことをログに 1 行出します。[カスタマイズ](CUSTOMIZATION_FEATURE.ja.md)を参照してください。

## レイアウトを選ぶ

**View → Layout ▸** にすべてのレイアウトが並びます。選択はアクティブなペインの現在のタブに属します。タブはそれぞれ自分の選択を持ち、新しいタブは開いた元のタブの選択を引き継ぎ、XeFM はセッションをまたいで覚えています。一度も選んでいないタブは `DEFAULT_LAYOUT` で始まります。`choose_layout` アクションは同じ選択をダイアログで開きます。コマンドパレットからも使えます。

## 追加の情報の表示を切り替える

**View → Show ▸** には、追加の情報ごとの項目があり、アクティブなペインのタブについて 3 つの状態から選べます。

- **Auto** — すべてのタブはこの状態で始まります。その情報が当てはまるフォルダーで表示します（作業ツリーの中での Git の状態、システムがタグを管理している場所でのタグ）。
- **On** — このタブではどこでも表示します。
- **Off** — このタブでは表示しません。

ソートやフィルターと同じく、状態はタブに属します。セッションをまたいで残り、そのタブから開いた新しいタブに引き継がれます。`choose_extras` アクションで、同じ操作をキーボードからできます。

追加の情報を持ち込む拡張パッケージは、インストールするだけで、当てはまる場所に表示されます。`config.py` に何か書く必要はありません。

### 印の位置と意味

- **印は、付けた文字のすぐ前か後ろに描きます。** 印のある行だけで、その行の文字が場所を譲ります。印のない行のために場所を空けておくことはしないので、前に印の付いた名前は、まわりの名前より少し右から始まります。印どうしは形と色で区別します。
- **名前の後ろ**の印は、タグの点と同じく名前に続けて描きます。区別は印の形と色で行います。
- **独自の列**は、値をどの行でも同じ位置に出したいときのもう 1 つの方法です。たとえば名前の前に置けます。追加の情報の列は、フォルダー内でいちばん長い値の幅になります。
- **持っているファイルがなければ場所を取りません。** Git の状態を持つファイルが 1 つもないフォルダーでは、Git の印も Git の列も出ず、追加の情報がないときと同じ詰まった行になります。

**F1**（ヘルプ）は、アクティブなペインに印が表示されていると、**Markers in this pane** の節から始まります。有効な追加の情報が描く印のすべてについて、その色と意味が並びます。

2 つの追加の情報が同じ印を同じ色で描く場合（Git の変更を表す黄色の `●` は、黄色のタグとまったく同じに見えます）、設定を読み込んだときに XeFM がログペインでそのことを知らせます。

## フォルダーのサイズなどの属性を確定させる

属性の中には、すべての行について自動で求めるには時間がかかりすぎるものがあり、XeFM は頼まれたときだけ求めます。サイズの列はフォルダーについては `<DIR>` と表示します。フォルダーにどれだけ入っているかを知るには、その下のすべてを数える必要があるためです。自分で定義した属性も、このような値にできます（後述の `compute`）。

**View → Resolve Attribute…**（`resolve_attribute`）は、選択項目、選択がなければカーソル位置の項目について、これらの属性を 1 つ求めます。ダイアログに対象の項目と、このペインでそれについて求められる属性が名前で並びます（既定のレイアウトでは **Size**）。求められるものが 1 つだけでもダイアログを出すので、何を実行するのかが常に分かります。ここにあるフォルダーをすべて対象にするときは、先にすべて選択してください。

処理はバックグラウンドで進み、終わったものから結果が表示されます。フォルダーを離れると止まります。合計はそのフォルダーにいる間は残ります。途中で中身が変わったフォルダーは、もう一度求めるまで `<DIR>` に戻ります。

## ペインに表示しているものでソートする

ソートダイアログ（`sort`）は、自身のソートキーの後に、ペインが表示しているもののうちソートキーにないものを並べます。既定のレイアウトでは **Size with folder totals**（組み込みの **Size** はファイルだけを並べます）、Git の状態の追加の情報が表示されていればその状態です。このような行でソートすると、次のようになります。

- 並ぶのは**このフォルダーだけ**です。別のフォルダーへ移ると、ペインは前のソートに戻ります。戻ってきたら、もう一度選んでください。
- ペインがすでに持っている値を使います。値のない行（サイズを計算していないフォルダーなど）は、昇順でも降順でも最後になります。
- 自動で埋まるものは、値が届いている途中はグレー表示です。すべての行に値がそろうと選べるようになります。

**View → Sort By ▸ Reverse Sort** で、ほかのソートと同じく順序を逆にできます。ステータスバーには「(this folder)」付きで表示されます。

## 自分で定義する

**Tools → Edit Configuration…**（設定ファイルを編集）を開きます。以下のテーブルは、ファイル内でそれぞれの上にあるコメントに、例付きで説明があります。

### `ATTRIBUTES` — エントリについて XeFM が知ることのできる値

値は 1 つの関数 `read(directory, entries)` がバックグラウンドで計算します。`entries` は 1 つのフォルダーの行、`directory` はそのフォルダーで、関数はエントリごとに 1 つの値を同じ順で返します。XeFM はフォルダー全体を一度に渡すので、`git status` のようにフォルダー全体に一度に答えられる情報源は、ファイルごとではなく 1 回だけ呼ばれます。

```python
import subprocess

def line_count(directory, entries):
    def count(entry):
        with open(entry.path, 'rb') as f:
            return sum(1 for _ in f)
    return [count(e) for e in entries]

def git_status(directory, entries):
    try:
        def git(*args):
            return subprocess.run(['git', *args], cwd=str(directory), check=True,
                                  capture_output=True, text=True).stdout
        prefix = git('rev-parse', '--show-prefix').strip()
        items = git('status', '--porcelain', '-z', '--', '.').split('\0')
    except (OSError, subprocess.CalledProcessError):
        return [None] * len(entries)        # not a Git working tree
    codes, skip = {}, False
    for item in items:
        if skip or len(item) < 4:
            skip = False
            continue
        code, path = item[:2], item[3:]
        skip = code[0] in 'RC'              # a rename's old path follows
        if path.startswith(prefix):
            # the entry here the change is in: a file, or the folder holding it
            name = path[len(prefix):].split('/')[0]
            codes.setdefault(name, code.strip()[:1])
    return [codes.get(e.path.name) for e in entries]

class Config:
    ATTRIBUTES = {
        'lines': {'label': 'Lines', 'type': 'count', 'read': line_count},
        'git': {
            'label': 'Git status', 'type': 'enum', 'read': git_status,
            'values': {
                'M': {'label': 'Modified',  'color': 'yellow'},
                'A': {'label': 'Added',     'color': 'green'},
                '?': {'label': 'Untracked', 'color': 'muted'},
            },
        },
    }
```

| キー | 意味 |
|---|---|
| `read` | 関数 `read(directory, entries)`。`entries` と同じ順で、エントリごとに 1 つの値を返します。 |
| `label` | ソートダイアログに表示する名前。 |
| `type` | `text`、`count`、`size`（バイト数）、`time`（タイムスタンプ）、`enum`（`values` のどれか）、`tags`。値の書き方とソートのしかたが決まります。 |
| `values` | `enum` の場合の、各値の意味と表示色。ヘルプに並ぶのはこの意味です。 |
| `where` | 問い合わせるストレージ：`local`（既定）、`archive`、`ssh`、`s3`。ファイルごとの呼び出しは、ディスクなら軽く、S3 では 1 件ごとにリクエストになります。 |
| `compute` | `auto`（既定）または `on_request`。 |

属性を定義しただけでは、どこにも表示されません。表示するのは追加の情報かレイアウトです。画面上の何かが属性を表示すると、その値は**フォルダーのすべての行**についてバックグラウンドで計算されます。そのため、定義はフォルダー 1 つ分にすぐ答えられるものにしてください。それができないもの（たとえば、すべてのファイルを丸ごと読むもの）は `'compute': 'on_request'` とします。その場合は、頼んだときだけ計算されます。**View → Resolve Attribute…**（`resolve_attribute`）で、選択項目またはカーソル位置の項目について求めます。このときは 1 回の呼び出しに 1 エントリずつ渡すので、値は 1 つずつ表示され、フォルダーを離れると止まります。

値は届くまで空欄です。関数が失敗したり、長さの違うリストを返したりしても、失われるのはその呼び出しの値だけで、そのことをログペインに 1 回だけ出します。

自分の関数（ソートキー、フィルター、アクション）からは、XeFM がすでに持っている値を `entry.attr('git')` で読めます。値を計算することも待つこともありません。値が届くまでは `None` です。

### `LAYOUTS` と `DEFAULT_LAYOUT` — 行の見せ方

```python
class Config:
    LAYOUTS = {
        'short': {'label': 'Short time', 'columns': [
            'name', 'ext', 'size',
            {'attr': 'mtime', 'format': 'recent', 'priority': 1}]},
        'names': {'label': 'Names only', 'columns': ['name']},
    }
    DEFAULT_LAYOUT = 'short'
```

列は属性の名前か、次のキーを持つ辞書で書きます。

| キー | 意味 |
|---|---|
| `attr` | 表示する属性。 |
| `format` | 書き方。書式の名前（後述）か、自分の関数。 |
| `width` | 幅（文字数）。各書式に既定の幅があります。 |
| `align` | `left` または `right`。数値と日付は右寄せです。 |
| `priority` | ペインの幅が足りないとき、優先度を持つ列が低いものから外れます。優先度のない列は残ります。 |

どのレイアウトにも `name` 列があり、ほかの列が残した幅を使います。`ext` を書かなければ、拡張子は名前の一部として表示されます。組み込みの `name`、`ext`、`size`（ファイルのサイズ、またはフォルダーの計算済みの合計）、`mtime`、`tags` は、どのレイアウトでも使えます。レイアウトに `'default'` という名前を付けると組み込みのものを置き換えます。打ち間違いで置き換わらないよう、`'override': True` が必要です。

**書式**

| 型 | 書式（最初のものが既定） |
|---|---|
| `size` | `compact`（`12.3K`）、`bytes`（`12,345`） |
| `time` | `short`、`full`（既定ではこの 2 つを `DATE_FORMAT` が選びます）、`iso`、`relative`（`5 min ago`）、`recent`（今日なら `13:24`、今年なら `10/21`、それより前は `2024`） |
| `enum` | `letter`（値そのもの）、`word`（`values` のラベル）。どちらもその値の色で表示 |
| `tags` | `dots`、`names` |
| `count` | `number` |
| `text` | `text` |

自分の関数は `(value, entry)` を受け取り、文字列を返します。色を付けるときは `Cell` を、複数ならそのリストを返します。値の計算中は `value` が `None` です。`Cell` の `color` には `'muted'`、`'accent'`、`'accent2'`、`'text'`、色の名前（`'red'`、`'green'`、`'yellow'`、`'blue'`、`'purple'`、`'orange'`、`'gray'`）、`(r, g, b)` のどれかを指定します。`bold` や `italic` も指定できます。選択、カーソル、非アクティブなペインの減光はこの上にかかるので、色の指定で行が読めなくなることはありません。

### `LAYOUT_EXTRAS` — フォルダーが加える情報

```python
from xefm.user_api import Cell

GIT_MARK = {'M': Cell('M', color='yellow'),
            'A': Cell('A', color='green'),
            '?': Cell('?', color='muted')}

def git_mark(value, entry):
    return GIT_MARK.get(value, '')

def in_git_tree(path):
    return any((p / '.git').exists() for p in (path, *path.parents))

class Config:
    LAYOUT_EXTRAS = {
        'git': {
            'label': 'Git status',
            'when': in_git_tree,
            'markers': [{'attr': 'git', 'format': git_mark,
                         'on': 'name', 'side': 'before'}],
            'columns': [{'attr': 'git', 'format': 'word', 'replace': 'mtime'}],
        },
    }
```

| キー | 意味 |
|---|---|
| `label` | **View → Show** とヘルプに表示する名前。 |
| `when` | **Auto** のときに表示する場所：`'always'`（既定）、`'never'`、パスのパターン（`'s3://*'`）、またはフォルダーのパスを受け取る関数。関数はバックグラウンドで動くので、ディスクを見ても構いません。 |
| `markers` | 列の文字の横に付ける印（後述）。 |
| `columns` | 足す列（後述）。 |

**印（マーカー）** は、属性の名前か、次のキーを持つ辞書で書きます。`attr`、`format`、`on`（印を付ける列。既定は `'name'` で、タブのレイアウトにその列がないときも名前に付きます）、`side`（`'before'` または既定の `'after'`）、`limit`（書式の結果のうち表示する個数の上限。タグの点は 3 つ）です。印のない行では場所を取りません。タグの点と見間違えない印を選んでください。

**列**は、レイアウトの列と同じキーに加えて、置く場所を指定します。`before` / `after` で指定した列の前 / 後ろに、`replace` で指定した列の代わりに置きます。`replace` は場所を節約するためのもので、その列の位置と、指定しなければその列の優先度を引き継ぎます。どれも指定しないとき、または指定した列がレイアウトにないときは末尾に置きます。名前の前に置いた列は、どの行でも値が同じ位置に出ます。名前の前の印は、名前と一緒に動きます。列の幅はフォルダー内でいちばん長い値に合わせ、値を持つファイルが 1 つもないフォルダーでは列ごと出しません。

**自分で書いていない追加の情報を変える。** `LAYOUT_EXTRAS` に同じ名前で、変えたいキーだけを書きます。残りは組み込みや拡張パッケージの定義のままです。

```python
class Config:
    LAYOUT_EXTRAS = {
        'tags': {'when': 'never'},       # no tag dots unless turned On
        'git': {'when': 'always'},       # an extension's extra, everywhere
    }
```

### 拡張パッケージから

拡張パッケージは属性、レイアウト、追加の情報を提供できます（`[contributes.attributes]`、`[contributes.layouts]`、`[contributes.layout_extras]`。[拡張パッケージ](EXTENSIONS_FEATURE.ja.md)を参照）。追加の情報は自分の `when` を持っているので、パッケージをインストールした時点で当てはまる場所に表示されます。そこから先は **View → Show** と `config.py` の `LAYOUT_EXTRAS` で決めます。

## 関連項目

- [ソートダイアログ](SORT_DIALOG_FEATURE.ja.md)
- [ファイルのタグ](FILE_TAGS_FEATURE.ja.md)
- [ヘルプダイアログ](HELP_DIALOG_FEATURE.ja.md)
- [カスタマイズ](CUSTOMIZATION_FEATURE.ja.md)
- [メニューバー](MENU_BAR_FEATURE.ja.md)
