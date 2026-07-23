-- Migration 041: Backfill imported_identities from external_identities for
-- legacy messenger imports that predate the imported_identities table.
--
-- external_identities was populated by the original importer and holds one row
-- per (provider, external_name). We create a matching imported_identities row
-- for every messenger external_identity that doesn't already have one, then
-- backfill message counts and date ranges from the messages table.

INSERT INTO imported_identities (
    id,
    source,
    source_display_name,
    normalised_name,
    linked_user_id,
    status,
    message_count,
    first_seen_at,
    last_seen_at,
    created_at,
    updated_at
)
SELECT
    gen_random_uuid()                        AS id,
    ei.provider                              AS source,
    ei.external_name                         AS source_display_name,
    lower(trim(ei.external_name))            AS normalised_name,
    ei.user_id                               AS linked_user_id,
    CASE WHEN ei.user_id IS NOT NULL THEN 'linked' ELSE 'unlinked' END AS status,
    COALESCE(msg_stats.message_count, 0)     AS message_count,
    msg_stats.first_seen_at,
    msg_stats.last_seen_at,
    ei.created_at,
    NOW()                                    AS updated_at
FROM external_identities ei
LEFT JOIN (
    SELECT
        u.id AS user_id,
        COUNT(m.id)    AS message_count,
        MIN(m.created_at) AS first_seen_at,
        MAX(m.created_at) AS last_seen_at
    FROM users u
    JOIN messages m ON m.user_id = u.id AND m.is_imported = true
    GROUP BY u.id
) msg_stats ON msg_stats.user_id = ei.user_id
WHERE ei.provider IN ('messenger', 'facebook_messenger')
  AND NOT EXISTS (
    SELECT 1
    FROM imported_identities ii
    WHERE ii.source = ei.provider
      AND lower(trim(ii.normalised_name)) = lower(trim(ei.external_name))
  );
