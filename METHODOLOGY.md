# Reporting Methodology

How this repository turns a data-entry form into a set of role-appropriate
reports. This is the process to repeat whenever a new form is added to
`_MODULE_SPECS`; following it should require no new analytics code in the common
case.

## 1. The problem

A form is one table of submissions. Five different people need five different
things from that table. A class teacher who filed the row wants to see the row.
A principal wants to know whether the thing the row describes is getting better
or worse, and what to do about it. Handing the principal the raw rows is a
failure of the product, not a feature of it.

The `DMS - IMPACT.pptx` deck states this as a chain:

> Right Information → Right Person → Right Action → Controlled Consumption →
> Reduced Cost & Wastage.

Everything below is machinery for the first two arrows.

## 2. Tiers

The deck names five escalating positions (ENTRY, SUPPORT, EXECUTER, MONITOR,
ENSURE, DECISION). This app has five roles and **we do not add more**. The
mapping is:

| Tier | Roles | Decision they are making | What they get |
|---|---|---|---|
| `ENTRY` | `class_teacher`, `catalyst_member`, `office` | Did this happen, and is my own record complete and correct? | Own records, row-level detail, completeness prompts, own recent trend |
| `SUPPORT` | `academic_supervisor` | Who needs help this week, and what arrangement must I make? | Cross-owner aggregates, outliers, unresolved challenges, backlog, comparisons between sections |
| `DECISION` | `administrator` | Is the system working, what is it costing, what should change? | Everything: trends over long windows, SWOT, red flags, benchmarks, forecasts, export |

Tier is derived, never stored: `tier_of(role)` in `desk/analytics/access.py`.
`administrator` sees the union of all tiers, because that is already true
everywhere else in the app (`allowed_modules`, `records_for`).

The deck's EXECUTER/MONITOR/ENSURE labels describe *what a tier does with the
report*, not additional access levels. They survive as narrative headings in the
report templates, not as roles.

### Escalation rule

An analysis belongs to the **lowest** tier that can act on its result.

- Can only the person who wrote the row fix it? → `ENTRY`.
- Does fixing it require coordinating two or more owners? → `SUPPORT`.
- Does fixing it require money, policy, or staffing? → `DECISION`.

Analyses are inherited upward: a `SUPPORT` analysis is visible to `SUPPORT` and
`DECISION`, never downward. Row-level identity (who was absent, which roll
number) stops at `SUPPORT`; above that it is aggregated, because the deck is
explicit that a principal needs "on which day day boarding was less", not the
names.

## 3. Analyses are generated, not hand-written

59 forms × 50 analyses = 2,950 blocks. Nobody maintains that. Instead:

**A. Primitives.** `desk/analytics/primitives.py` holds ~60 pure functions, each
of the shape `(series, context) -> Insight | None`. They know nothing about
schools. Families:

| Family | Examples |
|---|---|
| Volume | total, mean, median, per-period rate, coverage |
| Trend | slope, direction, streak, momentum vs previous window, seasonality by weekday/month |
| Distribution | histogram, top-N, bottom-N, concentration, diversity, mode |
| Outlier | z-score, IQR fence, sudden drop, sudden spike, record high/low |
| Comparison | segment gap (by standard/level/shift/owner), best vs worst, rank table |
| Quality | blank rate, required-field completeness, late filing, duplicate suspicion |
| Text | recurring keyword, unresolved-issue count, sentiment-free theme grouping |
| Risk | threshold breach, repeated breach (red flag), overdue follow-up |
| Synthesis | SWOT quadrant assembly, headline narrative, recommended action |

Nothing in this list calls a model or an external service. It is arithmetic and
string frequency counting. This is a hard constraint of the project.

**B. Binding.** `desk/analytics/engine.py` walks a `Module`'s `fields` and
applies every primitive whose input contract matches the `Field.kind`:

| `Field.kind` | Primitives applied |
|---|---|
| `date` | trend, seasonality, streak, gap detection, filing latency |
| `integer` | volume, trend, outlier, distribution, comparison, threshold |
| `choice` | distribution, mode, concentration, segment comparison, coverage |
| `text` | completeness, duplicate suspicion, keyword frequency |
| `longtext` | keyword frequency, unresolved-issue count, theme grouping, length-as-effort |

