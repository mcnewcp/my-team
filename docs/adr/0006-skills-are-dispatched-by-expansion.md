# Skills are dispatched by expansion, not by model choice

The orchestrator dispatches a payload skill by handing the harness the skill's own
invocation form as the prompt — `/implement 17` on Claude Code, `$implement 17` on Codex —
so the harness expands the skill into context before the model acts. The harness seam gains
a tenth parameter, `skill: str`, and each adapter renders it natively; the prompt assembler
never emits harness syntax.

The alternative that looks equivalent is instructing the model in prose: *"use the implement
skill"*, which routes through the harness's skill-invocation tool. It is not equivalent,
because it makes loading the skill a decision the model takes rather than a step that
happens. The prototype run had already paid for that distinction once — both implementer
dispatches were refused the skill and improvised the work instead, which voided the
by-hand-identical promise the payload exists to keep.

## Considered options

**Prose instruction through the skill-invocation tool.** Six dispatches against a throwaway
repo on Claude Code 2.1.237 settled it:

| dispatch shape | `disable-model-invocation: true` | `false` |
| --- | --- | --- |
| the slash command as the prompt | loads | loads |
| `"Use the mt-probe skill."` | **not listed to the model at all** | loads |

With the flag on the skill is *invisible* rather than refused — nothing in the transcript
says a skill was skipped. With the flag off it loads, but the model is still choosing. The
expansion path is immune to the flag in both directions, and arguments survive it intact:
`/mt-probe 17` yields the argument, a bare `/mt-probe` yields none.

**Prepending the invocation form above the seam**, leaving the seam's parameter list at
nine. Rejected because the prompt assembler would then be emitting Claude Code syntax — the
precise leak the seam exists to prevent, and the same argument that made
`--setting-sources project` an adapter constant rather than a seam parameter. A "skill" is
harness-neutral: `.agents/skills` is literally Codex's own repo skill root, and both
harnesses have a first-class invocation form for one.

**Inlining the skill body into the prompt**, which the prototype floated as a fallback. It
works for prose-only skills and fails the moment a skill has bundled assets or invokes
another skill by name, which `/implement` now does. It also makes shipping skills into the
target repo pointless, since the human path and the agent path would no longer read the
same text.

## Consequences

**The invocation-policy flags stop being load-bearing for dispatch, and still get flipped.**
`disable-model-invocation: false` and `allow_implicit_invocation: true` go on all five
payload skills. Expansion does not consult them, but `/implement` invokes `/create-pr` **by
name**, and that composition *is* the skill-invocation tool — a flag there fails silently,
in the invisible mode measured above. Flipping all five costs nothing and removes the trap
for whichever skill composes next.

**This is CLI behaviour measured, not a documented contract.** A version bump could move it.
The mitigation is that the fallback is known and cheap — prose instruction with the flags
already flipped is the same dispatch minus the guarantee — so a regression degrades rather
than blocks.

**The seam's parameter list grows for a reason that generalises.** `skill` is the second
harness-specific rendering the seam hides, after the stop signal. It is what keeps the
prompt assembler harness-blind while the payload stays one tree serving both harnesses.
