# Contracts are append-only, digest-bound issue comments

Before implementation, the Contractor posts a human-readable Contract candidate generated from
a closed machine-readable JSON object in the same issue comment. A lowercase SHA-256 digest over
the object's UTF-8 RFC 8785 representation identifies the exact payload; with the default-on
approval boundary, the Product Owner selects it by adding a thumbs-up reaction to that comment;
the first attributable application of `my-team:implementing` then freezes it. A thumbs-down
reaction on the current candidate explicitly requests rework and returns the pipeline to
`contracting`; explanatory comments are prompt input rather than machine state. Both reactions
present together are conflicting current evidence and escalate.

GitHub cannot make comments immutable, so immutability is a protocol invariant rather than a
platform guarantee. An edit invalidates the candidate, corrections are new contiguous revisions
that bind the prior comment permalink and digest. The first attributable application of
`my-team:implementing` closes the revision chain and freezes the immediately preceding canonical
candidate; later returns to `implementing` retain that reference rather than freezing again. The
pull request carries both a visible link and a machine-readable reference to the frozen comment
and digest.

Contractor clarification uses no second document schema. Within a `contracting` State occurrence,
the first unedited Contractor-authored issue comment that is not a Contract Candidate is the
clarification request; the API act and ordering declare its purpose, while its prose is prompt
input and is never interpreted by the State machine. Byte-identical reposts alias the earliest
comment. A divergent second request, a request alongside a current candidate, or an edit to the
request is conflicting evidence and escalates.

## Considered options

**Edit one canonical comment.** This keeps the conversation short but lets a correction rewrite
what the Product Owner approved and destroys the evidence needed for recovery. Append-only
revisions retain that evidence and make ambiguous duplicate posts reconcilable by payload digest.

**Approve with a label or a new comment.** A label is attached to the issue rather than a specific
candidate. A separate approval comment must duplicate and parse a reference and is itself
editable. A reaction is native, attributable and attached to the exact candidate it approves.

**Make either Markdown or JSON authoritative.** Hand-authored copies can disagree. JSON alone is
hostile to the Product Owner, while Markdown alone is brittle to parse. The Contractor therefore
produces one JSON authority, mechanically validates it, renders the Markdown from it and reparses
the embedded object before posting.

## Consequences

Acceptance-criterion identifiers are issue-local and never reused. An unchanged criterion object
may retain its identifier across a revision; changed meaning retires the old identifier and takes
the next unused one. Every active criterion has deterministic Test Plan coverage, the Test Budget
is a hard cap on new leaf cases, and Scope Paths are an operation-aware allowlist over the diff.

Mechanical validation establishes schema closure, referential integrity, canonical digest,
revision continuity, source-issue identity, author and approval attribution, and the exact pull
request reference. It cannot establish that an oracle truly proves a user-visible outcome; that
semantic judgment belongs to the Contractor and, while approval is enabled, the Product Owner.

An exact retry aliases the earliest matching comment. A different payload at the same revision,
an edited candidate, a withdrawn approval after implementation starts, an issue-body change, or
a proposed successor after implementation starts escalates instead of silently changing the
definition of done.
