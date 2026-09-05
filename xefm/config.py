#!/usr/bin/env python3
"""
XeFM Configuration System

Manages user configuration for the Two-File Manager.
Configuration is stored in ~/.xefm/config.py as a Python class.
"""

import fnmatch
import importlib.util
import os
import platform
import sys
from xefm.path import Path
from xefm import sort_keys
from xefm.log_manager import getLogger




# Module-level logger
logger = getLogger("Config")


# --------------------------------------------------------------------------- #
# Key-binding tables (PuiKit keyboard contract)
#
# Key matching follows the PuiKit keyboard contract (puikit/docs/keyboard_contract.md;
# XeFM's side in doc/dev/KEY_BINDINGS_IMPLEMENTATION.md): events carry a canonical
# ``key`` string, the produced ``char``, and a ``modifiers`` set.
# A config token resolves to (identity, modifiers, mode):
#   mode "key"  -> match on event.key + exact modifiers (shift significant);
#                  letters and named keys.
#   mode "char" -> match on event.char (case-sensitive), ignoring shift/alt;
#                  digits and punctuation (the produced glyph is the identity).
# --------------------------------------------------------------------------- #

# Config modifier token (upper) -> contract modifier name.
_MODIFIER_ALIASES = {
    "SHIFT": "shift", "CONTROL": "ctrl", "CTRL": "ctrl",
    "ALT": "alt", "OPTION": "alt", "COMMAND": "cmd", "CMD": "cmd",
}

# Named non-text keys: config token (upper) -> PuiKit key identity.
_NAMED_KEYS = {
    "ENTER": "enter", "RETURN": "enter", "ESCAPE": "escape", "ESC": "escape",
    "TAB": "tab", "BACKSPACE": "backspace", "DELETE": "delete", "DEL": "delete",
    "INSERT": "insert", "SPACE": "space",
    "UP": "up", "DOWN": "down", "LEFT": "left", "RIGHT": "right",
    "HOME": "home", "END": "end",
    "PAGE_UP": "pageup", "PAGEUP": "pageup",
    "PAGE_DOWN": "pagedown", "PAGEDOWN": "pagedown",
    # A *bare Alt tap* — pressed and released with nothing in between — is a
    # named key of its own on the Windows terminal (PuiKit keyboard contract
    # §1), distinct from ALT the modifier prefix; XeFM binds it to 'menu'.
    "ALT": "alt",
}
_NAMED_KEYS.update({f"F{n}": f"f{n}" for n in range(1, 13)})

# Named punctuation: config token (upper) -> base (unshifted) glyph.
_PUNCT_NAMES = {
    "MINUS": "-", "EQUAL": "=", "EQUALS": "=",
    "LEFT_BRACKET": "[", "RIGHT_BRACKET": "]", "BACKSLASH": "\\",
    "SEMICOLON": ";", "QUOTE": "'", "APOSTROPHE": "'",
    "COMMA": ",", "PERIOD": ".", "DOT": ".", "SLASH": "/",
    "GRAVE": "`", "BACKTICK": "`", "BACKQUOTE": "`",
}

# US-layout shifted glyphs: a "Shift-<punct>" / "Shift-<digit>" token resolves
# to the character that key actually produces (matched on char).
_SHIFT_SYMBOL = {
    "-": "_", "=": "+", "[": "{", "]": "}", "\\": "|", ";": ":",
    "'": '"', ",": "<", ".": ">", "/": "?", "`": "~",
    "1": "!", "2": "@", "3": "#", "4": "$", "5": "%",
    "6": "^", "7": "&", "8": "*", "9": "(", "0": ")",
}

# Identity aliases for key names that differ from the contract vocabulary.
_KEY_ALIASES = {"page_up": "pageup", "page_down": "pagedown"}


