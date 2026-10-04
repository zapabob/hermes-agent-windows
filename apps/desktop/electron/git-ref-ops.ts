// Git reference CRUD for the desktop SCM rail: branches, tags, stashes, and
// fetch/pull. Built on the system git binary via execFile, matching the other
// git ops modules. Reads degrade to empty on a non-repo / remote backend;
// mutations reject so the renderer can toast. Names are validated with git's
// own `check-ref-format` at the boundary — never sanitized-and-fixed, because
// a rewritten name would hide a typo the user should see.


import { resolveRequestedPathForIpc } from './hardening'
import { executeGitChecked, rethrowGitPolicyError } from './git-execution-policy'

// Unit separator between format fields. Git's pretty-format parser only honors
// `%xNN` escapes (and for-each-ref honors neither `%xNN` nor `%NN`), so the
// separator is passed as a literal control byte in the format string — same
// assumption parseHistory makes for its record/field separators.
const SEP = String.fromCharCode(31)

async function runGit(gitBin: string, args: string[], cwd: string): Promise<string> {
  return executeGitChecked(cwd, gitBin, args)
}

// Validate a branch name with git's own ref-name grammar. Throws on anything
// git would refuse, so no invalid name ever reaches a mutation.
async function assertBranchName(gitBin, cwd, name) {
  const label = String(name || '').trim()

  if (!label) {
    throw new Error('Branch name is required.')
  }

  try {
    await runGit(gitBin, ['check-ref-format', '--branch', label], cwd)
  } catch (error) {
    rethrowGitPolicyError(error)
    throw new Error('Invalid branch name.')
  }
}

async function assertTagName(gitBin, cwd, name) {
  const label = String(name || '').trim()

  if (!label) {
    throw new Error('Tag name is required.')
  }

  try {
    await runGit(gitBin, ['check-ref-format', `refs/tags/${label}`], cwd)
  } catch (error) {
    rethrowGitPolicyError(error)
    throw new Error('Invalid tag name.')
  }
}

// A ref the renderer picked from a listing (listBranches / history / remotes).
// Option-like or whitespace-bearing values can't come from those lists, so
// reject them outright; git validates the rest of the name.
function assertRefArg(value, label) {
  const clean = String(value || '').trim()

  if (!clean || /\s/.test(clean) || clean.startsWith('-')) {
    throw new Error(`Invalid ${label}.`)
  }

  return clean
}

// Remote names follow a tighter grammar than refs: no slash, must not start
// with a dash.
function assertRemoteName(value) {
  const clean = String(value || '').trim()

  if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(clean)) {
    throw new Error('Invalid remote name.')
  }

  return clean
}

function assertStashIndex(index) {
  const n = Number(index)

  if (!Number.isInteger(n) || n < 0 || n > 100_000) {
    throw new Error('Invalid stash index.')
  }

  return n
}

// Tag rows: name, peeled commit sha ('' for a lightweight tag), tag-object
// sha, author date, subject. For a lightweight tag the commit sha is used.
function parseTags(out) {
  return String(out || '')
    .split('\n')
    .filter(Boolean)
    .map(line => {
      const [name, peeled, object, date, ...rest] = line.split(SEP)
      const sha = peeled || object

      return {
        name: name || '',
        sha: sha || '',
        shortSha: sha ? sha.slice(0, 7) : '',
        date: date || '',
        subject: rest.join(SEP) || ''
      }
    })
}

// Stash rows from the stash reflog: `stash@{N}`, commit sha, author date,
// subject (git prefixes the default "On <branch>: " unless a message was set).
function parseStashes(out) {
  return String(out || '')
    .split('\n')
    .filter(Boolean)
    .map(line => {
      const [id, sha, date, ...rest] = line.split(SEP)
      const match = /^stash@\{(\d+)\}$/.exec(id || '')

      return {
        index: match ? Number(match[1]) : -1,
        id: id || '',
        sha: sha || '',
        shortSha: (sha || '').slice(0, 7),
        date: date || '',
        message: rest.join(SEP) || ''
      }
    })
}

async function listTags(repoPath, gitBin) {
  let cwd

  try {
    cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Tag list' })
  } catch (error) {
    rethrowGitPolicyError(error)
    return []
  }

  try {
    const out = await runGit(
      gitBin,
      [
        'for-each-ref',
        '--sort=-creatordate',
        `--format=%(refname:short)${SEP}%(*objectname)${SEP}%(objectname)${SEP}%(creatordate:iso-strict)${SEP}%(subject)`,
        'refs/tags'
      ],
      cwd
    )

    return parseTags(out)
  } catch (error) {
    rethrowGitPolicyError(error)
    return []
  }
}

