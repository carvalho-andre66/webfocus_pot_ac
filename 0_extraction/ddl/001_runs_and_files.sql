-- Extraction runs and the files discovered in the WebFOCUS bundle.

CREATE TABLE IF NOT EXISTS wf_extraction_runs (
    run_id            VARCHAR(32)   NOT NULL,
    bundle_root       VARCHAR(1024) NOT NULL,
    parser_version    VARCHAR(32)   NOT NULL,
    status            VARCHAR(16)   NOT NULL COMMENT 'running | succeeded | failed',
    started_at        DATETIME(6)   NOT NULL,
    finished_at       DATETIME(6)   NULL,
    file_count        INT           NULL,
    statement_count   INT           NULL,
    issue_count       INT           NULL,
    error_message     TEXT          NULL,
    PRIMARY KEY (run_id)
);

CREATE TABLE IF NOT EXISTS wf_source_files (
    run_id            VARCHAR(32)   NOT NULL,
    file_id           INT           NOT NULL,
    relative_path     VARCHAR(1024) NOT NULL COMMENT 'Path under the bundle root',
    ibfs_path         VARCHAR(1024) NOT NULL COMMENT 'IBFS:/<relative_path>, as used by -INCLUDE and drill links',
    source_root       VARCHAR(16)   NOT NULL COMMENT 'WFC (client repository) | EDA (reporting server) | OTHER',
    file_kind         VARCHAR(32)   NOT NULL COMMENT 'procedure | master | access_file | flat_file | html | other',
    size_bytes        BIGINT        NOT NULL,
    line_count        INT           NOT NULL,
    sha256            CHAR(64)      NOT NULL,
    text_encoding     VARCHAR(16)   NOT NULL,
    raw_text          MEDIUMTEXT    NULL COMMENT 'NULL for flat files: client data is never staged',
    PRIMARY KEY (run_id, file_id),
    KEY idx_wf_source_files_ibfs_path (run_id, ibfs_path(255))
);

CREATE TABLE IF NOT EXISTS wf_flat_file_profiles (
    run_id            VARCHAR(32)   NOT NULL,
    file_id           INT           NOT NULL,
    row_count         INT           NOT NULL COMMENT 'Non-blank lines',
    column_count      INT           NOT NULL COMMENT 'Inferred: most common whitespace-separated token count',
    min_line_width    INT           NOT NULL,
    max_line_width    INT           NOT NULL,
    PRIMARY KEY (run_id, file_id)
);

CREATE TABLE IF NOT EXISTS wf_flat_file_columns (
    run_id            VARCHAR(32)   NOT NULL,
    file_id           INT           NOT NULL,
    column_position   INT           NOT NULL COMMENT '1-based',
    min_width         INT           NOT NULL,
    max_width         INT           NOT NULL,
    inferred_type     VARCHAR(16)   NOT NULL COMMENT 'integer | decimal | alpha (inferred from values, values not stored)',
    PRIMARY KEY (run_id, file_id, column_position)
);
