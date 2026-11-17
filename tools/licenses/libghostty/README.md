# libghostty-vt license texts

The desktop bundles (macOS `.app`, Windows zip and MSIX) ship libghostty-vt for
XeFM's terminal (`tools/fetch_libghostty.py`). Its official release carries
Ghostty's own `LICENSE` in the Windows zips only, not in the macOS xcframework,
and neither names the libraries compiled into it. These are fed to the bundle's
`THIRD_PARTY_NOTICES.txt` instead:

| File | Component | License |
|---|---|---|
| `ghostty-LICENSE.txt` | Ghostty / libghostty-vt 1.0.1 (from the release zip) | MIT |
| `simdutf-LICENSE-MIT.txt` | simdutf (compiled in) | MIT (dual MIT / Apache-2.0; MIT chosen) |
| `highway-LICENSE.txt` | Highway (compiled in, macOS build) | Apache-2.0 or BSD-3-Clause (file carries both) |
| `wuffs-LICENSE-MIT.txt` | Wuffs (compiled in) | MIT (dual MIT / Apache-2.0; MIT chosen) |

The compiled-in libraries were read off the library's symbols (`nm` on the
xcframework's `libghostty-vt.a`, `strings` on the DLLs). Check them again when
the pinned version moves.
