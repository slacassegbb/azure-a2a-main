-- ============================================================================
-- AGENT RENAME MIGRATION
-- Date: 2026-03-02
-- Description: Rename 26 agents across all database tables
-- ============================================================================

BEGIN;

-- ============================================================================
-- STEP 0: Safety check — verify old names exist
-- ============================================================================
DO $$
DECLARE
    missing_agents TEXT[];
    old_names TEXT[] := ARRAY[
        'AI Foundry Stock Market Agent',
        'AI Foundry Time Series Agent',
        'AI Foundry Branding & Content Agent',
        'AI Foundry Classification Triage Agent',
        'AI Foundry Image Generator Agent',
        'Email Agent',
        'Teams Agent',
        'AI Foundry PowerPoint Agent',
        'Sora 2 Video Generator',
        'Twilio SMS Agent',
        'AI Foundry Assessment & Estimation Agent',
        'AI Foundry Claims Specialist Agent',
        'AI Foundry Deep Search Knowledge Agent',
        'AI Foundry Excel Agent',
        'AI Foundry Fraud Intelligence Agent',
        'AI Foundry Google Maps Agent',
        'AI Foundry HubSpot Agent',
        'AI Foundry Image Analysis Agent',
        'AI Foundry QuickBooks Agent',
        'AI Foundry Reporter Agent',
        'AI Foundry Stripe Agent',
        'AI Foundry Word Agent',
        'Legal Compliance & Regulatory Agent',
        'Salesforce CRM Agent',
        'AI Foundry Music Agent',
        'AI Foundry Video & Audio Agent'
    ];
    agent_name TEXT;
BEGIN
    missing_agents := ARRAY[]::TEXT[];
    FOREACH agent_name IN ARRAY old_names LOOP
        IF NOT EXISTS (SELECT 1 FROM agents WHERE name = agent_name) THEN
            missing_agents := array_append(missing_agents, agent_name);
        END IF;
    END LOOP;

    IF array_length(missing_agents, 1) > 0 THEN
        RAISE NOTICE 'WARNING: These agents were NOT found in agents table: %', missing_agents;
    ELSE
        RAISE NOTICE 'All 26 old agent names verified in agents table.';
    END IF;
END $$;

-- ============================================================================
-- STEP 1: Drop FK constraint on user_agent_configs (no ON UPDATE CASCADE)
-- ============================================================================
DO $$
DECLARE
    fk_name TEXT;
BEGIN
    SELECT conname INTO fk_name
    FROM pg_constraint
    WHERE conrelid = 'user_agent_configs'::regclass
      AND confrelid = 'agents'::regclass
      AND contype = 'f'
    LIMIT 1;

    IF fk_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE user_agent_configs DROP CONSTRAINT %I', fk_name);
        RAISE NOTICE 'Dropped FK constraint: %', fk_name;
    ELSE
        RAISE NOTICE 'No FK constraint found (may already be dropped).';
    END IF;
END $$;

-- ============================================================================
-- STEP 2: Rename agents in the agents table
-- ============================================================================
UPDATE agents SET name = 'Stock Market Analysis Agent'             WHERE name = 'AI Foundry Stock Market Agent';
UPDATE agents SET name = 'Forecasting and Anomaly Detection Agent' WHERE name = 'AI Foundry Time Series Agent';
UPDATE agents SET name = 'Branding Agent'                          WHERE name = 'AI Foundry Branding & Content Agent';
UPDATE agents SET name = 'Classification and Triage Agent'         WHERE name = 'AI Foundry Classification Triage Agent';
UPDATE agents SET name = 'Image Generator Agent'                   WHERE name = 'AI Foundry Image Generator Agent';
UPDATE agents SET name = 'Microsoft Outlook Agent'                 WHERE name = 'Email Agent';
UPDATE agents SET name = 'Microsoft Teams Agent'                   WHERE name = 'Teams Agent';
UPDATE agents SET name = 'Microsoft PowerPoint Agent'              WHERE name = 'AI Foundry PowerPoint Agent';
UPDATE agents SET name = 'Video Generator Agent'                   WHERE name = 'Sora 2 Video Generator';
UPDATE agents SET name = 'Text Message Agent'                      WHERE name = 'Twilio SMS Agent';
UPDATE agents SET name = 'Assessment and Estimation Agent'         WHERE name = 'AI Foundry Assessment & Estimation Agent';
UPDATE agents SET name = 'Claims Agent'                            WHERE name = 'AI Foundry Claims Specialist Agent';
UPDATE agents SET name = 'Deep Search Agent'                       WHERE name = 'AI Foundry Deep Search Knowledge Agent';
UPDATE agents SET name = 'Microsoft Excel Agent'                   WHERE name = 'AI Foundry Excel Agent';
UPDATE agents SET name = 'Fraud Intelligence Agent'                WHERE name = 'AI Foundry Fraud Intelligence Agent';
UPDATE agents SET name = 'Google Maps Agent'                       WHERE name = 'AI Foundry Google Maps Agent';
UPDATE agents SET name = 'HubSpot Agent'                           WHERE name = 'AI Foundry HubSpot Agent';
UPDATE agents SET name = 'Image Analysis Agent'                    WHERE name = 'AI Foundry Image Analysis Agent';
UPDATE agents SET name = 'QuickBooks Agent'                        WHERE name = 'AI Foundry QuickBooks Agent';
UPDATE agents SET name = 'Report Generator Agent'                  WHERE name = 'AI Foundry Reporter Agent';
UPDATE agents SET name = 'Stripe Agent'                            WHERE name = 'AI Foundry Stripe Agent';
UPDATE agents SET name = 'Microsoft Word Agent'                    WHERE name = 'AI Foundry Word Agent';
UPDATE agents SET name = 'Legal Agent'                             WHERE name = 'Legal Compliance & Regulatory Agent';
UPDATE agents SET name = 'Salesforce Agent'                        WHERE name = 'Salesforce CRM Agent';
UPDATE agents SET name = 'Music Generator Agent'                   WHERE name = 'AI Foundry Music Agent';
UPDATE agents SET name = 'Video and Audio Editing Agent'           WHERE name = 'AI Foundry Video & Audio Agent';

