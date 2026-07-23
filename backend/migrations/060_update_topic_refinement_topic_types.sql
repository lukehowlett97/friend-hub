-- Migration 060: align refined topic types with the group-chat timeline taxonomy.

UPDATE chat_topics
SET topic_type = CASE
    WHEN topic_type IN ('argument', 'debate', 'politics', 'history', 'jokes', 'photos', 'other') THEN 'general_chat'
    WHEN topic_type = 'football' THEN 'sport'
    ELSE topic_type
END
WHERE topic_type IN ('argument', 'debate', 'politics', 'history', 'jokes', 'photos', 'other', 'football');

ALTER TABLE chat_topics
    DROP CONSTRAINT IF EXISTS ck_chat_topics_topic_type;

ALTER TABLE chat_topics
    ADD CONSTRAINT ck_chat_topics_topic_type
    CHECK (
        topic_type IS NULL
        OR topic_type IN (
            'general_chat',
            'planning',
            'event',
            'sport',
            'gaming',
            'food_drink',
            'music',
            'travel',
            'work',
            'relationship',
            'memory',
            'unknown'
        )
    );
