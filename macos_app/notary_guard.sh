# shellcheck shell=bash
# Sourced by build.sh and create_dmg.sh when NOTARY_PROFILE is set, before the
# long work starts. Defines notary_guard, which needs log_info / log_error.
#
# notarytool keeps a keychain profile in the data protection keychain, which
# cannot be read while the screen is locked. A locked screen makes notarytool
# report "No Keychain password item found for profile" - the profile is still
# there. A release runs long enough for the display to sleep and the screen to
# lock under it, so the notarization at the end failed and looked like a lost
# profile (doc/dev/RELEASE_SYSTEM.md, "Notarization and the screen lock").
#
# notary_guard therefore:
#   1. keeps the display awake (caffeinate -d) until the calling script exits,
#      so the screen does not lock in the middle of the build, and
#   2. reads the profile now, so a screen that is already locked - or a
#      profile that really is missing - stops the build here, not after it.

notary_guard() {
    local profile="$1"
    if command -v caffeinate >/dev/null 2>&1; then
        # -w: caffeinate exits with the script that sourced this file.
        caffeinate -d -w "$$" &
        log_info "Keeping the display awake until notarization is done (caffeinate -d)"
    fi
    local out
    if out="$(xcrun notarytool history --keychain-profile "${profile}" 2>&1)"; then
        log_info "Notary profile ${profile}: readable"
        return 0
    fi
    if printf '%s' "${out}" | grep -q "No Keychain password item found"; then
        log_error "Cannot read the notary profile ${profile} from the keychain."
        log_error "Most often the screen is locked: notarytool cannot read its"
        log_error "profile while it is. Unlock the Mac and run this again. The"
        log_error "profile is not lost - do not store it again for this."
        log_error "(Run from a sandboxed shell, the keychain is out of reach too.)"
        log_error "If it persists with the screen unlocked, check it with:"
        log_error "  xcrun notarytool history --keychain-profile \"${profile}\""
    else
        log_error "notarytool cannot use the profile ${profile}:"
        printf '%s\n' "${out}" | sed 's/^/[ERROR]   /' >&2
    fi
    exit 1
}
