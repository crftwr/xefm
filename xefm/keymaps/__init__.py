"""The keymap presets' key tables, one module each (#565, #597).

:mod:`.common` holds the keys every preset shares; :mod:`.afx`,
:mod:`.orthodox`, :mod:`.native` and :mod:`.vim` each hold one preset's own
keys as ``own_bindings()``, laid over the common table by
:func:`xefm.keymap_presets.table`. What a preset is called, how it is
described and whether it types ahead are in :mod:`xefm.keymap_presets`.
"""

from xefm.keymaps import afx, common, native, orthodox, vim  # noqa: F401