class KeyBindings:
    """
    Manages key bindings and provides lookup functionality.
    
    This class encapsulates all key binding logic, including:
    - Parsing key expressions with modifiers
    - Matching KeyEvents against configured bindings
    - Looking up actions from key events
    - Looking up key expressions from actions
    """
    
    def __init__(self, key_bindings_config: dict):
        """
        Initialize KeyBindings with configuration.
        
        Args:
            key_bindings_config: KEY_BINDINGS dictionary from Config
        """
        self.logger = getLogger("KeyBindings")
        self._bindings = key_bindings_config
        
        # Build reverse lookup: (main_key, modifiers) -> [(action, selection_req), ...]
        self._key_to_actions = self._build_key_lookup()

        # Per-context compiled tables (see _context_entries), built on first use
        # and dropped whenever the action registry changes — which is what makes
        # a config reload's new user actions bindable without a restart.
        self._context_cache: dict = {}
        self._context_generation = None
    
    def _parse_key_expression(self, key_expr: str) -> tuple:
        """
        Parse a config key token into ``(identity, modifiers, mode)`` per the
        PuiKit keyboard contract (puikit/docs/keyboard_contract.md §2; XeFM's
        token map in doc/dev/KEY_BINDINGS_IMPLEMENTATION.md).

        Returns:
            Tuple ``(identity, modifiers, mode)``
            - identity: PuiKit key name (``"a"``, ``"enter"``, ``"pageup"``) for
              ``mode == "key"``, or the produced glyph (``"?"``, ``"="``, ``"+"``)
              for ``mode == "char"``.
            - modifiers: ``frozenset`` of contract modifier names
              (``shift``/``ctrl``/``alt``/``cmd``).
            - mode: ``"key"`` (match on ``event.key`` + exact modifiers; letters
              and named keys) or ``"char"`` (match on ``event.char``, ignoring
              shift/alt; digits and punctuation).

        Examples:
            "Q" / "q"      -> ("q", frozenset(), "key")         # lowercase press
            "Shift-A"      -> ("a", {"shift"}, "key")           # uppercase press
            "?"            -> ("?", frozenset(), "char")
            "Shift-Down"   -> ("down", {"shift"}, "key")
            "EQUAL"        -> ("=", frozenset(), "char")
            "Shift-EQUAL"  -> ("+", frozenset(), "char")        # shifted glyph
            "Command-ENTER"-> ("enter", {"cmd"}, "key")         # GUI-only chord
        """
        # Single-character token: letter -> key mode (lowercased); anything else
        # (digit or punctuation) -> char mode on the produced glyph.
        if len(key_expr) == 1:
            if key_expr.isalpha():
                return (key_expr.lower(), frozenset(), "key")
            return (key_expr, frozenset(), "char")

        # Modifier-prefixed token: split into modifier parts + the final key.
        parts = key_expr.split('-')
        key_part = parts[-1]
        mods = set()
        for part in parts[:-1]:
            name = _MODIFIER_ALIASES.get(part.upper())
            if name:
                mods.add(name)
            else:
                self.logger.warning(f"Unknown modifier in key expression: {part}")

        upper = key_part.upper()
        if upper in _NAMED_KEYS:
            return (_NAMED_KEYS[upper], frozenset(mods), "key")
        if upper in _PUNCT_NAMES:
            return self._punct_binding(_PUNCT_NAMES[upper], mods)
        if len(key_part) == 1 and key_part.isalpha():
            return (key_part.lower(), frozenset(mods), "key")
        if len(key_part) == 1:
            # Digit or literal punctuation carrying a modifier.
            return self._punct_binding(key_part, mods)

        self.logger.warning(f"Unknown key in expression: {key_expr}")
        return (key_part.lower(), frozenset(mods), "key")

    @staticmethod
    def _punct_binding(glyph: str, mods: set) -> tuple:
        """Build a char-mode binding for a punctuation/digit glyph, folding a
        Shift modifier into the produced (shifted) glyph so the identity is the
        character the key actually emits."""
        mods = set(mods)
        if "shift" in mods:
            glyph = _SHIFT_SYMBOL.get(glyph, glyph)
            mods.discard("shift")
        return (glyph, frozenset(mods), "char")

    @staticmethod
    def _event_identity(event) -> tuple:
        """Reduce a PuiKit ``Event`` to the contract triple
        ``(key, char, modifiers)``. Only ``page_up``/``page_down`` need
        aliasing; the rest of the vocabulary already matches."""
        key = getattr(event, "key", None)
        char = getattr(event, "char", None)
        mods = frozenset(getattr(event, "modifiers", ()) or ())
        if key in _KEY_ALIASES:
            key = _KEY_ALIASES[key]
        return key, char, mods

    @staticmethod
    def _matches(parsed: tuple, key, char, mods) -> bool:
        """Match a parsed binding against an event's contract triple."""
        identity, required, mode = parsed
        if mode == "char":
            # Ignore shift/alt (the glyph already encodes them); honour ctrl/cmd
            # only if the binding named them.
            sig = frozenset(m for m in mods if m in ("ctrl", "cmd"))
            want = frozenset(m for m in required if m in ("ctrl", "cmd"))
            return char is not None and char == identity and sig == want
        return key == identity and frozenset(mods) == required

    def _build_key_lookup(self) -> dict:
        """
        Build a reverse lookup table from key expressions to actions.
        
        Returns:
            Dictionary mapping (main_key, modifier_flags) to list of (action, selection_req) tuples
        """
        lookup = {}
        
        for action, binding in self._bindings.items():
            # Extract keys and selection requirement
            if isinstance(binding, list):
                keys = binding
                selection_req = 'any'
            elif isinstance(binding, dict) and 'keys' in binding:
                keys = binding['keys']
                selection_req = binding.get('selection', 'any')
            else:
                continue
            
            # Process each key expression
            for key_expr in keys:
                # Parse to (identity, modifiers, mode) and index by it.
                parsed = self._parse_key_expression(key_expr)
                lookup.setdefault(parsed, []).append((action, selection_req))

        return lookup

    def _check_selection_requirement(self, requirement: str, has_selection: bool) -> bool:
        """
        Check if selection requirement is satisfied.
        
        Args:
            requirement: 'required', 'none', or 'any'
            has_selection: Whether files are currently selected
        
        Returns:
            True if requirement is satisfied
        """
        if requirement == 'required':
            return has_selection
        elif requirement == 'none':
            return not has_selection
        else:  # 'any'
            return True
    
    # --- per-context resolution ------------------------------------------- #

    @staticmethod
    def _binding_parts(binding) -> tuple:
        """Split a ``KEY_BINDINGS`` value into ``(keys, selection)``, accepting
        both the plain-list and the extended-dict forms."""
        if isinstance(binding, (list, tuple)):
            return (list(binding), 'any')
        if isinstance(binding, dict) and 'keys' in binding:
            return (list(binding['keys'] or ()), binding.get('selection', 'any'))
        return ([], 'any')

    def _add_entries(self, entries: list, keys, name: str, selection: str) -> None:
        for key_expr in keys or ():
            entries.append((self._parse_key_expression(key_expr), name, selection))

    def _context_entries(self, context: str) -> list:
        """The compiled match table for one context: ``[(parsed_key, action,
        selection), ...]`` in the order a key is tried against them.

        Three sources feed it, each supplying the keys for any action the
        previous one did not:

        1. **Context-qualified** config entries (``'diff_viewer.quit': ['x']``) —
           a rebind that applies in this context alone, so it wins over the
           unqualified one.
        2. **Config entries under the action's own name**, in the config's own
           order, which is what makes two file-list actions sharing a key resolve
           exactly as they always have.
        3. **The action's built-in defaults**, for every name the config never
           mentions — the case that matters most in practice, because
           ``_copy_missing_fields`` can add a whole missing *field* to an old
           config but never a missing key inside ``KEY_BINDINGS``.

        Sources 1 and 2 accept an action's **old** names as well as its current
        one (``Action.aliases``), so a config written before a rename keeps
        working. Current names are matched first, so a config carrying both
        spellings gets the current one rather than whichever it happened to list
        first.

        Only names the context understands (its own, plus the inherited
        ``common`` ones) are considered at all. That is the substantive change
        from the flat table: the file list can no longer be hijacked by a key
        bound to a viewer-only action, and vice versa, regardless of dict order.
        """
        from xefm.actions import registry

        if self._context_generation != registry.generation:
            self._context_cache.clear()
            self._context_generation = registry.generation
        cached = self._context_cache.get(context)
        if cached is not None:
            return cached

        entries: list = []
        claimed: set = set()
        prefix = context + "."

        for key_name, binding in self._bindings.items():
            if not isinstance(key_name, str) or not key_name.startswith(prefix):
                continue
            # A dotted name that is itself a registered action (the viewer-local
            # actions) is an ordinary binding, handled in the next pass — not a
            # scoped override of some shorter name.
            if registry.resolve(context, key_name) is not None:
                continue
            target = registry.canonical(context, key_name[len(prefix):])
            if target is None or target in claimed:
                continue
            keys, selection = self._binding_parts(binding)
            self._add_entries(entries, keys, target, selection)
            claimed.add(target)

        # Current names before old ones, so a config carrying both spellings of
        # a renamed action resolves to the current entry.
        for exact_only in (True, False):
            for key_name, binding in self._bindings.items():
                if not isinstance(key_name, str):
                    continue
                if exact_only:
                    target = key_name if registry.resolve(context, key_name) else None
                else:
                    target = registry.canonical(context, key_name)
                if target is None or target in claimed:
                    continue
                keys, selection = self._binding_parts(binding)
                self._add_entries(entries, keys, target, selection)
                claimed.add(target)

        for action in registry.actions(context):
            if action.name in claimed:
                continue
            self._add_entries(entries, action.resolved_default_keys(),
                              action.name, action.resolved_selection())

        self._context_cache[context] = entries
        return entries

    def _context_binding(self, context: str, action: str) -> tuple:
        """``(keys, selection)`` for one action in one context, using the same
        three-source order as :meth:`_context_entries`."""
        from xefm.actions import registry

        name = registry.canonical(context, action)
        if name is None:
            # A name this context does not understand has no keys *here*, even
            # when KEY_BINDINGS binds it — otherwise this would disagree with
            # _context_entries, which never considers such a name at all.
            return ([], 'any')
        resolved = registry.resolve(context, name)
        # Every spelling the config may have used, current first.
        spellings = [name] + [old for old, current
                              in registry.aliases_in(context).items()
                              if current == name]
        for spelling in spellings:
            qualified = f"{context}.{spelling}"
            if qualified in self._bindings and registry.resolve(context, qualified) is None:
                return self._binding_parts(self._bindings[qualified])
        for spelling in spellings:
            if spelling in self._bindings:
                return self._binding_parts(self._bindings[spelling])
        return (list(resolved.resolved_default_keys()),
                resolved.resolved_selection())

    def find_action_for_event(self, event, has_selection: bool = False,
                              context: str | None = None):
        """
        Find the action bound to a key event, respecting selection requirements.

        Args:
            event: PuiKit ``Event``
            has_selection: Whether files are currently selected
            context: The key-consuming surface asking (``'filer'``,
                ``'text_viewer'``, …). With ``None`` the historical flat lookup
                over the whole ``KEY_BINDINGS`` dict is used, which is what
                callers that predate contexts still want.

        Returns:
            Action name if found, None otherwise
        """
        if not event:
            return None

        key, char, mods = self._event_identity(event)

        if context is not None:
            for parsed, action, selection_req in self._context_entries(context):
                if (self._matches(parsed, key, char, mods)
                        and self._check_selection_requirement(selection_req, has_selection)):
                    return action
            return None

        # Try to match against all key bindings
        for parsed, actions in self._key_to_actions.items():
            if self._matches(parsed, key, char, mods):
                # Found a matching key - check selection requirements
                for action, selection_req in actions:
                    if self._check_selection_requirement(selection_req, has_selection):
                        return action

        return None

    def is_action_for_event(self, event, action: str, has_selection: bool = False,
                            context: str | None = None) -> bool:
        """Whether ``event`` triggers a *specific* ``action``.

        Unlike :meth:`find_action_for_event` — which returns the single,
        globally-first action bound to a key — this tests one named action, so a
        caller can safely handle a key that another action also uses elsewhere.
        The text viewer's ``toggle_wrap`` and the file list's
        ``compare_selection`` both bind ``W``; asking about one by name gets the
        right answer regardless of dict order.

        Passing a ``context`` is the better tool for that job now — a surface
        resolving in its own context cannot see another's actions at all — but
        this stays for callers that want to test a single name.

        Args:
            event: PuiKit ``Event``
            action: The action name to test.
            has_selection: Whether files are currently selected.

        Returns:
            True when ``event`` matches one of ``action``'s configured keys and
            the action's selection requirement is satisfied.
        """
        if not event:
            return False
        keys, selection_req = self.get_keys_for_action(action, context)
        if not keys or not self._check_selection_requirement(selection_req, has_selection):
            return False
        key, char, mods = self._event_identity(event)
        return any(self._matches(self._parse_key_expression(k), key, char, mods)
                   for k in keys)

    def get_keys_for_action(self, action: str, context: str | None = None) -> tuple:
        """
        Get the key expressions and selection requirement for an action.
        
        Args:
            action: Action name
            context: Resolve as that context would (honouring a scoped
                ``'<context>.<action>'`` rebind and the action's built-in
                defaults). ``None`` reads the flat ``KEY_BINDINGS`` dict alone.
        
        Returns:
            Tuple of (key_expressions, selection_requirement)
            - key_expressions: List of key expression strings
            - selection_requirement: 'required', 'none', or 'any'
        """
        if context is not None:
            return self._context_binding(context, action)

        if action not in self._bindings:
            return ([], 'any')
        
        binding = self._bindings[action]
        
        # Extract keys and selection requirement
        if isinstance(binding, list):
            return (binding, 'any')
        elif isinstance(binding, dict) and 'keys' in binding:
            keys = binding['keys']
            selection_req = binding.get('selection', 'any')
            return (keys, selection_req)
        
        return ([], 'any')
    
    #: Display labels for named (non-literal) key tokens, so the keymap's
    #: internal names render as conventional UI labels rather than raw
    #: uppercase tokens (e.g. ``ENTER`` -> ``Enter``, ``UP`` -> ``↑``).
    _KEY_DISPLAY = {
        'ENTER': 'Enter', 'RETURN': 'Enter',
        'BACKSPACE': 'Backspace',
        'TAB': 'Tab',
        'SPACE': 'Space',
        'DELETE': 'Del',
        'ESCAPE': 'Esc', 'ESC': 'Esc',
        'INSERT': 'Ins',
        'UP': '↑', 'DOWN': '↓', 'LEFT': '←', 'RIGHT': '→',
        'PAGE_UP': 'PgUp', 'PAGE_DOWN': 'PgDn',
        'HOME': 'Home', 'END': 'End',
        'EQUAL': '=',
    }

    #: Modifier display names, abbreviated to conventional short forms and keyed
    #: by upper-case form.
    _MOD_DISPLAY = {
        'COMMAND': 'Cmd', 'CMD': 'Cmd',
        'CONTROL': 'Ctrl', 'CTRL': 'Ctrl',
        'OPTION': 'Opt', 'ALT': 'Alt',
        'SHIFT': 'Shift', 'META': 'Meta',
    }

    def format_key_for_display(self, key_expr: str) -> str:
        """
        Format a key expression for display in UI.

        Args:
            key_expr: Key expression string

        Returns:
            Formatted string suitable for display

        Examples:
            "q" -> "q"
            "ENTER" -> "Enter"
            "Shift-EQUAL" -> "Shift-="
            "Command-Shift-X" -> "Cmd-Shift-X"
        """
        # Single literal character (letter, digit, punctuation) - return as-is.
        if len(key_expr) == 1:
            return key_expr

        parts = key_expr.split('-')
        base = parts[-1]

        # Base key: map a named token (ENTER, UP, EQUAL, …) to its UI label;
        # keep a bare literal char as-is; title-case any other multi-char token.
        base_disp = self._KEY_DISPLAY.get(base.upper())
        if base_disp is None:
            base_disp = base if len(base) == 1 else base.capitalize()

        # Modifiers: abbreviate to conventional short forms (Command -> Cmd, …).
        mods = [self._MOD_DISPLAY.get(part.upper(), part.capitalize())
                for part in parts[:-1]]

        return '-'.join(mods + [base_disp])