-- ============================================================================
-- STEP 3: Rename in user_agent_configs
-- ============================================================================
UPDATE user_agent_configs SET agent_name = 'Stock Market Analysis Agent'             WHERE agent_name = 'AI Foundry Stock Market Agent';
UPDATE user_agent_configs SET agent_name = 'Forecasting and Anomaly Detection Agent' WHERE agent_name = 'AI Foundry Time Series Agent';
UPDATE user_agent_configs SET agent_name = 'Branding Agent'                          WHERE agent_name = 'AI Foundry Branding & Content Agent';
UPDATE user_agent_configs SET agent_name = 'Classification and Triage Agent'         WHERE agent_name = 'AI Foundry Classification Triage Agent';
UPDATE user_agent_configs SET agent_name = 'Image Generator Agent'                   WHERE agent_name = 'AI Foundry Image Generator Agent';
UPDATE user_agent_configs SET agent_name = 'Microsoft Outlook Agent'                 WHERE agent_name = 'Email Agent';
UPDATE user_agent_configs SET agent_name = 'Microsoft Teams Agent'                   WHERE agent_name = 'Teams Agent';
UPDATE user_agent_configs SET agent_name = 'Microsoft PowerPoint Agent'              WHERE agent_name = 'AI Foundry PowerPoint Agent';
UPDATE user_agent_configs SET agent_name = 'Video Generator Agent'                   WHERE agent_name = 'Sora 2 Video Generator';
UPDATE user_agent_configs SET agent_name = 'Text Message Agent'                      WHERE agent_name = 'Twilio SMS Agent';
UPDATE user_agent_configs SET agent_name = 'Assessment and Estimation Agent'         WHERE agent_name = 'AI Foundry Assessment & Estimation Agent';
UPDATE user_agent_configs SET agent_name = 'Claims Agent'                            WHERE agent_name = 'AI Foundry Claims Specialist Agent';
UPDATE user_agent_configs SET agent_name = 'Deep Search Agent'                       WHERE agent_name = 'AI Foundry Deep Search Knowledge Agent';
UPDATE user_agent_configs SET agent_name = 'Microsoft Excel Agent'                   WHERE agent_name = 'AI Foundry Excel Agent';
UPDATE user_agent_configs SET agent_name = 'Fraud Intelligence Agent'                WHERE agent_name = 'AI Foundry Fraud Intelligence Agent';
UPDATE user_agent_configs SET agent_name = 'Google Maps Agent'                       WHERE agent_name = 'AI Foundry Google Maps Agent';
UPDATE user_agent_configs SET agent_name = 'HubSpot Agent'                           WHERE agent_name = 'AI Foundry HubSpot Agent';
UPDATE user_agent_configs SET agent_name = 'Image Analysis Agent'                    WHERE agent_name = 'AI Foundry Image Analysis Agent';
UPDATE user_agent_configs SET agent_name = 'QuickBooks Agent'                        WHERE agent_name = 'AI Foundry QuickBooks Agent';
UPDATE user_agent_configs SET agent_name = 'Report Generator Agent'                  WHERE agent_name = 'AI Foundry Reporter Agent';
UPDATE user_agent_configs SET agent_name = 'Stripe Agent'                            WHERE agent_name = 'AI Foundry Stripe Agent';
UPDATE user_agent_configs SET agent_name = 'Microsoft Word Agent'                    WHERE agent_name = 'AI Foundry Word Agent';
UPDATE user_agent_configs SET agent_name = 'Legal Agent'                             WHERE agent_name = 'Legal Compliance & Regulatory Agent';
UPDATE user_agent_configs SET agent_name = 'Salesforce Agent'                        WHERE agent_name = 'Salesforce CRM Agent';
UPDATE user_agent_configs SET agent_name = 'Music Generator Agent'                   WHERE agent_name = 'AI Foundry Music Agent';
UPDATE user_agent_configs SET agent_name = 'Video and Audio Editing Agent'           WHERE agent_name = 'AI Foundry Video & Audio Agent';

