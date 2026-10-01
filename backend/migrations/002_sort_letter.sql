-- The A–Z rail needs per-letter counts; computing the letter per row made that
-- a full table scan. Store it as an indexed generated column instead.
--
-- Buckets follow the list's NOCASE sort order so they stay contiguous:
--   '#' names that sort before A (digits, punctuation)
--   'A'..'Z'
--   '~' names that sort after Z (accented and non-Latin first letters)
-- The API reports both '#' and '~' to the UI as '#'.
ALTER TABLE contacts ADD COLUMN sort_letter TEXT GENERATED ALWAYS AS (
    CASE WHEN lower(substr(sort_key, 1, 1)) < 'a' THEN '#'
         WHEN lower(substr(sort_key, 1, 1)) <= 'z' THEN upper(substr(sort_key, 1, 1))
         ELSE '~' END
) VIRTUAL;

CREATE INDEX idx_contacts_letter ON contacts (sort_letter);