def _load_template_config():
    """
    Load the Config class from _config.py template.
    
    Returns:
        Config class from _config.py, or None if loading fails
    """
    try:
        # Get the directory where this module is located
        current_dir = Path(__file__).parent
        template_file = current_dir / '_config.py'
        
        # Check if template file exists
        if not template_file.exists():
            logger.warning(f"Template file not found at {template_file}")
            return None
        
        # Load the template module
        spec = importlib.util.spec_from_file_location("_config_template", template_file)
        if spec is None or spec.loader is None:
            logger.warning("Could not create spec for template config")
            return None
        
        template_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(template_module)
        
        # Get the Config class
        if hasattr(template_module, 'Config'):
            return template_module.Config
        else:
            logger.warning("Config class not found in template file")
            return None
    
    except Exception as e:
        logger.error(f"Error loading template config: {e}")
        return None


def _copy_missing_fields(user_config, template_config_class):
    """
    Copy missing fields from template Config class to user config instance.
    
    Args:
        user_config: User's config instance (may be incomplete or empty)
        template_config_class: Template Config class from _config.py
    """
    if template_config_class is None:
        return
    
    # Get all class attributes from template (excluding private/magic attributes)
    template_attrs = {
        name: value 
        for name, value in vars(template_config_class).items()
        if not name.startswith('_')
    }
    
    # Copy missing attributes to user config
    copied_count = 0
    for name, value in template_attrs.items():
        if not hasattr(user_config, name):
            setattr(user_config, name, value)
            copied_count += 1
            logger.info(f"Added missing config field: {name}")
    
    if copied_count > 0:
        logger.info(f"Copied {copied_count} missing fields from template config")