-- ============================================================================
-- STEP 4: Re-add FK with ON UPDATE CASCADE
-- ============================================================================
ALTER TABLE user_agent_configs
    ADD CONSTRAINT user_agent_configs_agent_name_fkey
    FOREIGN KEY (agent_name) REFERENCES agents(name)
    ON DELETE CASCADE
    ON UPDATE CASCADE;

-- ============================================================================
-- STEP 5: Helper function for JSONB renames
-- ============================================================================
CREATE OR REPLACE FUNCTION _rename_agent(old_val TEXT) RETURNS TEXT AS $$
DECLARE
    result TEXT := old_val;
BEGIN
    result := REPLACE(result, 'AI Foundry Stock Market Agent',            'Stock Market Analysis Agent');
    result := REPLACE(result, 'AI Foundry Time Series Agent',            'Forecasting and Anomaly Detection Agent');
    result := REPLACE(result, 'AI Foundry Branding & Content Agent',     'Branding Agent');
    result := REPLACE(result, 'AI Foundry Classification Triage Agent',  'Classification and Triage Agent');
    result := REPLACE(result, 'AI Foundry Image Generator Agent',        'Image Generator Agent');
    result := REPLACE(result, 'AI Foundry PowerPoint Agent',             'Microsoft PowerPoint Agent');
    result := REPLACE(result, 'AI Foundry Assessment & Estimation Agent','Assessment and Estimation Agent');
    result := REPLACE(result, 'AI Foundry Claims Specialist Agent',      'Claims Agent');
    result := REPLACE(result, 'AI Foundry Deep Search Knowledge Agent',  'Deep Search Agent');
    result := REPLACE(result, 'AI Foundry Excel Agent',                  'Microsoft Excel Agent');
    result := REPLACE(result, 'AI Foundry Fraud Intelligence Agent',     'Fraud Intelligence Agent');
    result := REPLACE(result, 'AI Foundry Google Maps Agent',            'Google Maps Agent');
    result := REPLACE(result, 'AI Foundry HubSpot Agent',               'HubSpot Agent');
    result := REPLACE(result, 'AI Foundry Image Analysis Agent',         'Image Analysis Agent');
    result := REPLACE(result, 'AI Foundry QuickBooks Agent',             'QuickBooks Agent');
    result := REPLACE(result, 'AI Foundry Reporter Agent',               'Report Generator Agent');
    result := REPLACE(result, 'AI Foundry Stripe Agent',                 'Stripe Agent');
    result := REPLACE(result, 'AI Foundry Word Agent',                   'Microsoft Word Agent');
    result := REPLACE(result, 'AI Foundry Music Agent',                  'Music Generator Agent');
    result := REPLACE(result, 'AI Foundry Video & Audio Agent',          'Video and Audio Editing Agent');
    result := REPLACE(result, 'Legal Compliance & Regulatory Agent',     'Legal Agent');
    result := REPLACE(result, 'Salesforce CRM Agent',                    'Salesforce Agent');
    result := REPLACE(result, 'Sora 2 Video Generator',                  'Video Generator Agent');
    result := REPLACE(result, 'Twilio SMS Agent',                         'Text Message Agent');
    result := REPLACE(result, 'Email Agent',                              'Microsoft Outlook Agent');
    result := REPLACE(result, 'Teams Agent',                              'Microsoft Teams Agent');
    RETURN result;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- STEP 6: Update workflows.steps JSONB (agentName field)
