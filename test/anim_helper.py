"""Playing a Panel's transitions to their end in a test.

A viewer now closes by fading out and removes its layer when that ends
(dialog_geometry.close_viewer), so a test that closes one and checks what is
left settles the transitions first."""


def settle(panel, rounds: int = 8) -> None:
    """Run the memory backend's animation ticks until no transition is left:
    the stepped (TUI) path's frames, and the completion hooks of composited
    (GUI) ones, which the memory backend fires on its next tick."""
    backend = panel.backend
    for _ in range(rounds):
        if not (panel._size_anims or panel._color_anims or panel._effect_anims
                or backend._pending_completes):
            return
        backend.run_animation_ticks()