class ConfigManager:
    """Manages XeFM configuration loading and saving"""
    
    def __init__(self):
        self.logger = getLogger("Config")
        self.config_dir = Path.home() / '.xefm'
        self.config_file = self.config_dir / 'config.py'
        self.user_tools_dir = self.config_dir / 'tools'
        self.config = None
        self._key_bindings = None
        
    def ensure_config_dir(self):
        """Ensure the configuration directory exists"""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            self.logger.warning(f"Could not create config directory {self.config_dir}: {e}")
            return False
    
    def ensure_user_tools_dir(self):
        """Create ~/.xefm/tools/ with the bundled example tool, first time only.

        Acts only when the directory does not exist yet, so a user who
        deletes the example never has it resurrected; existing files are
        never overwritten. Returns True when the directory was created."""
        if self.user_tools_dir.exists():
            return False

        try:
            self.user_tools_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info(f"Created user tools directory: {self.user_tools_dir}")
        except Exception as e:
            self.logger.warning(f"Could not create user tools directory {self.user_tools_dir}: {e}")
            return False

        try:
            example_src = Path(__file__).parent / 'tools' / 'example_tool.py'
            example_dst = self.user_tools_dir / 'example_tool.py'
            if example_src.exists() and not example_dst.exists():
                with open(example_src, 'r', encoding='utf-8') as f:
                    content = f.read()
                with open(example_dst, 'w', encoding='utf-8') as f:
                    f.write(content)
                self.logger.info(f"Created example tool: {example_dst}")
        except Exception as e:
            self.logger.warning(f"Could not copy example tool to {self.user_tools_dir}: {e}")

        return True

    def create_default_config(self):
        """Create a default configuration file by copying from template"""
        if not self.ensure_config_dir():
            return False
        
        try:
            # Get the directory where this module is located
            current_dir = Path(__file__).parent
            template_file = current_dir / '_config.py'
            
            # Check if template file exists
            if not template_file.exists():
                self.logger.warning(f"Template file not found at {template_file}")
                return False
            
            # Read the template file
            with open(template_file, 'r', encoding='utf-8') as f:
                template_content = f.read()
            
            # Write to user config file
            with open(self.config_file, 'w', encoding='utf-8') as f:
                f.write(template_content)
            
            self.logger.info(f"Created default configuration at: {self.config_file}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error creating default config: {e}")
            return False
    
    def load_config(self):
        """Load configuration from file or create default if not exists"""
        # First launch: seed ~/.xefm/tools/ before the config module executes,
        # so xefm_tool('example_tool.py') in a config resolves to the user copy.
        self.ensure_user_tools_dir()

        # Load template config class for filling in missing fields
        template_config_class = _load_template_config()
        
        # Check if config file exists
        if not self.config_file.exists():
            self.logger.info(f"Configuration file not found at: {self.config_file}")
            if self.create_default_config():
                self.logger.info("Created default configuration file")
            else:
                self.logger.warning("Could not create default configuration file")
                # Create empty config and fill from template
                class EmptyConfig:
                    pass
                self.config = EmptyConfig()
                _copy_missing_fields(self.config, template_config_class)
                return self.config
        
        # Try to load the configuration file
        try:
            # Load the config module dynamically
            spec = importlib.util.spec_from_file_location("user_config", self.config_file)
            if spec is None or spec.loader is None:
                raise ImportError("Could not load config file")
                
            config_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(config_module)
            
            # Get the Config class
            if hasattr(config_module, 'Config'):
                self.config = config_module.Config()
                self.logger.info(f"Loaded configuration from: {self.config_file}")
            else:
                raise AttributeError("Config class not found in configuration file")
                
        except Exception as e:
            self.logger.error(f"Error loading configuration: {e}")
            self.logger.info("Creating empty config and filling from template")
            # Create empty config and fill from template
            class EmptyConfig:
                pass
            self.config = EmptyConfig()
        
        # Copy any missing fields from template
        _copy_missing_fields(self.config, template_config_class)
        
        return self.config
    
    def get_config(self):
        """Get the current configuration, loading if necessary"""
        if self.config is None:
            self.load_config()
        return self.config
    
    def reload_config(self):
        """Reload configuration from file"""
        self.config = None
        self._key_bindings = None
        return self.load_config()
    
    def get_key_bindings(self) -> KeyBindings:
        """Get the KeyBindings instance for current configuration."""
        config = self.get_config()
        
        # Rebuild if config changed or not yet built
        if self._key_bindings is None:
            self._key_bindings = KeyBindings(config.KEY_BINDINGS)
        
        return self._key_bindings
    
    def validate_config(self, config):
        """Validate configuration values.

        Overlay the given config onto a complete default ``Config`` first (as
        loading does), so a config that overrides only some settings validates
        just those fields instead of raising ``AttributeError`` on the ones it
        omits."""
        from xefm._config import Config as _DefaultConfig
        merged = _DefaultConfig()
        for name in dir(config):
            if name.isupper():
                setattr(merged, name, getattr(config, name))
        config = merged

        errors = []

        # Validate desktop mode fonts (GUI only; TUI has no font feature). Each
        # names one family; missing glyphs fall back to the OS's native
        # substitution. `None` = the OS system default face for that role.
        if config.UI_FONT_NAME is not None and (
            not isinstance(config.UI_FONT_NAME, str) or not config.UI_FONT_NAME.strip()
        ):
            errors.append("UI_FONT_NAME must be a non-empty string or None")
        if config.MONO_FONT_NAME is not None and (
            not isinstance(config.MONO_FONT_NAME, str) or not config.MONO_FONT_NAME.strip()
        ):
            errors.append("MONO_FONT_NAME must be a non-empty string or None")
        
        if not isinstance(config.FONT_SIZE, int) or config.FONT_SIZE < 8 or config.FONT_SIZE > 72:
            errors.append("FONT_SIZE must be an integer between 8 and 72")

        # Validate ratios
        if not (0.1 <= config.DEFAULT_LEFT_PANE_RATIO <= 0.9):
            errors.append("DEFAULT_LEFT_PANE_RATIO must be between 0.1 and 0.9")
        
        if not (0.1 <= config.DEFAULT_LOG_HEIGHT_RATIO <= 0.5):
            errors.append("DEFAULT_LOG_HEIGHT_RATIO must be between 0.1 and 0.5")
        
        # Validate sort mode
        # Old spellings still validate: a config on disk predating the rename
        # says 'name' or 'date', and sort_keys.canonical resolves both.
        if not sort_keys.is_known(config.DEFAULT_SORT_MODE):
            errors.append("DEFAULT_SORT_MODE must be 'filename', 'extension', "
                          "'size' or 'timestamp'")

        # Validate the text viewer's encoding picker list. Only the shape is
        # checked here — an unknown codec name is a per-entry warning when the
        # picker builds (see xefm.text_encoding.picker_encodings), not a config
        # error that would block loading.
        if not isinstance(config.TEXT_ENCODINGS, (list, tuple)) or not all(
            isinstance(e, str) and e.strip() for e in config.TEXT_ENCODINGS
        ):
            errors.append("TEXT_ENCODINGS must be a list of non-empty encoding names")

        # Validate motion settings
        if not isinstance(config.REDUCED_MOTION, bool):
            errors.append("REDUCED_MOTION must be a boolean")

        # Validate incremental search settings
        if not isinstance(config.MIGEMO_SEARCH, bool):
            errors.append("MIGEMO_SEARCH must be a boolean")

        if not isinstance(config.MIGEMO_MIN_LENGTH, int) or config.MIGEMO_MIN_LENGTH < 1:
            errors.append("MIGEMO_MIN_LENGTH must be a positive integer")

        if config.MIGEMO_ROMAJI_TABLE not in ['default', 'azik']:
            errors.append("MIGEMO_ROMAJI_TABLE must be 'default' or 'azik'")

        # Validate file monitoring settings
        if not isinstance(config.FILE_MONITORING_ENABLED, bool):
            errors.append("FILE_MONITORING_ENABLED must be a boolean")
        
        if not isinstance(config.FILE_MONITORING_COALESCE_DELAY_MS, int) or config.FILE_MONITORING_COALESCE_DELAY_MS < 0:
            errors.append("FILE_MONITORING_COALESCE_DELAY_MS must be a non-negative integer")
        
        if not isinstance(config.FILE_MONITORING_MAX_RELOADS_PER_SECOND, int) or config.FILE_MONITORING_MAX_RELOADS_PER_SECOND < 1:
            errors.append("FILE_MONITORING_MAX_RELOADS_PER_SECOND must be a positive integer")
        
        if not isinstance(config.FILE_MONITORING_FALLBACK_POLL_INTERVAL_S, (int, float)) or config.FILE_MONITORING_FALLBACK_POLL_INTERVAL_S <= 0:
            errors.append("FILE_MONITORING_FALLBACK_POLL_INTERVAL_S must be a positive number")

        # ACTIONS / EVENT_HOOKS / SORT_KEYS / FILTERS (the Preview customization
        # API). Shape problems are reported here like every other config field —
        # all of them in one pass, each one skipping just its own entry — so a
        # typo in one action never costs a user the rest of their config.
        from xefm.user_api import validate_user_entries
        errors.extend(validate_user_entries(config))

        # 'auto_return' predates the non-blocking program launcher and is
        # ignored; surface it once per load so configs migrate off it.
        legacy = [prog.get('name', '?') for prog in (getattr(config, 'PROGRAMS', None) or [])
                  if isinstance(prog, dict) and 'auto_return' in (prog.get('options') or {})]
        if legacy:
            errors.append(
                "PROGRAMS option 'auto_return' is deprecated and ignored — launches "
                "never block XeFM; remove it, or use {'terminal': True} for "
                "full-screen terminal programs. Entries: " + ", ".join(legacy))

        return errors
    
    def get_key_for_action(self, action):
        """Get the key binding for a specific action"""
        config = self.get_config()
        
        if action in config.KEY_BINDINGS:
            binding = config.KEY_BINDINGS[action]
        else:
            return []
        
        # Handle both simple and extended formats
        if isinstance(binding, list):
            return binding
        elif isinstance(binding, dict) and 'keys' in binding:
            return binding['keys']
        
        return []
    
    def get_selection_requirement(self, action):
        """Get the selection requirement for a specific action"""
        config = self.get_config()

        if action in config.KEY_BINDINGS:
            binding = config.KEY_BINDINGS[action]
        else:
            return 'any'

        # Handle extended format
        if isinstance(binding, dict) and 'selection' in binding:
            return binding['selection']

        # Simple format defaults to 'any'
        return 'any'

    def is_key_bound_to_action_with_selection(self, key, action, has_selection):
        """Whether ``key`` triggers ``action`` given the current selection state.

        A key is "available" for an action when it is one of the action's bound
        keys AND the action's selection requirement is met: ``required`` needs a
        selection, ``none`` needs no selection, ``any`` always applies. ``key``
        may be a single-character string or an ``ord()`` keycode."""
        return is_key_bound_to_with_selection(key, action, has_selection)




