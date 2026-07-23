-- Apply already-closed chat agenda nickname/role motions that passed.
--
-- Chat agenda poll cards derive "closed" from deadline_at at read time. Older
-- closed cards could show a Yes winner without updating the target member.

WITH vote_counts AS (
    SELECT
        po.poll_id,
        po.id AS option_id,
        lower(trim(po.label)) AS label,
        count(pv.id) AS votes
    FROM poll_options po
    LEFT JOIN poll_votes pv ON pv.option_id = po.id AND pv.poll_id = po.poll_id
    GROUP BY po.poll_id, po.id, lower(trim(po.label))
),
yes_winners AS (
    SELECT
        p.id AS poll_id,
        p.target_user_id,
        trim(p.proposed_nickname) AS proposed_nickname,
        vc.votes AS yes_votes
    FROM polls p
    JOIN vote_counts vc ON vc.poll_id = p.id AND vc.label = 'yes'
    WHERE p.source = 'chat_agenda'
      AND p.event_type = 'nickname_vote'
      AND p.target_user_id IS NOT NULL
      AND p.deadline_at IS NOT NULL
      AND p.deadline_at <= now()
      AND p.status IS DISTINCT FROM 'cancelled'
      AND vc.votes > 0
      AND NOT EXISTS (
          SELECT 1
          FROM vote_counts tied
          WHERE tied.poll_id = p.id
            AND tied.option_id <> vc.option_id
            AND tied.votes >= vc.votes
      )
      AND p.proposed_nickname IS NOT NULL
      AND length(trim(p.proposed_nickname)) BETWEEN 2 AND 50
      AND position(E'\n' in trim(p.proposed_nickname)) = 0
      AND position(E'\r' in trim(p.proposed_nickname)) = 0
      AND position(E'\t' in trim(p.proposed_nickname)) = 0
)
UPDATE users u
SET nickname = yw.proposed_nickname,
    updated_at = now()
FROM yes_winners yw
WHERE u.id = yw.target_user_id
  AND u.nickname IS DISTINCT FROM yw.proposed_nickname;

WITH vote_counts AS (
    SELECT
        po.poll_id,
        po.id AS option_id,
        lower(trim(po.label)) AS label,
        count(pv.id) AS votes
    FROM poll_options po
    LEFT JOIN poll_votes pv ON pv.option_id = po.id AND pv.poll_id = po.poll_id
    GROUP BY po.poll_id, po.id, lower(trim(po.label))
),
yes_winners AS (
    SELECT
        p.id AS poll_id,
        p.target_user_id,
        trim(p.proposed_role) AS proposed_role,
        vc.votes AS yes_votes
    FROM polls p
    JOIN vote_counts vc ON vc.poll_id = p.id AND vc.label = 'yes'
    WHERE p.source = 'chat_agenda'
      AND p.event_type = 'role_vote'
      AND p.target_user_id IS NOT NULL
      AND p.deadline_at IS NOT NULL
      AND p.deadline_at <= now()
      AND p.status IS DISTINCT FROM 'cancelled'
      AND vc.votes > 0
      AND NOT EXISTS (
          SELECT 1
          FROM vote_counts tied
          WHERE tied.poll_id = p.id
            AND tied.option_id <> vc.option_id
            AND tied.votes >= vc.votes
      )
      AND p.proposed_role IS NOT NULL
      AND length(trim(p.proposed_role)) BETWEEN 1 AND 64
      AND position(E'\n' in trim(p.proposed_role)) = 0
      AND position(E'\r' in trim(p.proposed_role)) = 0
      AND position(E'\t' in trim(p.proposed_role)) = 0
)
UPDATE users u
SET display_role = yw.proposed_role,
    updated_at = now()
FROM yes_winners yw
WHERE u.id = yw.target_user_id
  AND u.display_role IS DISTINCT FROM yw.proposed_role;

UPDATE polls
SET status = 'closed',
    updated_at = now()
WHERE source = 'chat_agenda'
  AND deadline_at IS NOT NULL
  AND deadline_at <= now()
  AND status IS DISTINCT FROM 'cancelled'
  AND status IS DISTINCT FROM 'closed';
