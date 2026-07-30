-- =====================================================================
-- Migration 0006 (up): the language a case is corresponded in.
--
-- Applied by db.database._migrate_case_correspondence_language() during
-- init_db().
--
-- Why this is not the user's language
-- -----------------------------------
-- Until now there was one language setting, held in the Streamlit
-- session, and everything followed it - the buttons, the reports, and
-- the emails the product drafts to Swiss authorities.
--
-- That conflates two different questions:
--
--     "what language does this specialist read?"
--     "what language must this letter be written in?"
--
-- In Valais they routinely have different answers. The canton is
-- officially bilingual: the lower Valais works in French, the Oberwallis
-- in German, and the boundary runs through the middle of the canton. A
-- German-speaking mobility manager in Zurich handling an arrival in
-- Martigny needs a German interface and a French letter to the Contrôle
-- des habitants. With one setting they get whichever they last clicked,
-- and the mistake is invisible until a commune replies asking for a
-- resubmission.
--
-- The user's language stays in the session, where it belongs - it is a
-- preference, and it may differ between two people opening the same case.
-- The correspondence language belongs to the case, because the authority
-- it will be sent to does not change when a different colleague opens it.
--
-- NULL means "not decided yet"
-- ----------------------------
-- Not defaulted to a language. Every existing case predates this column,
-- and writing 'fr' into all of them would assert something about each one
-- that nobody checked. The application falls back to the canton's
-- principal administrative language and says on screen that it is doing
-- so, which is a visible assumption rather than a stored fact.
--
-- Constrained to the languages the product actually ships. An unchecked
-- value here would reach an LLM prompt as "write this in xx" and produce
-- a letter in a language nobody at the commune reads.
--
-- Safe to re-run.
-- =====================================================================

ALTER TABLE cases
    ADD COLUMN IF NOT EXISTS correspondence_language TEXT;


ALTER TABLE cases
    DROP CONSTRAINT IF EXISTS cases_correspondence_language_known;

ALTER TABLE cases
    ADD CONSTRAINT cases_correspondence_language_known CHECK (
        correspondence_language IS NULL
        OR correspondence_language IN ('de', 'fr', 'it', 'en')
    );


COMMENT ON COLUMN cases.correspondence_language IS
    'Language for letters and emails generated for this case - the '
    'language of the authority it is addressed to, not of the user '
    'reading the screen. NULL means not chosen; the application falls '
    'back to the canton default and shows that it has done so.';
