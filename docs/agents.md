# Create playlists with an AI agent

Genplis includes a portable [Agent Skill](https://agentskills.io/) that
teaches an AI agent to inspect your library, turn playlist ideas into M3UG
filters, and validate the results. It includes offline instructions and
language, tag, and usage references matching the packaged genplis version.

The skill does not run an AI model or send your music to a service. Your
chosen agent supplies the model and tools; its own privacy and permission
settings still apply.

## Install the skill

For **Codex or OpenCode**:

```bash
genplis --install-skill
```

This installs `~/.agents/skills/genplis/SKILL.md` and its references. The
explicit `genplis --install-skill agents` form has the same effect.

For **Claude Code**:

```bash
genplis --install-skill claude
```

This installs the same skill in `~/.claude/skills/genplis/`. OpenCode also
discovers this location, so users of both Claude Code and OpenCode can use
just the Claude installation. Avoid installing both copies unnecessarily.
Discovery follows each agent's conventions and settings; other agents may
need the skill copied to their own supported location.

Installation is global for your user, not limited to a project. It needs no
collection path, does not load genplis configuration or access the tag cache,
and does not modify any agent configuration or permission settings. It cannot
be combined with collection, playlist, inspection, or configuration options.

## Ask for a playlist

Start your agent in a workspace where it can access the collection and write
filters. For example:

> Use the genplis skill. My music is in `/home/me/Music`. Create an M3UG
> playlist for about an hour of my highly rated metal, shuffled, with no
> more than three songs per artist. Check the available tags first, save
> it as `/home/me/Music/Favorite-metal.m3ug`, and validate it without
> generating a playlist yet.

The agent should discover actual tag names, values, and coverage before
choosing rules. For requests such as "relaxing music", it should ask about
appropriate metadata or explain a proposed approximation rather than invent
a mood detector.

If the skill is not available, restart the agent session. You can also
invoke it explicitly using your agent's skill selection interface, such as
`$genplis` in Codex, `@genplis` in OpenCode, or `/genplis` in Claude Code.
If the agent cannot run commands, supply the relevant output from
`genplis --tag-stats /path/to/Music` and `genplis -t genre /path/to/Music`.
It should clearly identify an unvalidated draft.

Parsing checks and traces leave playlists untouched, although inspection
and trace commands may update the tag cache. When you want the `.m3u` file,
ask the agent to generate it or run:

```bash
genplis /path/to/Music --filter /path/to/Music/Favorite-metal.m3ug
```

Normal generation replaces that filter's existing playlist by default;
other playlists are left alone with `--filter`. See [Usage](usage.md).

## Update or remove the skill

Repeating installation with identical content is a no-op. If bundled files
differ, installation stops before changing them. Back up customizations,
then explicitly replace bundled files with:

```bash
genplis --install-skill --force
# Or, for the Claude installation:
genplis --install-skill claude --force
```

Extra files you added inside the skill directory are preserved. Symbolic
links and file/directory collisions within the skill are refused, even with
`--force`. Parent skills locations may themselves be symlinked.

Package upgrades do not update installed copies automatically. Reinstall
after upgrading genplis; the skill records its source version in frontmatter.
To remove it, delete only the `genplis` skill directory you installed, after
backing up anything you want to keep. Do not remove the whole skills directory.

## Use the instructions without installing

The complete [agent instructions](agent-instructions.md) are also readable
as a normal document. Give those instructions and the linked [M3UG](m3ug.md)
and [tag references](tags.md) to an assistant that does not support skills.
For a local skill installation, everything needed for writing filters is
bundled; network access is not required to read the primary references.