-- ============================================================================
UPDATE workflows
SET steps = (
    SELECT jsonb_agg(
        CASE
            WHEN step->>'agentName' IS NOT NULL
            THEN jsonb_set(step, '{agentName}', to_jsonb(_rename_agent(step->>'agentName')))
            ELSE step
        END
        ORDER BY ordinality
    )
    FROM jsonb_array_elements(steps) WITH ORDINALITY AS t(step, ordinality)
)
WHERE steps IS NOT NULL
  AND steps::text LIKE '%Agent%';

-- ============================================================================
-- STEP 7: Update active_workflows_multi.workflow_data JSONB
-- ============================================================================
UPDATE active_workflows_multi
SET workflow_data = (
    SELECT jsonb_set(
        workflow_data,
        '{steps}',
        COALESCE(
            (SELECT jsonb_agg(
                CASE
                    WHEN step->>'agentName' IS NOT NULL
                    THEN jsonb_set(step, '{agentName}', to_jsonb(_rename_agent(step->>'agentName')))
                    ELSE step
                END
                ORDER BY ordinality
            )
            FROM jsonb_array_elements(workflow_data->'steps') WITH ORDINALITY AS t(step, ordinality)),
            '[]'::jsonb
        )
    )
)
WHERE workflow_data IS NOT NULL
  AND workflow_data->'steps' IS NOT NULL
  AND workflow_data::text LIKE '%Agent%';

-- ============================================================================
-- STEP 8: Update agent_files.source_agent
-- ============================================================================
UPDATE agent_files SET source_agent = 'Stock Market Analysis Agent'             WHERE source_agent = 'AI Foundry Stock Market Agent';
UPDATE agent_files SET source_agent = 'Forecasting and Anomaly Detection Agent' WHERE source_agent = 'AI Foundry Time Series Agent';
UPDATE agent_files SET source_agent = 'Branding Agent'                          WHERE source_agent = 'AI Foundry Branding & Content Agent';
UPDATE agent_files SET source_agent = 'Classification and Triage Agent'         WHERE source_agent = 'AI Foundry Classification Triage Agent';
UPDATE agent_files SET source_agent = 'Image Generator Agent'                   WHERE source_agent = 'AI Foundry Image Generator Agent';
UPDATE agent_files SET source_agent = 'Microsoft Outlook Agent'                 WHERE source_agent = 'Email Agent';
UPDATE agent_files SET source_agent = 'Microsoft Teams Agent'                   WHERE source_agent = 'Teams Agent';
UPDATE agent_files SET source_agent = 'Microsoft PowerPoint Agent'              WHERE source_agent = 'AI Foundry PowerPoint Agent';
UPDATE agent_files SET source_agent = 'Video Generator Agent'                   WHERE source_agent = 'Sora 2 Video Generator';
UPDATE agent_files SET source_agent = 'Text Message Agent'                      WHERE source_agent = 'Twilio SMS Agent';
UPDATE agent_files SET source_agent = 'Assessment and Estimation Agent'         WHERE source_agent = 'AI Foundry Assessment & Estimation Agent';
UPDATE agent_files SET source_agent = 'Claims Agent'                            WHERE source_agent = 'AI Foundry Claims Specialist Agent';
UPDATE agent_files SET source_agent = 'Deep Search Agent'                       WHERE source_agent = 'AI Foundry Deep Search Knowledge Agent';
UPDATE agent_files SET source_agent = 'Microsoft Excel Agent'                   WHERE source_agent = 'AI Foundry Excel Agent';
UPDATE agent_files SET source_agent = 'Fraud Intelligence Agent'                WHERE source_agent = 'AI Foundry Fraud Intelligence Agent';
UPDATE agent_files SET source_agent = 'Google Maps Agent'                       WHERE source_agent = 'AI Foundry Google Maps Agent';
UPDATE agent_files SET source_agent = 'HubSpot Agent'                           WHERE source_agent = 'AI Foundry HubSpot Agent';
UPDATE agent_files SET source_agent = 'Image Analysis Agent'                    WHERE source_agent = 'AI Foundry Image Analysis Agent';
UPDATE agent_files SET source_agent = 'QuickBooks Agent'                        WHERE source_agent = 'AI Foundry QuickBooks Agent';
UPDATE agent_files SET source_agent = 'Report Generator Agent'                  WHERE source_agent = 'AI Foundry Reporter Agent';
UPDATE agent_files SET source_agent = 'Stripe Agent'                            WHERE source_agent = 'AI Foundry Stripe Agent';
UPDATE agent_files SET source_agent = 'Microsoft Word Agent'                    WHERE source_agent = 'AI Foundry Word Agent';
UPDATE agent_files SET source_agent = 'Legal Agent'                             WHERE source_agent = 'Legal Compliance & Regulatory Agent';
UPDATE agent_files SET source_agent = 'Salesforce Agent'                        WHERE source_agent = 'Salesforce CRM Agent';
UPDATE agent_files SET source_agent = 'Music Generator Agent'                   WHERE source_agent = 'AI Foundry Music Agent';
UPDATE agent_files SET source_agent = 'Video and Audio Editing Agent'           WHERE source_agent = 'AI Foundry Video & Audio Agent';