Plus cross-field pairings: every `integer` is crossed with every `choice` for
segment comparison, and with `event_date` for trend. That crossing is what
carries a typical form past 50 analyses without any per-form authoring.

**C. Overrides.** `desk/analytics/specs.py` adds hand-written, domain-specific
analyses for the five hubs the deck documents (`dayboarding`, `exam_details`,
`stationary`, `field_trip`, `assembly_console`). These are the ones a generic primitive cannot
infer — "food wastage on days when the rating for food served was below 3", the
red-flag escalation for "problems continuing for a long period". A spec entry
may also *suppress* a generated analysis that is meaningless for that form, and
may *override* the tier a generated analysis defaults to.

Generated + overrides = the catalogue. `catalogue_for(module)` returns it; the
count is asserted in tests.

## 4. Compute model

On the fly, per request. `list_records()` → filter → `get_data()` (decrypt in
memory) → aggregate in Python → render.

No derived table, no metrics collection, no cache of plaintext. The reasons are
not performance:

1. Payloads are AES-GCM encrypted with the record UUID as associated data.
   Any persisted aggregate would be plaintext at rest, silently undoing that.
2. `TVS_DATA_KEY` is unrotatable; a second copy of the data is a second thing to
   get wrong.
3. It behaves identically on `DjangoStore` and `FirestoreStore` with no schema
   change and no new Firestore collection.

If a school's volume ever makes this slow, the fix is a request-scoped cache and
a narrower date window — not persistence.

## 5. Field visibility

Analyses answer "what may this tier see, by default". The super-admin console
(`/reports/visibility/`) answers "what does this school actually want them to
see". It is a per-`(module_key, role, field_key)` override, deny-only: it can
hide a field that the tier matrix allows, never reveal one it forbids. Enforced
at the point where a record is turned into output, so it applies to reports,
tables, and exports alike.

Three paths turn a stored record into output, and the override binds on all
three: `filter_insights()` for reports, `visible_fields()` for rendered field
lists, and `redact_row()` inside `record_to_dict()` for the raw-record export.
A new output path must call one of them —
`test_hiding_a_field_redacts_the_raw_record_export` exists because the export
was originally missed, and reports and exports disagreeing about what is hidden
is the failure mode to guard against. Backups are deliberately exempt: they copy
ciphertext without decrypting, so a redacted backup would silently corrupt a
restore.

Deny-only matters. If the toggle could grant, a mis-click would hand roll
numbers to someone the escalation rule deliberately kept them from.

## 6. Presentation

- Infographics are **server-rendered inline SVG**. The CSP set in
  `ActivityDeskSecurityMiddleware` is `script-src 'self'; style-src 'self'`, so
  no CDN chart library and no inline `style=`/`<script>` will run. Chart helpers
  live in `desk/analytics/charts.py` and emit markup styled by classes in
  `static/desk/app.css`.
- Every insight carries a `severity` (`good` / `neutral` / `watch` / `alert`) so
  the same data renders as a calm card or a red flag without template logic.
- Exports: XLSX and CSV reuse `tvs_dms/exporter.py` (keep the formula-escaping;
  it is tested). PDF is admin-only and is rendered from the same insight objects,
  so a PDF and the screen can never disagree.

## 6a. Mapping the IMPACT deck onto modules

`DMS - IMPACT.pptx` documents five hubs. Each names its "Data collected / hub"
line, and those field lists are the authority for what the form must capture —
an analysis the deck promises cannot exist if the field was never collected.

