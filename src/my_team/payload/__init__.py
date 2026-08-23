"""The skill payload: product data shipped inside the package, not code.

`my-team sync` installs `skills/mt-*` into a target repo's skill roots. Nothing here
is imported or executed; this module exists only so the tree has an import anchor for
`importlib.resources`. Editing a skill under `skills/` changes nothing until a sync
runs. See docs/adr/0008-the-payload-is-installed-into-the-target-repo.md.
"""