async function listStashes(repoPath, gitBin) {
  let cwd

  try {
    cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Stash list' })
  } catch (error) {
    rethrowGitPolicyError(error)
    return []
  }

  try {
    // `git stash list` is a reflog walk of refs/stash. Ask git log directly so
    // the format string isn't rewritten by the stash wrapper.
    const out = await runGit(gitBin, ['log', '-g', `--format=%gd${SEP}%H${SEP}%aI${SEP}%s`, 'refs/stash'], cwd)

    return parseStashes(out)
  } catch (error) {
    rethrowGitPolicyError(error)
    return []
  }
}

async function branchCreate(repoPath, name, base, gitBin) {
  const cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Branch create' })

  await assertBranchName(gitBin, cwd, name)

  const args = ['branch', name]

  if (base) {
    args.push(assertRefArg(base, 'branch base'))
  }

  await runGit(gitBin, args, cwd)

  return { ok: true }
}

async function branchRename(repoPath, name, newName, gitBin) {
  const cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Branch rename' })

  await assertBranchName(gitBin, cwd, newName)
  await runGit(gitBin, ['branch', '-m', assertRefArg(name, 'branch'), newName], cwd)

  return { ok: true }
}

// `-d` refuses an unmerged branch and the currently checked-out branch; git's
// own guards do that work. `force` opts into `-D`.
async function branchDelete(repoPath, name, force, gitBin) {
  const cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Branch delete' })

  await runGit(gitBin, ['branch', force ? '-D' : '-d', assertRefArg(name, 'branch')], cwd)

  return { ok: true }
}

async function tagCreate(repoPath, name, target, gitBin) {
  const cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Tag create' })

  await assertTagName(gitBin, cwd, name)

  const args = ['tag', name]

  if (target) {
    args.push(assertRefArg(target, 'tag target'))
  }

  await runGit(gitBin, args, cwd)

  return { ok: true }
}

async function tagDelete(repoPath, name, gitBin) {
  const cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Tag delete' })

  await runGit(gitBin, ['tag', '-d', assertRefArg(name, 'tag')], cwd)

  return { ok: true }
}

// `git stash push` with no changes exits 0 ("No local changes to save"), so
// creating an empty stash is not an error — the renderer decides whether to
// disable the button from the status it already has.
async function stashCreate(repoPath, message, includeUntracked, gitBin) {
  const cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Stash create' })
  const args = ['stash', 'push']

  if (includeUntracked) {
    args.push('-u')
  }

  const note = String(message || '')
    .trim()
    .slice(0, 1000)

  if (note) {
    args.push('-m', note)
  }

  await runGit(gitBin, args, cwd)

  return { ok: true }
}

// Conflicts reject so the renderer can offer the user a path forward instead
// of pretending the apply landed.
async function stashApply(repoPath, index, gitBin) {
  const cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Stash apply' })

  await runGit(gitBin, ['stash', 'apply', `stash@{${assertStashIndex(index)}}`], cwd)

  return { ok: true }
}

async function stashDrop(repoPath, index, gitBin) {
  const cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Stash drop' })

  await runGit(gitBin, ['stash', 'drop', `stash@{${assertStashIndex(index)}}`], cwd)

  return { ok: true }
}

// Prune stale remote-tracking refs by default — matches VS Code's fetch and
// keeps the branch list honest after a teammate deletes a branch.
async function gitFetch(repoPath, remote, gitBin) {
  const cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Git fetch' })
  const args = ['fetch', '--prune']

  if (remote) {
    args.push(assertRemoteName(remote))
  }

  await runGit(gitBin, args, cwd)

  return { ok: true }
}

async function gitPull(repoPath, rebase, gitBin) {
  const cwd = resolveRequestedPathForIpc(repoPath, { purpose: 'Git pull' })
  const args = ['pull']

  if (rebase) {
    args.push('--rebase')
  }

  await runGit(gitBin, args, cwd)

  return { ok: true }
}

export {
  branchCreate,
  branchDelete,
  branchRename,
  gitFetch,
  gitPull,
  listStashes,
  listTags,
  parseStashes,
  parseTags,
  stashApply,
  stashCreate,
  stashDrop,
  tagCreate,
  tagDelete
}
