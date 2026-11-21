# Project lane · every piece of work has a home on the person's computer

One folder per project in the local workspace, always the same five folders, and every result filed into the
right one as it is produced. Nothing a person needs should exist only in a conversation or a cloud session.

```
<workspace>/                     D:\New_Projects on the person's laptop unless they set another
  index.html                     every project and what it holds
  _studio/house-style.md         how this person wants new projects set up
  <Project_Name>/
    code/                        the repository: open this folder to work
    docs/                        requirements, statements of work, reviews, test evidence, report cards
    ppts/                        decks, their speaker notes and their reviews
    guides/                      set-up guides, runbooks, presenter paths
    architecture/                decisions, diagrams, architecture records
    index.html                   what is in each folder, with links
```

1. **Find or create the project** (`stage brief`). `project_status` lists the projects and says where the workspace
   is. If the work belongs to one of them, use it. Otherwise `project_new` with a name in the person's own style
   (their existing folders are the guide: words joined with underscores, client first, for example
   `Northwind_Refunds`), plus `client`, `jira` (story or project key) and `github` (owner/repo) when known. In a
   cloud session pass `code_dir` with the repository's folder so the two are linked.
2. **Read the house style before creating anything new.** `house_style` returns the person's own rules and what
   their existing repositories show. Follow the rules. Treat the counts as defaults to offer, not as orders. If a
   rule and the current request disagree, the request wins and you say so in one line.
3. **Work in `code/`.** An existing repository is cloned there; a new one is created there (the Build lane's
   scaffolds, or by hand following the house style). Deliverables do not go in the repository unless the
   repository's own conventions say so.
4. **Results file themselves.** Every lane tool files what it produces: decks to `ppts`, reviews, test evidence
   and report cards to `docs`, decisions and diagrams to `architecture`. When the run has a story key, they go
   under a folder named for it (`docs/NW-142/…`). For anything you write yourself (a story snapshot, the pull
   request text, a guide, meeting notes) call `project_file`; pass `to` when the folder is not obvious.
5. **In a cloud session, copy to the laptop at the end of every stage.** `project_sync` with action `list`
   returns pairs of `stagedPath` and `devicePath`. Pass them, 50 at a time, to the device file-commit tool, then
   `project_sync` with action `done`. Add `code: true` after commits so the changed code files are copied too. If
   the laptop cannot be reached, say so plainly, keep going, and leave the list pending: never report work as
   saved locally when it is not.
6. **Close** with `project_status` for the project: one line per folder, and the path of its `index.html`.
7. **To put the work on GitHub** (a new, existing or team repository), follow the publish lane: the local copy
   comes first, and every push and pull request waits for the person's yes.

Never file internal pricing, credentials or key files into a project folder: the tool refuses them, and so do you.
To learn the house style from more repositories: `house_style` with action `learn` and the folders that hold them.
