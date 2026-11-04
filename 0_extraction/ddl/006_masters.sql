-- Master files (.mas): declared table shapes. Metadata only; master files hold no client data.

CREATE TABLE IF NOT EXISTS wf_master_files (
    run_id            VARCHAR(32)   NOT NULL,
    file_id           INT           NOT NULL,
    filename          VARCHAR(128)  NULL COMMENT 'FILENAME, upper case: the name requests use in TABLE FILE and JOIN',
    suffix            VARCHAR(16)   NULL COMMENT 'FOC | XFOC | SQLORA | DFIX | ...',
    dataset           VARCHAR(1024) NULL COMMENT 'DATASET: app-relative path of the data file',
    remarks           TEXT          NULL,
    file_attributes   TEXT          NULL COMMENT 'Other file attributes as KEY=VALUE lines',
    segment_count     INT           NOT NULL,
    field_count       INT           NOT NULL COMMENT 'Real fields',
    define_count      INT           NOT NULL COMMENT 'Virtual (DEFINE) fields',
    PRIMARY KEY (run_id, file_id),
    KEY idx_wf_master_files_filename (run_id, filename)
);

CREATE TABLE IF NOT EXISTS wf_master_segments (
    run_id            VARCHAR(32)   NOT NULL,
    file_id           INT           NOT NULL,
    segment_seq       INT           NOT NULL,
    segment_name      VARCHAR(128)  NOT NULL,
    segtype           VARCHAR(16)   NULL,
    parent_segment    VARCHAR(128)  NULL,
    line_number       INT           NOT NULL,
    other_attributes  TEXT          NULL COMMENT 'Other segment attributes as KEY=VALUE lines',
    PRIMARY KEY (run_id, file_id, segment_seq)
);

CREATE TABLE IF NOT EXISTS wf_master_fields (
    run_id            VARCHAR(32)   NOT NULL,
    file_id           INT           NOT NULL,
    field_seq         INT           NOT NULL,
    segment_seq       INT           NULL,
    field_kind        VARCHAR(8)    NOT NULL COMMENT 'field | define',
    field_name        VARCHAR(128)  NOT NULL,
    alias             VARCHAR(255)  NULL,
    usage_format      VARCHAR(32)   NULL COMMENT 'USAGE: display format, for example I8, D12.2, A40V, YYMD',
    actual_format     VARCHAR(32)   NULL COMMENT 'ACTUAL: stored format, when declared',
    missing           VARCHAR(8)    NULL COMMENT 'ON | OFF, when declared',
    title             VARCHAR(512)  NULL,
    description       TEXT          NULL,
    fieldtype         VARCHAR(8)    NULL COMMENT 'I marks an indexed field',
    expression_text   TEXT          NULL COMMENT 'DEFINE expression, NULL for real fields',
    other_attributes  TEXT          NULL COMMENT 'Other field attributes as KEY=VALUE lines',
    line_number       INT           NOT NULL,
    raw_text          TEXT          NOT NULL,
    PRIMARY KEY (run_id, file_id, field_seq),
    KEY idx_wf_master_fields_name (run_id, field_name)
);
