"""The pure core: plain data and the functions over it, and no I/O anywhere.

Nothing in this package opens a file, spawns a process or speaks to GitHub. That is
enforced by signature — `derive(observation, now, work_started_at)` takes no client —
and by this package carrying its own 100% coverage floor, which only holds while the
code here stays pure functions over plain data.
"""
