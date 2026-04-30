# shellcheck shell=bash
#
# Shared bash helpers for the devenv-aware tooling.  Each function
# is a no-op when the local `devenv` branch doesn't exist, so the
# scripts stay safe to run on a vanilla checkout that never set
# devenv up.
#
# Usage contract:
#
#   * `devenv_rebase_off` echoes the upstream branch name on stdout
#     iff a rebase happened (i.e. devenv was an ancestor of HEAD and
#     was just dropped).  Stdout is empty otherwise.  Callers decide
#     whether the rebase happened by checking that stdout is non-
#     empty -- not by checking the return code, which is reserved
#     for actual errors.
#
#   * `devenv_set_as_base` puts devenv at the base of the current
#     branch (i.e. ensures devenv is an ancestor of HEAD).  Idempotent:
#     no-op when devenv is already an ancestor.  Note this APPLIES
#     devenv as a base; it doesn't merely "restore" a previously-
#     present base.  Used by both:
#       - the publisher scripts (where devenv was just dropped and is
#         being put back so the worktree stays usable), and
#       - the fetch-rebase-pull-request flow (where devenv was never
#         present on the freshly-checked-out PR review branch but the
#         maintainer wants the devenv toolchain available locally).

# If devenv is in HEAD's ancestry, rebase HEAD onto upstream's default
# branch, dropping the devenv commits from history.
#
# Exits non-zero only on real errors (upstream/HEAD unset, rebase
# conflict, repo damaged).  No-op (returns 0, prints nothing) when
# devenv doesn't exist locally or HEAD is already off devenv.
#
# Stdout: upstream branch name (e.g. "upstream/main") iff a rebase
# was performed; empty otherwise.
devenv_rebase_off() {
    git rev-parse --verify --quiet refs/heads/devenv >/dev/null || return 0

    # `merge-base --is-ancestor` returns 0 (yes), 1 (no), or 128 (error
    # such as missing object / corrupt ref).  We must distinguish: a
    # 128 means we should fail loudly, not silently no-op.
    local rc=0
    git merge-base --is-ancestor devenv HEAD || rc=$?
    case $rc in
        0) ;;          # devenv is an ancestor; continue to rebase below.
        1) return 0 ;; # devenv is not an ancestor; nothing to drop.
        *)
            echo "Error: 'git merge-base --is-ancestor devenv HEAD' failed" >&2
            echo "       (exit $rc); aborting before any rewriting." >&2
            return $rc
            ;;
    esac

    local upstream_head upstream_branch
    if ! upstream_head=$(git symbolic-ref --quiet refs/remotes/upstream/HEAD); then
        echo "Error: upstream/HEAD is not set." >&2
        echo "       Run: git remote set-head upstream --auto" >&2
        return 1
    fi
    upstream_branch=${upstream_head#refs/remotes/}

    # `--rebase-merges` keeps merge commits that the user intentionally
    # made on the feature branch (e.g. merging in upstream/main mid-
    # flight); without it those merges would be silently flattened by
    # the default cherry-pick rebase strategy and the pushed branch
    # wouldn't match the local history.
    git rebase --rebase-merges --onto "$upstream_branch" devenv >&2
    echo "$upstream_branch"
}

# Apply devenv as the base of the current branch.  No-op when devenv
# is already in HEAD's ancestry, or when devenv doesn't exist locally.
#
# Returns non-zero (and leaves the user mid-rebase) only when the
# rebase itself conflicts; in that case the user resolves and runs
# `git rebase --continue`.
devenv_set_as_base() {
    git rev-parse --verify --quiet refs/heads/devenv >/dev/null || return 0

    local rc=0
    git merge-base --is-ancestor devenv HEAD || rc=$?
    case $rc in
        0) return 0 ;; # already there; nothing to do.
        1) ;;          # not an ancestor; rebase below.
        *)
            echo "Error: 'git merge-base --is-ancestor devenv HEAD' failed" >&2
            echo "       (exit $rc); cannot apply devenv base." >&2
            return $rc
            ;;
    esac

    if ! git rebase --rebase-merges devenv >&2; then
        echo "Error: failed to apply devenv as the local base." >&2
        echo "       Resolve conflicts and run: git rebase --continue" >&2
        return 1
    fi
}

# Returns 0 if a rebase / merge / cherry-pick / revert is mid-flight,
# 1 otherwise.  Backs both the "refuse to start" precondition and
# the "don't pile on" trap-time recovery path.
_devenv_op_in_progress() {
    local git_dir marker
    git_dir=$(git rev-parse --git-dir)
    for marker in rebase-merge rebase-apply MERGE_HEAD CHERRY_PICK_HEAD REVERT_HEAD; do
        [[ -e $git_dir/$marker ]] && return 0
    done
    return 1
}

# Abort if a rebase / merge / cherry-pick / revert is mid-flight, so
# that destructive helpers don't pile a new rebase on top of an
# in-progress one.  Call this BEFORE any rewriting helper.
devenv_assert_no_in_progress_op() {
    if _devenv_op_in_progress; then
        local git_dir
        git_dir=$(git rev-parse --git-dir)
        echo "Error: a rebase/merge/cherry-pick/revert is in progress" >&2
        echo "       (under $git_dir).  Resolve it first." >&2
        return 1
    fi
}

# Trap-time variant of devenv_set_as_base.  When an EXIT/INT/TERM/HUP
# trap fires mid-rebase (e.g. user Ctrl-C'd while devenv_rebase_off
# was still rewriting history), starting a fresh rebase on top would
# fail and leave the user stranded in an even more confusing state.
# Instead, detect the in-progress op and print a recovery hint while
# preserving the original exit code so callers' final status is
# unchanged.  Safe in normal exit paths too: devenv_set_as_base is
# idempotent when devenv is already an ancestor.
devenv_restore_or_hint() {
    local rc=$?
    if _devenv_op_in_progress; then
        echo >&2
        echo "Note: a rebase/merge is in progress; not auto-restoring devenv." >&2
        echo "      Resolve it (git rebase --continue / --abort), then run:" >&2
        echo "        git rebase --rebase-merges devenv" >&2
        return "$rc"
    fi
    devenv_set_as_base
    return "$rc"
}
