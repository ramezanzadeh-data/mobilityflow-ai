"""
The single source of visual truth for the Streamlit UI.

All styling lives here rather than in per-page ``st.markdown("<style>")``
blocks. Scattered style blocks were how the interface drifted: each page
re-invented spacing and colour, so nothing was consistent and a change had
to be made in several places or not at all.

Design tokens are CSS custom properties on ``:root``. Components below
reference the tokens, never raw values, so the palette can be re-themed
(a customer's brand colours, a dark mode) by overriding the tokens alone.

Spacing follows an 8px grid. Every gap, padding and radius is a multiple
of ``--mf-space-1`` (4px) so vertical rhythm stays even without anyone
having to eyeball it.

Class names are prefixed ``mf-`` to avoid colliding with Streamlit's own
generated classes, which are unstable across versions.
"""

import streamlit as st


_THEME_CSS = """
<style>

:root {
    /* ---- Spacing: 8px grid (half-step available for tight optical work) */
    --mf-space-1: 4px;
    --mf-space-2: 8px;
    --mf-space-3: 12px;
    --mf-space-4: 16px;
    --mf-space-5: 24px;
    --mf-space-6: 32px;

    /* ---- Neutrals: one ramp, so text/border/surface stay related ----- */
    --mf-ink:         #0f172a;
    --mf-ink-muted:   #64748b;
    --mf-line:        #e2e8f0;
    --mf-surface:     #ffffff;
    --mf-surface-alt: #f8fafc;

    /* ---- Semantic status colours -------------------------------------
       Each has a text tone and a tint. The text tones are chosen to clear
       WCAG AA (4.5:1) against their own tint, so badges stay legible for
       low-vision users and on projectors in a meeting room.             */
    --mf-danger:       #b91c1c;
    --mf-danger-tint:  #fef2f2;
    --mf-danger-line:  #fecaca;

    --mf-warning:      #b45309;
    --mf-warning-tint: #fffbeb;
    --mf-warning-line: #fde68a;

    --mf-success:      #15803d;
    --mf-success-tint: #f0fdf4;
    --mf-success-line: #bbf7d0;

    --mf-info:         #1d4ed8;
    --mf-info-tint:    #eff6ff;
    --mf-info-line:    #bfdbfe;

    /* ---- Elevation & shape ------------------------------------------ */
    --mf-radius:    8px;
    --mf-radius-sm: 6px;
    --mf-radius-pill: 999px;
    --mf-shadow: 0 1px 2px rgba(15, 23, 42, .06),
                 0 1px 3px rgba(15, 23, 42, .04);
}

/* =====================================================================
   Field grid - the Case Overview summary.

   Replaces st.columns(8). Eight fixed Streamlit columns are eight equal
   fractions of the container regardless of viewport, so at ~90px each,
   values like "Permit F (Temporary admission)" wrapped one character per
   line and the risk alert rendered as a vertical column of letters.

   auto-fit + minmax gives each field a guaranteed minimum width and lets
   the row reflow to as many columns as actually fit - so the layout
   adapts to a laptop and to a widescreen without a breakpoint per size.
   ===================================================================== */
.mf-field-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: var(--mf-space-4);
    margin: var(--mf-space-2) 0 var(--mf-space-5) 0;
}

/* Narrower cells, for a short row of summary facts that should stay on
   one line. 120px is the floor at which a value like "Non-EU / EFTA"
   still reads - below that the wrapping this component was built to fix
   starts coming back, so it is a floor rather than a preference.

   Only worth using where the field count is small. Six of these fit a
   normal window; eight do not, which is why the case overview dropped
   two fields rather than shrinking further. */
.mf-field-grid--compact {
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: var(--mf-space-2);
    /* Inside a bordered container now, which supplies the separation the
       old bottom margin was standing in for. 24px of it below the fields
       pushed the provenance lines away from the score they qualify. */
    margin: var(--mf-space-1) 0 var(--mf-space-2) 0;
}

.mf-field-grid--compact .mf-field {
    padding: var(--mf-space-2) var(--mf-space-3);
}

.mf-field-grid--compact .mf-field__value {
    font-size: 14px;
}

.mf-field {
    display: flex;
    flex-direction: column;
    gap: var(--mf-space-1);
    min-width: 0;                 /* lets long values ellipsize, not overflow */
    padding: var(--mf-space-3) var(--mf-space-4);
    background: var(--mf-surface);
    border: 1px solid var(--mf-line);
    border-radius: var(--mf-radius);
    box-shadow: var(--mf-shadow);
}

.mf-field__label {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: .04em;
    text-transform: uppercase;
    color: var(--mf-ink-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.mf-field__value {
    font-size: 15px;
    font-weight: 500;
    line-height: 1.4;
    color: var(--mf-ink);
    /* Wrap between words only. `break-word` is what allowed the original
       character-by-character shredding once the column got narrow. */
    overflow-wrap: break-word;
    word-break: normal;
}

.mf-field__value--empty {
    color: var(--mf-ink-muted);
    font-style: italic;
}

/* =====================================================================
   Typography

   Streamlit's default headings are sized independently of anything else
   in this stylesheet, so a page title and the cards beneath it looked
   like they came from two different products. The scale below is a
   ratio, not a list of numbers picked one at a time: each step is
   roughly 1.25x the one below, which is what makes a hierarchy read as
   deliberate rather than arbitrary.

   Applied to the semantic elements rather than to Streamlit's generated
   class names, which change between versions.
   ===================================================================== */
:root {
    --mf-text-xs:   11px;   /* metadata, provenance   */
    --mf-text-sm:   12px;   /* captions, help text    */
    --mf-text-base: 14px;   /* body                   */
    --mf-text-lg:   17px;   /* section titles         */
    --mf-text-xl:   22px;   /* page titles            */
    --mf-text-2xl:  28px;   /* KPI figures            */
}

/* The page title block. */
.mf-page {
    margin-bottom: var(--mf-space-5);
}

.mf-page__title {
    margin: 0;
    font-size: var(--mf-text-xl);
    font-weight: 650;
    /* Negative tracking at larger sizes: type set at display size looks
       loose with the spacing that suits body text. */
    letter-spacing: -0.015em;
    line-height: 1.25;
    color: var(--mf-ink);
}

.mf-page__subtitle {
    margin: var(--mf-space-2) 0 0 0;
    font-size: var(--mf-text-base);
    line-height: 1.5;
    color: var(--mf-ink-muted);
    max-width: 70ch;   /* long lines are measurably harder to read */
}

/* =====================================================================
   Bordered containers

   st.container(border=True) draws a 1px hairline in Streamlit's own
   neutral, which at this density disappeared: Case Overview and Workflow
   Stage looked like loose content rather than two defined panels. A
   heavier, darker edge is what makes a box read as a box.

   Scoped with :has(.mf-panel-marker) rather than applied to the wrapper
   directly. Streamlit emits stVerticalBlockBorderWrapper for every
   container, not only those created with border=True, so the unscoped
   rule would have drawn a border around things that are not panels.
   ===================================================================== */
section[data-testid="stMain"]
[data-testid="stVerticalBlockBorderWrapper"]:has(.mf-panel-marker) {
    border: 2px solid var(--mf-ink-muted);
    border-radius: var(--mf-radius);
    background: var(--mf-surface);
}

/* The marker itself takes no space. */
.mf-panel-marker {
    display: none;
}

/* Section headings within a page. */
.mf-section {
    margin: var(--mf-space-6) 0 var(--mf-space-3) 0;
}

/* A section that follows the page identity directly. The standard space
   above separates one section from the previous one; here there is no
   previous section, and the full gap left the heading looking detached
   from the page it belongs to. */
.mf-section--tight {
    margin-top: var(--mf-space-3);
}

.mf-section__title {
    margin: 0;
    font-size: var(--mf-text-lg);
    /* 700, not 600. These headings now sit inside bordered containers,
       and at 600 they read as another line of content in the box rather
       than as the thing naming it. */
    font-weight: 700;
    letter-spacing: -0.005em;
    line-height: 1.3;
    color: var(--mf-ink);
}

/* .mf-section--split and .mf-section__identity* were here, for a section
   heading with the case subject beside it. Both are gone with the two
   layout components that emitted them: the employee's name is the page
   title now, so nothing renders an identity on a heading line.

   Removed rather than left in place. A class defined in the stylesheet
   and emitted by nothing is the mirror of the defect recorded at the top
   of components/workflow.py - a class emitted by the markup and defined
   in no stylesheet, which styled nothing and was not noticed for a
   release. Both cost the same to keep and mislead the next reader the
   same way. */

/* A short status beside a heading - "Stage 1/7", next to the section it
   counts. Quiet on purpose: it belongs to the heading rather than
   competing with it. */
.mf-section__meta {
    font-size: var(--mf-text-sm);
    font-weight: 500;
    color: var(--mf-ink-muted);
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
}

.mf-section__description {
    margin: var(--mf-space-1) 0 0 0;
    font-size: var(--mf-text-sm);
    line-height: 1.5;
    color: var(--mf-ink-muted);
    max-width: 70ch;
}

/* Streamlit's own headings, for the places that still use them - inside
   expanders and tabs, where a custom block would break the container's
   spacing. Brought onto the same scale so they do not stand out. */
section[data-testid="stMain"] h1 {
    font-size: var(--mf-text-xl);
    font-weight: 650;
    letter-spacing: -0.015em;
}

section[data-testid="stMain"] h2 {
    font-size: var(--mf-text-lg);
    font-weight: 600;
    letter-spacing: -0.005em;
}

section[data-testid="stMain"] h3 {
    font-size: var(--mf-text-base);
    font-weight: 600;
}

/* Captions carry help text and provenance notes; they are read, not
   skimmed, so they get a comfortable line height rather than the
   tightest one that fits. */
section[data-testid="stMain"] [data-testid="stCaptionContainer"] {
    font-size: var(--mf-text-sm);
    line-height: 1.55;
}

/* =====================================================================
   Sidebar: brand, user, navigation

   The frame is on screen for 100% of the session, so it carries more of
   the impression of quality than any single page does. What was there
   before: three lines of 13px text and a bare radio list, with no
   product identity and no visual hierarchy between "who am I" and
   "where can I go".
   ===================================================================== */

/* ---- Brand ---- */
.mf-brand {
    display: flex;
    align-items: center;
    gap: var(--mf-space-3);
    padding: var(--mf-space-2) 0 var(--mf-space-5) 0;
}

.mf-brand__mark {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 30px;
    height: 30px;
    border-radius: var(--mf-radius-sm);
    background: var(--mf-info);
    color: #fff;
    font-size: 16px;
    font-weight: 700;
    flex: 0 0 auto;
}

.mf-brand__name {
    font-size: 16px;
    font-weight: 650;
    letter-spacing: -0.01em;
    color: var(--mf-ink);
    white-space: nowrap;
}

.mf-brand__suffix {
    margin-left: 4px;
    font-weight: 500;
    color: var(--mf-info);
}

/* ---- Signed-in user ---- */
.mf-user {
    display: flex;
    align-items: center;
    gap: var(--mf-space-3);
    padding: var(--mf-space-3);
    margin-bottom: var(--mf-space-4);
    background: var(--mf-surface);
    border: 1px solid var(--mf-line);
    border-radius: var(--mf-radius);
}

.mf-user__avatar {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 32px;
    height: 32px;
    border-radius: 50%;
    background: var(--mf-surface-alt);
    border: 1px solid var(--mf-line);
    color: var(--mf-ink-muted);
    font-size: 14px;
    font-weight: 600;
    flex: 0 0 auto;
}

/* min-width:0 lets the long strings below ellipsize instead of pushing
   the block wider than the sidebar. */
.mf-user__text { min-width: 0; }

.mf-user__name,
.mf-user__company,
.mf-user__role {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}

.mf-user__name {
    font-size: 13px;
    font-weight: 600;
    color: var(--mf-ink);
}

/* Same weight as the username: in a multi-tenant product, "whose data am
   I looking at" is not secondary information. */
.mf-user__company {
    font-size: 12px;
    color: var(--mf-ink);
}

.mf-user__role {
    font-size: 11px;
    letter-spacing: .03em;
    text-transform: uppercase;
    color: var(--mf-ink-muted);
}

/* ---- Navigation ---- */
.mf-nav__section {
    padding: var(--mf-space-2) 0 var(--mf-space-1) 0;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: var(--mf-ink-muted);
}

/* Streamlit renders st.radio as a list of labelled radio inputs. Hiding
   the dot and styling the label turns the same widget into a navigation
   list, without replacing it - the widget still owns the state, so
   behaviour and keyboard support are unchanged. */
section[data-testid="stSidebar"] div[role="radiogroup"] {
    gap: 2px;
}

section[data-testid="stSidebar"] div[role="radiogroup"] > label {
    padding: var(--mf-space-2) var(--mf-space-3);
    border-radius: var(--mf-radius-sm);
    font-size: 14px;
    cursor: pointer;
    transition: background .12s ease;
}

section[data-testid="stSidebar"] div[role="radiogroup"] > label:hover {
    background: var(--mf-surface-alt);
}

section[data-testid="stSidebar"] div[role="radiogroup"] > label:has(input:checked) {
    background: var(--mf-info-tint);
    color: var(--mf-info);
    font-weight: 600;
    /* A left rule as well as colour: the active entry stays identifiable
       without relying on hue alone. */
    box-shadow: inset 3px 0 0 var(--mf-info);
}

section[data-testid="stSidebar"] div[role="radiogroup"] > label > div:first-child {
    display: none;   /* the radio dot; the highlight conveys selection */
}

/* Keyboard users must still be able to see where they are, and the dot
   above is what normally carries the browser's focus ring. */
section[data-testid="stSidebar"] div[role="radiogroup"] > label:focus-within {
    outline: 2px solid var(--mf-info);
    outline-offset: 1px;
}

/* =====================================================================
   Statutory obligations

   Each row shows the deadline and, on the same line, where the rule came
   from. A date the customer cannot trace is a date they cannot defend to
   an auditor, so provenance is not tucked behind a link.
   ===================================================================== */
.mf-obligation {
    padding: var(--mf-space-3) var(--mf-space-4);
    margin-bottom: var(--mf-space-2);
    background: var(--mf-surface);
    border: 1px solid var(--mf-line);
    border-left: 3px solid var(--mf-line);
    border-radius: var(--mf-radius-sm);
}

.mf-obligation__head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--mf-space-3);
}

.mf-obligation__title {
    font-size: 14px;
    font-weight: 600;
    color: var(--mf-ink);
}

.mf-obligation__due {
    margin-top: var(--mf-space-1);
    font-size: 13px;
    color: var(--mf-ink);
    font-variant-numeric: tabular-nums;
}

.mf-obligation__detail {
    margin-top: var(--mf-space-1);
    font-size: 12px;
    line-height: 1.5;
    color: var(--mf-ink-muted);
}

.mf-obligation__provenance {
    margin-top: var(--mf-space-2);
    padding-top: var(--mf-space-2);
    border-top: 1px dashed var(--mf-line);
    font-size: 11px;
    line-height: 1.5;
    color: var(--mf-ink-muted);
}

/* =====================================================================
   Empty state

   The screen a customer sees before they have data - including the very
   first screen of every new account, and the one a prospect sees in a
   demo on a fresh tenant. Given real space rather than rendered as a
   throwaway notice, because it is doing real work: explaining the
   product to someone who has not used it yet.
   ===================================================================== */
.mf-empty {
    max-width: 640px;
    margin: var(--mf-space-6) 0;
    padding: var(--mf-space-6);
    background: var(--mf-surface);
    border: 1px solid var(--mf-line);
    border-radius: var(--mf-radius);
    box-shadow: var(--mf-shadow);
}

.mf-empty__title {
    font-size: 18px;
    font-weight: 600;
    color: var(--mf-ink);
}

.mf-empty__body {
    margin: var(--mf-space-3) 0 0 0;
    font-size: 14px;
    line-height: 1.6;
    color: var(--mf-ink-muted);
}

.mf-empty__steps {
    margin: var(--mf-space-4) 0 0 0;
    padding-left: var(--mf-space-5);
    font-size: 14px;
    line-height: 1.9;
    color: var(--mf-ink);
}

/* =====================================================================
   KPI cards
   ===================================================================== */
.mf-kpi {
    padding: var(--mf-space-4);
    background: var(--mf-surface);
    border: 1px solid var(--mf-line);
    border-radius: var(--mf-radius);
    box-shadow: var(--mf-shadow);
    height: 100%;
}

.mf-kpi__label {
    font-size: 11px;
    font-weight: 600;
    letter-spacing: .04em;
    text-transform: uppercase;
    color: var(--mf-ink-muted);
}

.mf-kpi__value {
    margin-top: var(--mf-space-1);
    font-size: 28px;
    font-weight: 600;
    line-height: 1.2;
    color: var(--mf-ink);
    font-variant-numeric: tabular-nums;
}

/* A metric with nothing to measure yet is muted rather than absent, so
   the card keeps its place in the row without claiming to be a figure. */
.mf-kpi__value--empty {
    color: var(--mf-line);
}

.mf-kpi__note {
    margin-top: var(--mf-space-1);
    font-size: 11px;
    line-height: 1.4;
    color: var(--mf-ink-muted);
}

/* =====================================================================
   Distribution bars

   Replaces st.bar_chart for low-cardinality breakdowns. With two
   categories the chart drew a y-axis from 0.0 to 2.0, one full-width
   block, and rotated the category label to vertical. Here the label is
   always horizontal and the count is always a number.
   ===================================================================== */
.mf-dist {
    display: flex;
    flex-direction: column;
    gap: var(--mf-space-2);
    margin-bottom: var(--mf-space-4);
}

.mf-dist__row {
    display: grid;
    grid-template-columns: minmax(70px, 30%) 1fr auto;
    align-items: center;
    gap: var(--mf-space-3);
}

.mf-dist__label {
    font-size: 13px;
    color: var(--mf-ink);
    /* Long canton or permit names ellipsize; the full text stays
       available through the title attribute. Never wraps, so a label can
       never turn into the vertical text this replaced. */
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.mf-dist__track {
    height: 8px;
    background: var(--mf-surface-alt);
    border-radius: var(--mf-radius-pill);
    overflow: hidden;
}

.mf-dist__bar {
    height: 100%;
    background: var(--mf-info);
    border-radius: var(--mf-radius-pill);
}

.mf-dist__value {
    min-width: 24px;
    text-align: right;
    font-size: 13px;
    font-weight: 600;
    color: var(--mf-ink);
    font-variant-numeric: tabular-nums;
}

/* =====================================================================
   Record row - one record summarised horizontally (the case list).

   Replaces a hand-built row that used white-space:nowrap plus seven
   fixed margin-right:35px spacers. That combination locks the row to a
   fixed pixel width regardless of viewport, so the last item - the risk
   badge - was cut off mid-word ("🔺 H").

   flex-wrap + gap lets the items reflow onto a second line when space
   runs out, which is always preferable to silently losing information.
   ===================================================================== */
.mf-record-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--mf-space-2) var(--mf-space-5);
    padding: var(--mf-space-3) 0;
    font-size: 14px;
    color: var(--mf-ink);
}

.mf-record-row__item {
    display: inline-flex;
    align-items: center;
    gap: var(--mf-space-2);
    min-width: 0;
}

/* =====================================================================
   Badges - inline status pills.

   st.error()/st.warning() render a full-width alert block, which is why
   the risk indicator became a tall vertical strip inside a narrow column.
   A badge is inline-flex and never wider than its own text.
   ===================================================================== */
.mf-badge {
    display: inline-flex;
    align-items: center;
    gap: var(--mf-space-2);
    padding: var(--mf-space-1) var(--mf-space-3);
    border: 1px solid transparent;
    border-radius: var(--mf-radius-pill);
    font-size: 13px;
    font-weight: 600;
    line-height: 1.5;
    white-space: nowrap;          /* the fix for vertical "H I G H" text */
}

.mf-badge__score {
    padding-left: var(--mf-space-2);
    border-left: 1px solid currentColor;
    font-variant-numeric: tabular-nums;
    opacity: .85;
}

.mf-badge--danger {
    color: var(--mf-danger);
    background: var(--mf-danger-tint);
    border-color: var(--mf-danger-line);
}

.mf-badge--warning {
    color: var(--mf-warning);
    background: var(--mf-warning-tint);
    border-color: var(--mf-warning-line);
}

.mf-badge--success {
    color: var(--mf-success);
    background: var(--mf-success-tint);
    border-color: var(--mf-success-line);
}

.mf-badge--info {
    color: var(--mf-info);
    background: var(--mf-info-tint);
    border-color: var(--mf-info-line);
}

.mf-badge--neutral {
    color: var(--mf-ink-muted);
    background: var(--mf-surface-alt);
    border-color: var(--mf-line);
}

/* =====================================================================
   Workflow stepper

   The stages were previously one vertical emoji bullet per line, which
   used seven rows to say "we are at step 1 of 7" and gave no sense of a
   process. A horizontal track shows completed, current and remaining work
   in one glance - the pattern every comparable product uses.
   ===================================================================== */
.mf-stepper {
    margin: var(--mf-space-2) 0 var(--mf-space-5) 0;
}

/* Heading, track and counter on one row.

   The track takes the space the other two do not, so the stages spread
   across whatever is left rather than being sized independently of the
   room available. Aligned to the top, not the centre: the dots sit at a
   fixed height inside the track and the labels hang below them, so
   centring would push the heading down to the middle of a two-line
   block and leave it floating beside the labels rather than the dots. */
.mf-stage-row {
    display: flex;
    align-items: flex-start;
    gap: var(--mf-space-5);
    margin: var(--mf-space-2) 0 var(--mf-space-3) 0;
    /* Wraps rather than clips.
       On one row when there is room, which is what it is for. When there
       is not, the track drops to its own full-width line instead of
       scrolling out of view - a printout showed Decision and Completed
       simply absent, and a stage track that hides the last two stages is
       worse than a second line. */
    flex-wrap: wrap;
}

.mf-stage-row .mf-stepper__track {
    flex: 1;
    min-width: 0;
}

/* Nudged down to sit level with the dots rather than the top of the
   track box. 4px of step padding plus half a 20px marker. */
.mf-stage-row__title,
.mf-stage-row__meta {
    flex: none;
    padding-top: var(--mf-space-1);
    white-space: nowrap;
}

.mf-stepper__track {
    display: flex;
    align-items: flex-start;
    gap: 0;
    margin: 0;
    padding: 0;
    list-style: none;
    /* No horizontal scroll. It kept the steps readable in a browser and
       silently removed them everywhere else: printed to PDF, the track
       ended at "Author..." with two of seven stages gone and nothing to
       indicate they existed. The row wraps instead. */
    min-width: 520px;
}

/* A column: marker, then label, stacked by the layout rather than by a
   padding that has to be kept larger than the marker by hand.

   It was the hand-kept version before, and it was wrong on screen: the
   marker sat outside the flow at `position: absolute`, and the label was
   pushed clear of it by `padding-top: var(--mf-space-5)` - 24px. The
   marker is 16px plus a 2px border on each side, so it ends at 22px, and
   the current step's focus ring extends 4px past that to 26px. The gap
   was therefore negative, and every label rendered underneath its own
   marker: "Draft" appeared as "t", "Submitted" as "Sub<dot>itted".

   Two numbers that had to be kept in a relationship no rule expressed.
   Now the marker occupies its own space, so the label cannot overlap it
   whatever either one's size becomes. */
.mf-step {
    position: relative;
    flex: 1 1 0;
    min-width: 74px;
    display: flex;
    flex-direction: column;
    align-items: center;
    /* Clears the 4px focus ring on the current step with room to spare. */
    gap: var(--mf-space-3);
    padding: var(--mf-space-1) 0 0 0;
    text-align: center;
}

/* The connector line, drawn behind the markers.

   Absolutely positioned, so it is not a flex item and does not take a
   slot in the column above. `top` is the marker's centre: 4px of padding
   plus half of the marker's 20px outer height. */
.mf-step::before {
    content: "";
    position: absolute;
    top: 14px;
    left: -50%;
    width: 100%;
    height: 2px;
    background: var(--mf-line);
}

.mf-step:first-child::before {
    display: none;
}

.mf-step--done::before,
.mf-step--current::before {
    background: var(--mf-info);
}

/* In normal flow now, as a flex item, so it reserves the space it
   occupies. Left at content-box sizing on purpose: the tick mark below
   is positioned against a 16px interior, and switching to border-box
   would silently move it. */
.mf-step__marker {
    position: relative;
    flex: none;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    border: 2px solid var(--mf-line);
    background: var(--mf-surface);
    /* Above the connector line, which is drawn across the whole step. */
    z-index: 1;
}

.mf-step--done .mf-step__marker {
    border-color: var(--mf-info);
    background: var(--mf-info);
}

/* Tick mark on completed steps: shape, not colour alone, so the state is
   still distinguishable with colour vision deficiency. */
.mf-step--done .mf-step__marker::after {
    content: "";
    position: absolute;
    top: 1px;
    left: 4px;
    width: 3px;
    height: 7px;
    border: solid var(--mf-surface);
    border-width: 0 2px 2px 0;
    transform: rotate(45deg);
}

.mf-step--current .mf-step__marker {
    border-color: var(--mf-info);
    background: var(--mf-info);
    box-shadow: 0 0 0 4px var(--mf-info-tint);
}

.mf-step__label {
    display: block;
    padding: 0 var(--mf-space-2);
    font-size: 12px;
    line-height: 1.35;
    color: var(--mf-ink-muted);
    overflow-wrap: break-word;
    word-break: normal;
}

.mf-step--current .mf-step__label {
    color: var(--mf-info);
    font-weight: 600;
}

.mf-step--done .mf-step__label {
    color: var(--mf-ink);
}

.mf-stepper__meta {
    margin-top: var(--mf-space-3);
    font-size: 12px;
    color: var(--mf-ink-muted);
    font-variant-numeric: tabular-nums;
}

/* Available to screen readers, invisible on screen. Used to announce
   which step is current without repeating it visually. */
.mf-visually-hidden {
    position: absolute;
    width: 1px;
    height: 1px;
    margin: -1px;
    padding: 0;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
    border: 0;
}

/* =====================================================================
   Buttons

   Streamlit renders a button label as ordinary wrapping text inside a
   flex child, so a button placed in a narrow st.columns() slot breaks
   mid-phrase and grows into a multi-line block: "Back to Dash boar d"
   across five lines, "Generate Checklist" over two while its two
   neighbours stayed on one.

   Fixing it here rather than per call site means it holds for every
   button in the app, including ones not written yet. Buttons keep their
   natural width; only the shredding is prevented.
   ===================================================================== */
.stButton > button,
.stDownloadButton > button {
    white-space: nowrap;
    min-height: 38px;
    padding: var(--mf-space-2) var(--mf-space-4);
    border-radius: var(--mf-radius-sm);
    font-weight: 500;
    line-height: 1.4;
}

/* A row of related buttons should read as one row. Equal st.columns()
   widths sized every button to the widest label's column rather than to
   its own text, which is what left "Generate Checklist" alone on two
   lines between two single-line siblings. */
div[data-testid="column"] .stButton > button {
    width: auto;
}

/* =====================================================================
   Accessibility
   ===================================================================== */

/* Streamlit's default focus ring is easy to lose against the light
   surface. Keyboard users need to see where they are at all times. */
.stButton > button:focus-visible,
.stSelectbox div[data-baseweb="select"]:focus-within,
.stTextInput input:focus-visible {
    outline: 2px solid var(--mf-info) !important;
    outline-offset: 2px !important;
}

@media (prefers-reduced-motion: reduce) {
    * {
        animation-duration: .01ms !important;
        transition-duration: .01ms !important;
    }
}

</style>
"""


def inject_theme() -> None:
    """
    Emit the stylesheet once per page render.

    Called from the app entry point before any page renders. Streamlit
    reruns the whole script on every interaction, so this runs again on
    each rerun - which is intended and idempotent: the browser simply
    replaces an identical <style> block.
    """

    st.markdown(_THEME_CSS, unsafe_allow_html=True)