| Deck hub | Module | Entry role | Deck-mandated fields |
|---|---|---|---|
| DAY BOARDING / CANTEEN | `dayboarding` | catalyst_member | `attendance`, `expected_attendance`, `food_wastage`, `wastage_notes`, `rating_food`, `rating_student_feedback`, `rating_staff_feedback`, `rating_waiting_time`, `waiting_minutes`, `challenges` |
| EXAM COMMITTEE (+ PORTIONS) | `exam_details` | academic_supervisor | `students_expected`, `students_appeared`, `absentees`, `od_count`, `od_students`, `subject`, `portion_covered`, `qp_status`, `paper_arrangement`, `invigilators`, `invigilation_notes`, `challenges` |
| STATIONARY | `stationary` | office | `item`, `department`, `category`, `opening_stock`, `received`, `issued`, `closing_stock`, `pending_items`, `pending_count`, `unit_cost`, `receipt_reference`, `supplier`, `stock_status` |
| FIELD TRIP | `field_trip` | catalyst_member | `venue_planned`, `destination`, `participants`, `students_expected`, `staff_count`, `transport_mode`, `budget`, `learning_outcome`, `student_engagement`, `feedback`, `challenges` |
| ASSEMBLY | `assembly_console` | class_teacher | `participants`, `students_expected`, `theme`, `programme_flow`, `flow_rating`, `student_performance`, `values_shared`, `feedback`, `challenges` |

Three conventions hold across all five, and should hold for any hub added later:

- **Ratings share one vocabulary.** `RATINGS` and `EXTENT` in `tvs_dms/forms.py`
  are used verbatim by every hub. `_scale_score()` maps a rating onto 0–100 by
  its *position* in that tuple, so a hub that invents its own labels silently
  scores nothing. Anything off-scale is dropped, never guessed.
- **A count and its denominator are always collected as a pair.** Utilisation,
  turnout, appearance rate and stock turnover are all ratios; collecting only
  the numerator turns a decision-grade insight into a bare number.
- **Identity fields are collected but never escalate.** `absentees` and
  `od_students` exist because the entry tier genuinely needs the roll numbers.
  They match `IDENTITY_FIELD_HINTS`, so the engine caps any analysis touching
  them at `SUPPORT` — this is the deck's own "the principal needs insights, not
  roll numbers" rule, enforced structurally rather than by convention.

Two tests keep this honest: `test_impact_deck_fields_exist_on_their_hubs` fails
if a documented field is dropped, and
`test_every_declared_spec_analysis_can_actually_fire` fails if `specs.py`
advertises an analysis its builder never emits.

Backwards compatibility: records filed before a field existed simply lack it.
Builders fall back to the older field where one existed (`attendance` →
`participants`, `students_expected` → `participants`) rather than discarding
history, and name **both** keys in `fields_used` so hiding either one in the
visibility console still suppresses the analysis.

## 7. Adding a new form

1. Add the `Module` to `_MODULE_SPECS`, using `f()` / `activity_fields()` /
   `simple_activity()`. Use accurate `kind`s — `kind` is what the engine binds
   on, so a numeric field typed as `text` silently loses ~15 analyses.
   `f()` is positional — `f(key, label, kind, required, choices, hint)` — so
   `f("x", "X", "choice", CHOICES)` puts the tuple in `required` and leaves the
   field required with no options. Pass `False` explicitly for optional choice
   fields. `test_field_definitions_are_well_formed` catches this.
2. Update the module-count assertions in `tests/test_core.py` **and**
   `desk/tests.py` (both assert the 59 total; the former also asserts per-role
   counts). Update the counts in `CLAUDE.md` too.
3. Run the catalogue check: `python manage.py test desk.tests.AnalyticsCatalogueTests`.
   It fails if any module yields fewer than 50 analyses, which tells you the
   field kinds are wrong before a user finds out.
4. Read the generated catalogue (`/reports/<module_key>/?debug_catalogue=1` as
   an administrator). For each analysis ask the escalation question in §2 and
   correct any tier that is wrong via a `specs.py` override.
5. Add domain-specific analyses to `specs.py` for anything the primitives cannot
   see — usually a relationship between two specific fields, or a threshold that
   only means something in context.
6. Suppress generated analyses that are noise for this form.
7. Leave the visibility console alone. It is per-school configuration, not
   part of onboarding a form.

The only step that requires judgement is 4–6. Steps 1–3 are mechanical, and a
form that is typed correctly is reportable the moment it is defined.

## 8. What this deliberately does not do

- No LLM, no AI API, no external inference of any kind, anywhere in this
  pipeline. Every number and every sentence in a report is produced by
  deterministic Python that can be read and audited.
- No prediction presented as fact. Forecast primitives state their window and
  their method in the insight text.
- No cross-school or cross-tenant comparison. There is one school.