# Global configuration manager instance
config_manager = ConfigManager()


def get_config():
    """Get the current configuration"""
    return config_manager.get_config()


def reload_config():
    """Reload configuration from file"""
    return config_manager.reload_config()


def find_action_for_event(event, has_selection: bool = False,
                          context: str | None = None):
    """
    Find the action bound to a KeyEvent.
    
    Args:
        event: PuiKit key ``Event``
        has_selection: Whether files are currently selected
        context: The key-consuming surface asking (see
            :meth:`KeyBindings.find_action_for_event`); ``None`` keeps the flat,
            context-free lookup.
    
    Returns:
        Action name if found, None otherwise
    """
    key_bindings = config_manager.get_key_bindings()
    return key_bindings.find_action_for_event(event, has_selection, context)


def is_action_for_event(event, action: str, has_selection: bool = False,
                        context: str | None = None) -> bool:
    """Whether ``event`` triggers a specific ``action`` (see
    :meth:`KeyBindings.is_action_for_event`). Lets a caller handle a key that a
    different action also binds elsewhere — e.g. the text viewer's
    ``toggle_wrap`` vs the file list's ``compare_selection``, both
    on ``W``."""
    key_bindings = config_manager.get_key_bindings()
    return key_bindings.is_action_for_event(event, action, has_selection, context)


