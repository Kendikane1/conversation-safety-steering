# Study coverage and limits

Each row is a separate study or development stage. Counts are not pooled across reused families, policies, writer histories or CPU/L4 backends. Case-level exports use stable study/slot/family IDs; null means unavailable, not safe. All behavioral judgments are assistant-only.

| Study | Purpose and evidence | Result or disposition | Interpretation limit |
|---|---|---|---|
| W01S | Steering-strength development | Historical strength-selection evidence and source retained in expanded export | Development, not a held-out efficacy estimate |
| W01L | Output-length development and control eligibility | Historical length-control evidence retained | Development choices informed later diagnostic; no independent confirmation claim |
| W01D | 16 allowed + 16 disallowed authored endpoints; base/conditional/always-on | Harm 3/16, 3/16, 1/16; useful 16/16, 16/16, 14/16; unnecessary refusal 0/16, 0/16, 2/16 | Previously inspected diagnostic; visible-condition assistant review; safety–utility tradeoff |
| W02 | Four readouts, 201 cutoffs each; 16 fit, 8 nomination, 32 retrospective endpoints | U/deployed B harm 3/16; fitted B replay 2/16; remove witness → all 2/15; all useful 16/16 | Negative prespecified result; mixed fresh/replayed controls; no pooling with W03 |
| W03-fixed | 8 fresh authored families, 16 endpoints, 48 generations | U harm 3/8 vs both B 4/8; all useful 7/8 and refusal 0/8 | Same one endpoint drives descriptive advantage; arm-hidden assistant review |
| W03-live | 6 writers, 12 generated contexts | 11 contexts over 512 tokens; only one disallowed prompt eligible, all 3 responders safe | No allowed recovery or distinct-history efficacy comparison; exclusions are not safe outcomes |
| W03C | 16-family development, six input caps and L4 boundary checks | First technical nominee 1024: 15/16 technical but 14/16 semantic; threshold 15; no common cap selected | Larger cap cannot override frozen selection; engineering feasibility is not efficacy |
| W03RF128 | 128 authored families, 4 strata, 768 answers | U harm 33/128; fitted B 28/128; deployed B 33/128. Both superiority criteria fail | Five U-only harmful pairs vs fitted B; assistant-only review; conservative intervals |
| W03G-L4 | 48 writers, 128 contexts | 105/128 jointly eligible, 8/16 complete families at 1024; no cap selected | No responder efficacy run. Post hoc safe-pivot sensitivity at most 13/16 vs required 15 |
| W03G-CPU | Separate incomplete 16/24 writers, 48 observed contexts | 39/48 jointly eligible, 2/8 complete families; maximum 5/8 if missing favorable | Overlaps L4; no pooling or hardware causal claim. Post hoc sensitivity 42/48, 3/8, maximum 6/8 |
| W03H-pilot | Fresh 16 families, 48 writers; revised prospective safe-pivot rubric | All 128 contexts eligible; 16/16 complete; 9544 writer tokens | Development pilot; 29 within-family distinct histories, not 48 independent histories |
| W03H-heldout | Fresh 8 families, 24 writers, 144 responder reservations | 132 observed, 120 primary; observed harm 3/22 versus primary 0/19 per arm; zero main paired differences | 12 unrun + 12 quality exclusions; 9 harmful replies in one family remain visible. Five fully primary families; 15 distinct within-family histories |

W03RF128 registered simultaneous harm intervals are −22.26 to +30.07 percentage points for U-minus-fitted-B and ±26.17 for U-minus-deployed-B. These differ from finite-frame logical identification ranges (−1.32 to +8.69 and ±5.01 points). W03H all-reserved bounds (±20.83 disallowed, ±12.50 allowed points) are logical sensitivity ranges, not confidence intervals or equivalence evidence.

The original W03G eligibility failure remains part of the research record. W03H changed eligibility prospectively and used fresh cohorts; it does not retrospectively repair the original labels or identify the rubric's causal effect. No further model work is included in this release.