-- ============================================================================
-- STEP 9: Update messages.metadata JSONB (agentName field)
-- ============================================================================
UPDATE messages
SET metadata = jsonb_set(metadata, '{agentName}', to_jsonb(_rename_agent(metadata->>'agentName')))
WHERE metadata IS NOT NULL
  AND metadata->>'agentName' IS NOT NULL
  AND metadata->>'agentName' IN (
    'AI Foundry Stock Market Agent', 'AI Foundry Time Series Agent',
    'AI Foundry Branding & Content Agent', 'AI Foundry Classification Triage Agent',
    'AI Foundry Image Generator Agent', 'Email Agent', 'Teams Agent',
    'AI Foundry PowerPoint Agent', 'Sora 2 Video Generator', 'Twilio SMS Agent',
    'AI Foundry Assessment & Estimation Agent', 'AI Foundry Claims Specialist Agent',
    'AI Foundry Deep Search Knowledge Agent', 'AI Foundry Excel Agent',
    'AI Foundry Fraud Intelligence Agent', 'AI Foundry Google Maps Agent',
    'AI Foundry HubSpot Agent', 'AI Foundry Image Analysis Agent',
    'AI Foundry QuickBooks Agent', 'AI Foundry Reporter Agent',
    'AI Foundry Stripe Agent', 'AI Foundry Word Agent',
    'Legal Compliance & Regulatory Agent', 'Salesforce CRM Agent',
    'AI Foundry Music Agent', 'AI Foundry Video & Audio Agent'
  );

-- ============================================================================
-- STEP 10: Clean up helper function
-- ============================================================================
DROP FUNCTION IF EXISTS _rename_agent(TEXT);

-- ============================================================================
-- STEP 11: Verification
-- ============================================================================
DO $$
DECLARE
    old_count INTEGER;
    new_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO old_count FROM agents WHERE name IN (
        'AI Foundry Stock Market Agent', 'AI Foundry Time Series Agent',
        'AI Foundry Branding & Content Agent', 'AI Foundry Classification Triage Agent',
        'AI Foundry Image Generator Agent', 'Email Agent', 'Teams Agent',
        'AI Foundry PowerPoint Agent', 'Sora 2 Video Generator', 'Twilio SMS Agent',
        'AI Foundry Assessment & Estimation Agent', 'AI Foundry Claims Specialist Agent',
        'AI Foundry Deep Search Knowledge Agent', 'AI Foundry Excel Agent',
        'AI Foundry Fraud Intelligence Agent', 'AI Foundry Google Maps Agent',
        'AI Foundry HubSpot Agent', 'AI Foundry Image Analysis Agent',
        'AI Foundry QuickBooks Agent', 'AI Foundry Reporter Agent',
        'AI Foundry Stripe Agent', 'AI Foundry Word Agent',
        'Legal Compliance & Regulatory Agent', 'Salesforce CRM Agent',
        'AI Foundry Music Agent', 'AI Foundry Video & Audio Agent'
    );

    SELECT COUNT(*) INTO new_count FROM agents WHERE name IN (
        'Stock Market Analysis Agent', 'Forecasting and Anomaly Detection Agent',
        'Branding Agent', 'Classification and Triage Agent',
        'Image Generator Agent', 'Microsoft Outlook Agent', 'Microsoft Teams Agent',
        'Microsoft PowerPoint Agent', 'Video Generator Agent', 'Text Message Agent',
        'Assessment and Estimation Agent', 'Claims Agent',
        'Deep Search Agent', 'Microsoft Excel Agent',
        'Fraud Intelligence Agent', 'Google Maps Agent',
        'HubSpot Agent', 'Image Analysis Agent',
        'QuickBooks Agent', 'Report Generator Agent',
        'Stripe Agent', 'Microsoft Word Agent',
        'Legal Agent', 'Salesforce Agent',
        'Music Generator Agent', 'Video and Audio Editing Agent'
    );

    RAISE NOTICE 'VERIFICATION: % old names remaining (should be 0), % new names found', old_count, new_count;
END $$;

COMMIT;