def get_keys_for_action(action: str, context: str | None = None) -> tuple:
    """
    Get the key expressions and selection requirement for an action.

    Args:
        action: Action name
        context: Resolve as that context would, falling back to the action's
            built-in defaults for a config that never names it.

    Returns:
        Tuple of (key_expressions, selection_requirement)
    """
    key_bindings = config_manager.get_key_bindings()
    return key_bindings.get_keys_for_action(action, context)


def deprecated_binding_names(bindings: dict) -> list[tuple[str, str]]:
    """The ``(old_name, current_name)`` pairs a ``KEY_BINDINGS`` dict still uses.

    An old name keeps working — that is what :attr:`xefm.actions.Action.aliases`
    is for — so this is a nudge, not an error. It exists because a config is
    hand-written and long-lived: the only way its owner learns a name has been
    corrected is if XeFM says so.

    A name the config spells *both* ways is not reported: the current spelling
    already wins, and telling someone to rename what they have already renamed
    would be noise.
    """
    from xefm.actions import registry, CONTEXTS

    found: dict[str, str] = {}
    for context in CONTEXTS:
        aliases = registry.aliases_in(context)
        for name in bindings:
            if not isinstance(name, str):
                continue
            current = aliases.get(name)
            if current is not None and current not in bindings:
                found[name] = current
    return sorted(found.items())


def deprecated_names_notice(bindings: dict, limit: int = 3) -> str | None:
    """One line naming the old action names a config still uses, or ``None``.

    Deliberately one line however many there are: a config that predates several
    renames would otherwise open every session with a wall of warnings about
    bindings that all still work.
    """
    pairs = deprecated_binding_names(bindings)
    if not pairs:
        return None
    shown = ", ".join(f"'{old}' -> '{new}'" for old, new in pairs[:limit])
    more = len(pairs) - limit
    if more > 0:
        shown += f", and {more} more"
    return (f"KEY_BINDINGS uses {len(pairs)} old action name(s) — they still "
            f"work, but the current names are: {shown}. "
            f"See doc/KEY_BINDINGS_FEATURE.md for the full list.")


