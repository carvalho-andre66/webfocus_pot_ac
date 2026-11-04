-- Ordered statement stream per procedure file, and everything the parser could not handle.

CREATE TABLE IF NOT EXISTS wf_statements (
    run_id                VARCHAR(32)  NOT NULL,
    file_id               INT          NOT NULL,
    statement_seq         INT          NOT NULL COMMENT '1-based order within the file',
    parent_statement_seq  INT          NULL COMMENT 'Enclosing request for DM lines inside TABLE/DEFINE/MATCH blocks',
    statement_kind        VARCHAR(48)  NOT NULL,
    keyword               VARCHAR(64)  NULL COMMENT 'Leading command word(s), upper case',
    start_line            INT          NOT NULL,
    end_line              INT          NOT NULL,
    raw_text              MEDIUMTEXT   NOT NULL,
    PRIMARY KEY (run_id, file_id, statement_seq),
    KEY idx_wf_statements_kind (run_id, statement_kind)
);

CREATE TABLE IF NOT EXISTS wf_parse_issues (
    run_id            VARCHAR(32)  NOT NULL,
    file_id           INT          NOT NULL,
    issue_seq         INT          NOT NULL,
    line_number       INT          NULL,
    severity          VARCHAR(8)   NOT NULL COMMENT 'info | warning | error',
    issue_code        VARCHAR(64)  NOT NULL,
    message           TEXT         NOT NULL,
    PRIMARY KEY (run_id, file_id, issue_seq),
    KEY idx_wf_parse_issues_code (run_id, issue_code)
);
