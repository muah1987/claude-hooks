# Review Report — "Token-Efficient Hook Automation System" Specification v14

**Reviewed:** `Improved Hooks v14.md`, in the context of every prior version in this folder (base, v2–v7, v9, v10, V11, V12, v13) and the July 14 review of base/v10–v12.
**Date:** 17 July 2026
**Method:** Full read of v14; skim of all prior versions for the evolution record; cross-check against the official hooks reference (code.claude.com/docs/en/hooks) fetched twice during the v13→v14 cycle; and — unique to this review — validation against a **completed reference implementation** of the spec (`~/.claude/hooks/`, 65-assertion fixture suite, live headless-session verification, and three captured real payloads on Claude Code 2.1.208).

---

## 1. Context: what v14 is

v14 is the first version of this specification produced *after* an implementation existed. v13 was a documentation-verification pass over v12 (executing the July 14 review's fix list); v14 folds back the two defects that only became visible when v13 was actually built, tested, and run against live sessions:

1. **Guard spawn-filter coverage** — v13 §3.3 wired the Bash guard behind only `Bash(rm *)` and `Bash(git push *)` while its own config carried deny patterns for `sudo`/`dd`/`mkfs`/`chmod`/device-writes. Those families could never spawn the guard: the "optimization" was a silent bypass. v14 wires seven filters, adds a co-maintenance requirement to rule 8 (config deny families and `if` filters change together, or the guard runs unfiltered), and adds acceptance criteria in §10.A and §10.E.
2. **Statusline performance target** — v13's flat "<100 ms" is unachievable on a cold BusyBox/musl start (~195 ms measured, fork/exec-bound). v14 splits the target: <100 ms warm (mandatory ≥5 s cache), ≤250 ms cold tolerated, with "compile it" as the documented escape hatch rather than shell golf.

v14 also upgrades three claims from "documented" to "empirically confirmed": `stop_hook_active` and `last_assistant_message` on real Stop stdin (the rendered docs truncate before that section — a captured payload settled it), the statusline `rate_limits`/`context_window` shape, and the input-tokens-only basis of `used_percentage` (116,901 input / 1 M window → 12 % with output tokens excluded, matching §1.2 exactly).

**Verdict up front:** v14 is coherent, implementable, and — uniquely in this series — *proven* implementable, because the reference implementation passed all of its acceptance-testable criteria. The remaining findings below are real but none is architecture-breaking. The most instructive content of this review is in §5: what thirteen revisions of this document teach about how spec regressions happen.

---

## 2. High findings (should be addressed in v15, none blocks implementation)

### 2.1 The seventh filter's matching semantics are asserted, not verified

The redirect-to-device deny family (`> /dev/sd…`) has no command name to filter on, so v14 covers it with `"if": "Bash(*/dev/*)"`. That is a reasonable reading of permission-rule glob syntax, but unlike every other schema claim in v14 it has **no evidence behind it** — neither the docs excerpt nor a live test confirms that a `Bash(...)` rule glob matches mid-string against the full subcommand text rather than anchoring at the command name. And this failure mode is the *bad* direction: an `if` filter that never matches doesn't fail open, it fails **silent** — the guard simply never spawns for a bare `cat img > /dev/sda`, and the pattern is only checked when some other family's filter happens to spawn the guard.

The spec should either (a) mark this filter "verify with `claude --debug` at implementation time" the way rule 2 demands for schemas, or (b) prescribe the robust fallback outright: when any deny family cannot be expressed as a command-name filter, run the guard unfiltered on the Bash matcher and accept the ~30 ms spawn per command. The current text presents the glob as settled fact. This is precisely the pattern (confident assertion, no provenance) that §5 shows to be the series' recurring failure mode — it should not survive into v15 unlabeled.

### 2.2 The §10.E coverage criterion is prose; it should be executable

The new criterion — "every pattern family in `config.json → guards.*` has a covering `if` filter, verified by cross-referencing the two files" — was violated *within minutes of being written*: the first manual cross-check exposed the uncovered `>`-device family that v14's own §3.3 draft had missed. That is strong evidence the check works and equally strong evidence it must not be manual. v15 should specify a test that derives the command-name families from the config patterns mechanically and asserts filter coverage in `test/run.sh`, so the check runs on every suite execution instead of relying on a diligent reviewer. (A rule that its own author breaks on first contact is a rule that needs automation, not more emphasis.)

### 2.3 Two spec surfaces now exist; drift is a matter of time

The canonical spec now lives both at `~/.claude/hooks/SPEC.md` (with the implementation) and in this folder as `Improved Hooks v14.md`. Today they are byte-identical; nothing keeps them so. v15 should declare one location canonical and the other a copy (a one-line provenance header in each is enough), or the two will diverge the way §5.2's manifest path once did *within a single document*.

---

## 3. Medium findings

**Unverifiable acceptance criteria remain.** §10.B's "compaction completes successfully at the 85 % threshold" and the `PermissionRequest`-does-not-fire-headless caveat (§4.2) are both untestable offline — the docs are silent on the headless claim (checked explicitly during this cycle), and compaction headroom can only be proven in a long live session. Neither is wrong; both should be tagged "live-session criterion, not suite-testable" so an implementer doesn't burn time trying to fixture them.

**§5.4 validator scope still overpromises relative to any realistic v1 implementation.** Email SPF/DKIM/DMARC verification, web console/network-request assertions with screenshots, VPS artifact-checksum comparison — the reference implementation ships honest but much thinner probes (SMTP banner + MX; curl fallback when Playwright is absent; uptime/service/port/disk). The spec's own missing-tool rule (warn + `skipped`, never break) papers over the gap gracefully, but §5.4 reads as a requirement while functioning as an aspiration. v15 should split it into "minimum probe set" (what §10 actually tests) and "full probe set" (roadmap).

**The cold-start number is a single-machine measurement wearing a normative costume.** "≤250 ms tolerated" generalizes one Alpine/BusyBox data point. Fine as a budget; v15 should phrase it as one ("cold-start budget: 2.5× the warm target") rather than as a portable measurement, or the first person to run this on a slower ARM SBC will file a spec bug.

**Version history still says "see previous records" for v1–v9.** Those records now sit in the same folder as the spec. The history table should cite them by filename — the oscillation evidence in §5 below is only recoverable because these files happen to survive; the spec should not depend on that luck.

---

## 4. What v14 gets right (verified against docs, payloads, and a running system)

Everything the July 14 review flagged as critical stays fixed, and now with implementation evidence rather than doc-reading alone: the statusline-bridge limit architecture works end-to-end (a real captured payload feeds `limits.json`; the bridge injected a real wind-down directive at a real 96 % weekly reading, deduped on the next prompt, and went silent on stale data); `format.sh` on PostToolUse; `limit-bridge.sh` actually wired and firing on UserPromptSubmit; the single block/skip rule enforced in both directions (declared project blocked on missing/malformed context, undeclared project sailed through with a malformed file present); "JSON only on exit 0" honored (the guard's exit-2 path emits stderr only — asserted by the suite); the PermissionDenied `hookSpecificOutput.retry` shape; `used_percentage` in `limits.json`; one canonical manifest path used identically by three consumers; the safe `.env` parser rejecting `$( )`, backticks, and `;` payloads (hostile fixture exports nothing, executes nothing); detached async validators with the weakened-guarantee caveat stated honestly. The seven-filter guard set now blocks a dd-to-device and a redirect-to-device fixture in the suite, and blocked a live `.env` write in a real headless session with the ⛔ reason surfaced to the model. The loop-guard field the docs truncate away is confirmed on the wire. 65/65 assertions pass; the live-session lifecycle (SessionStart injection → manifest → Stop allow → SessionEnd quarantine → restore) was observed, not inferred.

---

## 5. The evolution record: how this spec kept regressing, and what finally stopped it

Reading all thirteen prior documents in sequence reveals a pattern no single-version review could see:

| Fact | base | v5 | v6 | v7 | v10 | v11 | v12 | v13/v14 |
|---|---|---|---|---|---|---|---|---|
| Statusline output stream | stdout ✓ | stdout ✓ | **stderr ✗** | stdout ✓ | stdout ✓ | stdout ✓ | stdout ✓ | stdout ✓ |
| Limit metrics location | statusline ✓ | statusline ✓ | — | — | **hook stdin ✗** | ✗ | ✗ | statusline ✓ |
| `if` syntax | — | — | — | permission-rule ✓ | permission-rule ✓ | **regex ✗** | regex ✗ | permission-rule ✓ |

Three independent facts each flipped from correct to wrong *during a revision that claimed to be a correctness pass* ("Based on official Claude Code hooks documentation…", says v6, while breaking the output stream v5 had right; v10's "Revised Architecture" inverted the limit flow the base file had right; v11's change table presents the regex regression as a clarification). The v9 file's `[cite: 7]` artifacts suggest at least one revision was machine-generated from a summary rather than from the prior document — which is exactly how a correct claim with no attached evidence gets "corrected" into a wrong one by a confident reviser.

What stopped the cycle was not more careful prose. It was **provenance and execution**: v13 attached every schema claim to a live-docs check ("do not rely on this document's schema excerpts either"); v14 attached the remaining claims to captured payloads and a test suite, and its two fixes came *from* building the thing. The general lesson this series teaches: a specification claim without recorded evidence has a half-life of about two revisions, and the only durable fix is to make the claim either executable (a test) or cited (a capture, a doc quote with date). v15 should adopt that as a ground rule — every schema assertion carries an evidence tag: `[docs YYYY-MM-DD]`, `[captured <fixture>]`, or `[UNVERIFIED]` — so the next reviser can distinguish load-bearing fact from confident memory at a glance. Notably, 2.1 above exists because v14 itself already contains one untagged `[UNVERIFIED]` claim; the convention would have caught it at writing time.

---

## 6. Recommended fix list for a v15

Label the `Bash(*/dev/*)` filter as unverified and specify the unfiltered-guard fallback for families with no command name (2.1). Make the §10.E family-coverage cross-check an executable test in `test/run.sh` (2.2). Declare one canonical spec location with a provenance header in the copy (2.3). Tag §10 criteria that are live-session-only. Split §5.4 into minimum and full probe sets. Rephrase the cold-start number as a budget relative to the warm target. Cite the v1–v13 files by name in the version history. Adopt the evidence-tag convention from §5 as a ground rule. None of these changes the architecture — v14's architecture is done; v15's job is making the document as self-verifying as the system it specifies.