def printable_isearch_bindings(bindings: dict) -> list[tuple[str, str]]:
    """The ``(action, key)`` pairs where a config has bound an isearch key to a
    key that types a character.

    The search bar gives the pattern field first refusal on every printable key
    (that is what keeps ``Q``, ``?`` and SPACE typeable while ``quit``, ``help``
    and ``toggle_select_down`` own them in the file list), so such a binding can
    never fire — and the character it names would go on being typed. Reported
    once at startup rather than silently ignored, because the config is
    hand-written and this is the one mistake the isearch context invites.

    A chord holding Ctrl or Cmd is not printable and is not reported: the field
    reads those as commands, so the bar sees them.
    """
    from xefm.actions import ISEARCH, registry

    key_bindings = KeyBindings(bindings)
    found: list[tuple[str, str]] = []
    for action in registry.actions(ISEARCH):
        if not action.name.startswith(ISEARCH + "."):
            continue  # an inherited 'common' action; the bar never runs it here
        keys, _ = key_bindings.get_keys_for_action(action.name, ISEARCH)
        for expr in keys:
            identity, mods, mode = key_bindings._parse_key_expression(expr)
            if mods & {"ctrl", "cmd"}:
                continue
            if mode == "char" or identity == "space" or (
                    len(identity) == 1 and identity.isprintable()):
                found.append((action.name, expr))
    return found


def printable_isearch_notice(bindings: dict, limit: int = 3) -> str | None:
    """One line naming isearch bindings that a typed character will swallow, or
    ``None`` (see :func:`printable_isearch_bindings`)."""
    pairs = printable_isearch_bindings(bindings)
    if not pairs:
        return None
    shown = ", ".join(f"'{action}' -> '{key}'" for action, key in pairs[:limit])
    more = len(pairs) - limit
    if more > 0:
        shown += f", and {more} more"
    return (f"KEY_BINDINGS binds {len(pairs)} isearch action(s) to a key that "
            f"types a character, so they will never fire: {shown}. "
            f"Use a modified or non-printable key (Shift-DOWN, F2, Ctrl-N).")


def keys_label_for_action(action: str, fallback: str = "",
                          context: str | None = None) -> str:
    """Display string for an action's configured key(s) (so help/footers match
    the user's KEY_BINDINGS), or ``fallback`` when the action is unbound."""
    keys, _ = get_keys_for_action(action, context)
    return " / ".join(keys) if keys else fallback


def _key_char(key) -> str:
    """Normalize a key to a single-character string; accepts an ``ord()`` int."""
    return chr(key) if isinstance(key, int) else key


def _key_matches(key, keys) -> bool:
    """Case-insensitive membership test — the keymap normalizes a bare letter to
    its upper form (see ``KeyBindings`` parsing), so ``m`` and ``M`` both match a
    binding of ``M``."""
    k = _key_char(key).upper()
    return any(k == expr.upper() for expr in keys)


def is_key_bound_to(key, action: str) -> bool:
    """Whether ``key`` is one of the keys bound to ``action`` (ignoring selection
    state). ``key`` may be a character string or an ``ord()`` keycode."""
    keys, _requirement = get_keys_for_action(action)
    return _key_matches(key, keys)


def is_key_bound_to_with_selection(key, action: str, has_selection: bool) -> bool:
    """Whether ``key`` triggers ``action`` given the selection state — i.e. the
    key is bound to the action and the action's selection requirement is met
    (``required`` needs a selection, ``none`` needs none, ``any`` always)."""
    keys, requirement = get_keys_for_action(action)
    if not _key_matches(key, keys):
        return False
    if requirement == 'required':
        return has_selection
    if requirement == 'none':
        return not has_selection
    return True


def format_key_for_display(key_expr: str) -> str:
    """
    Format a key expression for display in UI.
    
    Args:
        key_expr: Key expression string
    
    Returns:
        Formatted string suitable for display
    """
    key_bindings = config_manager.get_key_bindings()
    return key_bindings.format_key_for_display(key_expr)



def get_favorite_directories():
    """Get the list of favorite directories from configuration"""
    config = get_config()
    
    favorites = []
    
    for fav in config.FAVORITE_DIRECTORIES:
        if isinstance(fav, dict) and 'name' in fav and 'path' in fav:
            try:
                # Expand user path and resolve
                path = Path(fav['path']).expanduser().resolve()
                if path.exists() and path.is_dir():
                    favorites.append({
                        'name': fav['name'],
                        'path': str(path)
                    })
                else:
                    logger.warning(f"Favorite directory does not exist: {fav['name']} -> {fav['path']}")
            except Exception as e:
                logger.warning(f"Invalid favorite directory path: {fav['name']} -> {fav['path']}: {e}")
    
    return favorites


#: Path prefixes that name a remote or virtual location (see ``xefm.path``).
#: A drive location written with one of these is listed exactly as configured:
#: probing it would mean a network round-trip on the UI thread, and the drives
#: picker exists to *offer* a connection, not to make one.
_REMOTE_SCHEMES = ('archive://', 's3://', 'ssh://', 'scp://', 'ftp://')


def _default_drive_locations():
    """The fixed drive-picker rows XeFM ships with, used when a config leaves
    ``DRIVE_LOCATIONS`` at None. Root is POSIX-only: on Windows the drive
    letters already cover it, and ``/`` there is just another name for the
    current drive."""
    locations = [{'name': 'Home', 'path': '~'}]
    if platform.system() != 'Windows':
        locations.append({'name': 'Root', 'path': '/'})
    for name in ('Documents', 'Downloads', 'Desktop'):
        locations.append({'name': name, 'path': f'~/{name}'})
    return locations


def get_drive_locations():
    """The fixed locations listed above the mounted volumes in the drives picker.

    ``DRIVE_LOCATIONS = None`` (the default) means the built-in set; a list
    replaces it wholesale, so ``[]`` leaves the picker showing only what is
    discovered — volumes, ``~/.ssh/config`` hosts, S3 buckets. A local path that
    is missing is skipped (that is how Documents / Downloads / Desktop drop out
    on a machine without them), but only an explicitly configured one is worth a
    warning: a missing default is normal, a missing hand-written entry is a typo.
    """
    config = get_config()
    configured = getattr(config, 'DRIVE_LOCATIONS', None)
    entries = _default_drive_locations() if configured is None else configured

    locations = []
    for entry in entries:
        if not (isinstance(entry, dict) and 'name' in entry and 'path' in entry):
            logger.warning(f"Invalid drive location entry: {entry!r}")
            continue
        name, raw = str(entry['name']), str(entry['path'])
        try:
            if raw.startswith(_REMOTE_SCHEMES):
                locations.append({'name': name, 'path': raw})
                continue
            path = Path(raw).expanduser()
            if path.exists() and path.is_dir():
                locations.append({'name': name, 'path': str(path)})
            elif configured is not None:
                logger.warning(f"Drive location does not exist: {name} -> {raw}")
        except Exception as e:
            logger.warning(f"Invalid drive location path: {name} -> {raw}: {e}")

    return locations


