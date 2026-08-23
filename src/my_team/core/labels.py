"""The two labels that carry the loop's own vocabulary.

They are here because they are the only two facts about an issue that are **not
derivable** from anything else GitHub reports: an issue is admitted to the loop
because a trusted human applied one, and it leaves the loop because the orchestrator
swapped it for the other. Everything else the ladder reads is a consequence of some
act GitHub already records.

`init` creates them, `doctor` checks they exist, and the escalation ritual swaps one
for the other — which is why they are a shared constant rather than a string spelled
out at each of those three sites.
"""

from __future__ import annotations

from typing import Final

AUTHORIZATION_LABEL: Final = "ready-for-agent"
"""Applied by a trusted human, and the act that authorizes an issue for the loop."""

ESCALATION_LABEL: Final = "ready-for-human"
"""What escalation swaps it for, which is also what un-authorizes the issue."""
