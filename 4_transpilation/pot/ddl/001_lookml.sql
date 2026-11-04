-- POT transpilation: the LookML generated for one extraction run_id, and what could not be translated.
-- Reads extraction and rationalization tables; never rewrites them. Cleared and rewritten per run.

CREATE TABLE IF NOT EXISTS wf_xpl_runs (
    run_id         VARCHAR(32)   NOT NULL,
    model_name     VARCHAR(128)  NOT NULL,
    output_dir     VARCHAR(1024) NOT NULL,
    view_count     INT           NOT NULL,
    explore_count  INT           NOT NULL,
    field_count    INT           NOT NULL,
    gap_count      INT           NOT NULL,
    created_at     TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id)
);

CREATE TABLE IF NOT EXISTS wf_xpl_files (
    run_id          VARCHAR(32)   NOT NULL,
    relative_path   VARCHAR(512)  NOT NULL COMMENT 'Path under the LookML output directory',
    file_kind       VARCHAR(16)   NOT NULL COMMENT 'manifest | model | view',
    line_count      INT           NOT NULL,
    content_sha256  CHAR(64)      NOT NULL,
    PRIMARY KEY (run_id, relative_path)
);

CREATE TABLE IF NOT EXISTS wf_xpl_views (
    run_id          VARCHAR(32)   NOT NULL,
    view_name       VARCHAR(255)  NOT NULL,
    view_kind       VARCHAR(16)   NOT NULL COMMENT 'physical | derived | extension | parameters',
    source_name     VARCHAR(512)  NOT NULL COMMENT 'Server table, HOLD name, or procedure path',
    extends_view    VARCHAR(255)  NULL,
    file_id         INT           NULL,
    request_seq     INT           NULL,
    field_count     INT           NOT NULL,
    derived_sql     MEDIUMTEXT    NULL,
    PRIMARY KEY (run_id, view_name)
);

CREATE TABLE IF NOT EXISTS wf_xpl_fields (
    run_id          VARCHAR(32)   NOT NULL,
    view_name       VARCHAR(255)  NOT NULL,
    field_name      VARCHAR(255)  NOT NULL,
    field_kind      VARCHAR(16)   NOT NULL COMMENT 'dimension | measure | parameter',
    lookml_type     VARCHAR(32)   NOT NULL,
    label           VARCHAR(512)  NULL,
    hidden          TINYINT       NOT NULL,
    status          VARCHAR(16)   NOT NULL COMMENT 'translated | declared | inferred | gap',
    sql_text        MEDIUMTEXT    NULL,
    file_id         INT           NULL,
    request_seq     INT           NULL,
    field_seq       INT           NULL,
    webfocus_text   MEDIUMTEXT    NOT NULL,
    PRIMARY KEY (run_id, view_name, field_name)
);

CREATE TABLE IF NOT EXISTS wf_xpl_explores (
    run_id             VARCHAR(32)   NOT NULL,
    explore_name       VARCHAR(255)  NOT NULL,
    base_view          VARCHAR(255)  NOT NULL,
    file_id            INT           NULL,
    request_seq        INT           NULL,
    join_count         INT           NOT NULL,
    sql_always_where   MEDIUMTEXT    NULL,
    sql_always_having  MEDIUMTEXT    NULL,
    PRIMARY KEY (run_id, explore_name)
);

CREATE TABLE IF NOT EXISTS wf_xpl_joins (
    run_id          VARCHAR(32)   NOT NULL,
    explore_name    VARCHAR(255)  NOT NULL,
    join_seq        INT           NOT NULL,
    view_name       VARCHAR(255)  NOT NULL,
    join_type       VARCHAR(16)   NOT NULL,
    relationship    VARCHAR(16)   NOT NULL,
    sql_on          TEXT          NULL,
    webfocus_text   TEXT          NOT NULL,
    PRIMARY KEY (run_id, explore_name, join_seq)
);

CREATE TABLE IF NOT EXISTS wf_xpl_parameters (
    run_id          VARCHAR(32)   NOT NULL,
    file_id         INT           NOT NULL,
    variable_name   VARCHAR(256)  NOT NULL,
    view_name       VARCHAR(255)  NOT NULL,
    parameter_name  VARCHAR(255)  NOT NULL,
    lookml_type     VARCHAR(16)   NOT NULL,
    default_value   TEXT          NOT NULL,
    PRIMARY KEY (run_id, file_id, variable_name)
);

CREATE TABLE IF NOT EXISTS wf_xpl_gaps (
    run_id          VARCHAR(32)   NOT NULL,
    gap_seq         INT           NOT NULL,
    gap_code        VARCHAR(32)   NOT NULL COMMENT 'untranslatable_expression | untranslatable_filter | dynamic_request_line | dynamic_field_name | ...',
    severity        VARCHAR(8)    NOT NULL COMMENT 'info | warning',
    object_name     VARCHAR(512)  NOT NULL,
    file_id         INT           NULL,
    request_seq     INT           NULL,
    field_seq       INT           NULL,
    message         TEXT          NOT NULL,
    webfocus_text   MEDIUMTEXT    NOT NULL,
    PRIMARY KEY (run_id, gap_seq)
);