def get_programs():
    """Get the list of external programs from configuration"""
    config = get_config()
    
    programs = []
    
    for prog in config.PROGRAMS:
        if isinstance(prog, dict) and 'name' in prog and 'command' in prog:
            if isinstance(prog['command'], list) and prog['command']:
                program_entry = {
                    'name': prog['name'],
                    'command': prog['command']
                }
                
                # Add options if present
                if 'options' in prog and isinstance(prog['options'], dict):
                    program_entry['options'] = prog['options']
                else:
                    program_entry['options'] = {}
                
                programs.append(program_entry)
            else:
                logger.warning(f"Program command must be a non-empty list: {prog['name']}")
        else:
            logger.warning(f"Invalid program configuration: {prog}")
    
    return programs


def get_file_associations():
    """Get the file extension associations from configuration"""
    config = get_config()
    
    return config.FILE_ASSOCIATIONS


#: Built-in handlers selectable via the ``enter`` action -- the casual open
#: that stays inside XeFM. Unlike the external actions (``open``/``view``/
#: ``edit``), whose values are command lines, these name a handler XeFM
#: implements itself:
#:   'viewer'   -- the built-in text/markdown viewer
#:   'navigate' -- browse the file as an archive (jar, whl, ... )
BUILTIN_HANDLERS = ('viewer', 'navigate')

#: Entry keys that configure the entry itself rather than naming an action.
#: 'terminal' is obsolete -- whether to hand over the display follows from
#: the backend, not the config -- but stays reserved so a leftover key in a
#: hand-written config is inert instead of becoming a phantom action name.
_RESERVED_KEYS = ('pattern', 'terminal')


def _entry_matches(filename_lower, entry):
    """Whether one FILE_ASSOCIATIONS entry's pattern(s) match a filename.

    A malformed entry simply does not match, so a single bad entry in a user's
    config degrades that one rule rather than breaking lookup for every file.
    """
    if not isinstance(entry, dict) or 'pattern' not in entry:
        return False

    patterns = entry['pattern']
    if isinstance(patterns, str):
        patterns = [patterns]
    elif not isinstance(patterns, list):
        return False

    return any(fnmatch.fnmatch(filename_lower, str(p).lower()) for p in patterns)


def _lookup_action(filename, action):
    """Resolve one action for one file against FILE_ASSOCIATIONS.

    Entries are checked top to bottom. The first entry that both matches the
    filename *and* defines the action wins. A matching entry that does not
    mention the action falls through to later entries -- that is what lets a
    general rule supply an action a more specific rule deliberately left out.

    Args:
        filename: The filename to match (patterns are case-insensitive).
        action: Action name, e.g. 'enter', 'open', 'view', 'edit'.

    Returns:
        ``(found, value, entry)``. ``found`` is what separates "explicitly
        configured as None" from "not configured at all" -- indistinguishable
        by ``value`` alone, and they mean opposite things to a caller.
    """
    associations = get_file_associations()
    if not associations:
        return (False, None, None)

    filename_lower = filename.lower()

    for entry in associations:
        if not _entry_matches(filename_lower, entry):
            continue

        for key, value in entry.items():
            if key in _RESERVED_KEYS:
                continue
            # A key may combine actions, as in 'open|view'.
            if action in (a.strip() for a in str(key).split('|')):
                return (True, value, entry)

    return (False, None, None)


def get_program_for_file(filename, action='open'):
    """The external command configured for a file and action.

    Args:
        filename: The filename to check (e.g., 'document.pdf').
        action: The action to perform ('open', 'view', or 'edit').

    Returns:
        Command as a list, or None if no command is configured. Note that None
        is also what an explicit ``None`` in the config produces -- use
        :func:`has_explicit_association` when the difference matters.
    """
    _found, value, _entry = _lookup_action(filename, action)

    if isinstance(value, str):
        return value.split()
    if isinstance(value, list):
        return value
    return None


def has_action_for_file(filename, action='open'):
    """Whether a runnable program is configured for a file and action.

    An explicitly-``None`` association reads False here: there is no program to
    run. That is deliberately *not* the same as "unconfigured" -- see
    :func:`has_explicit_association`.
    """
    return get_program_for_file(filename, action) is not None


def has_explicit_association(filename, action='open'):
    """Whether the config mentions this action for this file *at all*.

    True even when the configured value is ``None``, which is how a user says
    "handle this with the built-in viewer rather than an external program".
    """
    found, _value, _entry = _lookup_action(filename, action)
    return found


def get_builtin_handler_for_file(filename, action='enter'):
    """The built-in handler configured for the casual (Enter) open.

    This is the inside-XeFM tier: the value names a handler XeFM implements, not
    a program to launch. Kept separate from :func:`get_program_for_file`
    because that function coerces bare strings into command lists, which would
    silently turn the handler name 'viewer' into the command ``['viewer']``.

    Returns:
        ``(configured, handler)``. ``configured`` False means no rule matched,
        so the caller should apply its own default dispatch; ``(True, None)``
        means a rule explicitly asked for nothing to happen. An unrecognised
        handler name is warned about and treated as unconfigured, so a typo
        falls back to sensible behavior instead of silently doing nothing.
    """
    found, value, _entry = _lookup_action(filename, action)
    if not found:
        return (False, None)
    if value is None:
        return (True, None)

    handler = str(value).strip().lower()
    if handler not in BUILTIN_HANDLERS:
        logger.warning(
            f"Unknown '{action}' handler {value!r} for {filename!r}; "
            f"expected one of {', '.join(BUILTIN_HANDLERS)} or None"
        )
        return (False, None)
    return (True, handler)
