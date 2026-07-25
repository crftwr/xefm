"""``python -m xefm`` entry point — defers to the same ``main`` the ``xefm``
console script and the macOS/Windows bundle launchers call."""

from xefm.app import main

if __name__ == "__main__":
    main()
