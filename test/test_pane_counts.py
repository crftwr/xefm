"""The pane footer's (dirs, files) count is kept until the listing changes.

``XeFMApp.counts`` walks the whole listing; the footer asks every frame, so the
answer is cached against the listing it came from. A listing replaces both
``files`` and ``file_info`` (it never edits them in place), so object identity
plus length is the whole key — these tests pin that it never serves an answer
for a listing it was not computed from.
"""

import types

from xefm.app import XeFMApp


def _app():
    return types.SimpleNamespace(_counts_memo={})


def _pane(names, dirs):
    files = [f"/x/{n}" for n in names]
    return {"files": files, "file_info": {f: {"is_dir": n in dirs} for f, n in zip(files, names)}}


def test_counts_dirs_and_files():
    assert XeFMApp.counts(_app(), _pane(["a", "b", "c"], {"b"})) == (1, 2)


def test_a_repeat_is_served_from_the_memo():
    app, pane = _app(), _pane(["a", "b"], {"a"})
    assert XeFMApp.counts(app, pane) == (1, 1)
    pane["file_info"][pane["files"][1]]["is_dir"] = True   # not how listings change...
    assert XeFMApp.counts(app, pane) == (1, 1)            # ...so the memo still answers


def test_a_new_listing_is_counted_again():
    app, pane = _app(), _pane(["a", "b"], {"a"})
    assert XeFMApp.counts(app, pane) == (1, 1)
    pane.update(_pane(["a", "b", "c", "d"], {"c", "d"}))
    assert XeFMApp.counts(app, pane) == (2, 2)


def test_a_listing_that_grew_in_place_is_counted_again():
    app, pane = _app(), _pane(["a"], set())
    assert XeFMApp.counts(app, pane) == (0, 1)
    pane["files"].append("/x/d")
    pane["file_info"]["/x/d"] = {"is_dir": True}
    assert XeFMApp.counts(app, pane) == (1, 1)


def test_panes_are_kept_apart():
    app = _app()
    left, right = _pane(["a"], {"a"}), _pane(["b", "c"], set())
    assert (XeFMApp.counts(app, left), XeFMApp.counts(app, right)) == ((1, 0), (0, 2))
    assert XeFMApp.counts(app, left) == (1, 0)
