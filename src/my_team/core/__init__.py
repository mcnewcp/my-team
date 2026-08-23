"""The pure core: plain data and the functions over it, and no I/O anywhere.

Nothing in this package opens a file, spawns a process or speaks to GitHub — and today
that is a convention, held by review and by nothing else. Neither strict typing nor the
100% coverage floor this package carries can see an `import subprocess`, so a module in
here that started doing I/O would pass every gate.

#55 is where the boundary gets teeth. The ladder it lands takes its clock as a
parameter and no client at all, so it cannot do I/O even by accident, and the same
ticket adds the contract CI can check: the ladder module may not import `subprocess`,
an HTTP client, or the GitHub and harness modules.
"""
