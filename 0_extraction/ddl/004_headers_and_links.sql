-- Header comments, includes, and drill links.

CREATE TABLE IF NOT EXISTS wf_file_header_attributes (
    run_id            VARCHAR(32)  NOT NULL,
    file_id           INT          NOT NULL,
    attribute_seq     INT          NOT NULL,
    line_number       INT          NOT NULL,
    attribute_key     VARCHAR(64)  NOT NULL,
    attribute_value   TEXT         NOT NULL,
    PRIMARY KEY (run_id, file_id, attribute_seq)
);

CREATE TABLE IF NOT EXISTS wf_file_change_log (
    run_id            VARCHAR(32)  NOT NULL,
    file_id           INT          NOT NULL,
    change_seq        INT          NOT NULL,
    line_number       INT          NOT NULL,
    version           VARCHAR(32)  NOT NULL,
    change_date       VARCHAR(16)  NOT NULL,
    author            VARCHAR(128) NOT NULL,
    change_type       VARCHAR(16)  NOT NULL,
    description       TEXT         NOT NULL,
    PRIMARY KEY (run_id, file_id, change_seq)
);

CREATE TABLE IF NOT EXISTS wf_html_blocks (
    run_id            VARCHAR(32)  NOT NULL,
    file_id           INT          NOT NULL,
    statement_seq     INT          NOT NULL,
    start_line        INT          NOT NULL,
    end_line          INT          NOT NULL,
    raw_text          MEDIUMTEXT   NOT NULL,
    PRIMARY KEY (run_id, file_id, statement_seq)
);

CREATE TABLE IF NOT EXISTS wf_references (
    run_id            VARCHAR(32)   NOT NULL,
    file_id           INT           NOT NULL,
    reference_seq     INT           NOT NULL,
    statement_seq     INT           NOT NULL,
    line_number       INT           NOT NULL,
    reference_kind    VARCHAR(16)   NOT NULL COMMENT 'include | ibfs_link',
    target_raw        VARCHAR(1024) NOT NULL,
    target_path       VARCHAR(1024) NULL COMMENT 'Bundle-relative path when one could be parsed',
    in_bundle         TINYINT       NOT NULL COMMENT '1 when target_path matches a bundled file',
    PRIMARY KEY (run_id, file_id, reference_seq),
    KEY idx_wf_references_kind (run_id, reference_kind)
);
