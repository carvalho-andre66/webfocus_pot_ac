-- Requests, defines, joins, and environment commands.
-- resolution_status: as_written | literal | inferred_from_default | unresolved

CREATE TABLE IF NOT EXISTS wf_requests (
    run_id                     VARCHAR(32)  NOT NULL,
    file_id                    INT          NOT NULL,
    request_seq                INT          NOT NULL,
    statement_seq              INT          NOT NULL,
    line_number                INT          NOT NULL,
    request_kind               VARCHAR(24)  NOT NULL COMMENT 'table | match | define_file | define_function',
    source_table_raw           VARCHAR(512) NOT NULL,
    source_table_resolved      VARCHAR(512) NOT NULL,
    source_resolution_status   VARCHAR(24)  NOT NULL,
    hold_name_raw              VARCHAR(512) NULL,
    hold_name_resolved         VARCHAR(512) NULL,
    hold_resolution_status     VARCHAR(24)  NULL,
    hold_format                VARCHAR(32)  NULL,
    match_file_raw             VARCHAR(512) NULL,
    match_file_resolved        VARCHAR(512) NULL,
    match_resolution_status    VARCHAR(24)  NULL,
    qualifier                  VARCHAR(16)  NULL COMMENT 'CLEAR for DEFINE FILE ... CLEAR',
    PRIMARY KEY (run_id, file_id, request_seq),
    KEY idx_wf_requests_kind (run_id, request_kind)
);

CREATE TABLE IF NOT EXISTS wf_request_fields (
    run_id            VARCHAR(32)  NOT NULL,
    file_id           INT          NOT NULL,
    request_seq       INT          NOT NULL,
    field_seq         INT          NOT NULL,
    side              VARCHAR(8)   NOT NULL COMMENT 'primary | match',
    role              VARCHAR(16)  NOT NULL COMMENT 'verb_field | by | across | compute | define | parameter | unparsed',
    verb              VARCHAR(8)   NULL COMMENT 'SUM | PRINT | COUNT | WRITE | LIST | ADD',
    field_name        VARCHAR(512) NOT NULL,
    field_format      VARCHAR(32)  NULL,
    alias             VARCHAR(256) NULL,
    expression_text   TEXT         NULL,
    modifiers         VARCHAR(64)  NULL,
    raw_text          TEXT         NOT NULL,
    PRIMARY KEY (run_id, file_id, request_seq, field_seq)
);

CREATE TABLE IF NOT EXISTS wf_request_filters (
    run_id            VARCHAR(32) NOT NULL,
    file_id           INT         NOT NULL,
    request_seq       INT         NOT NULL,
    filter_seq        INT         NOT NULL,
    side              VARCHAR(8)  NOT NULL COMMENT 'primary | match',
    filter_kind       VARCHAR(8)  NOT NULL COMMENT 'WHERE | IF | AND is folded into the previous clause | AMPER',
    expression_text   TEXT        NOT NULL,
    PRIMARY KEY (run_id, file_id, request_seq, filter_seq)
);

CREATE TABLE IF NOT EXISTS wf_joins (
    run_id                    VARCHAR(32)  NOT NULL,
    file_id                   INT          NOT NULL,
    join_seq                  INT          NOT NULL,
    statement_seq             INT          NOT NULL,
    line_number               INT          NOT NULL,
    join_action               VARCHAR(8)   NOT NULL COMMENT 'join | clear',
    join_type                 VARCHAR(16)  NULL COMMENT 'LEFT_OUTER | RIGHT_OUTER | INNER | ALL',
    multiplicity              VARCHAR(16)  NULL COMMENT 'MULTIPLE | UNIQUE',
    from_field                VARCHAR(128) NULL,
    from_table_raw            VARCHAR(512) NULL,
    from_table_resolved       VARCHAR(512) NULL,
    from_resolution_status    VARCHAR(24)  NULL,
    to_field                  VARCHAR(128) NULL,
    to_table_raw              VARCHAR(512) NULL,
    to_table_resolved         VARCHAR(512) NULL,
    to_resolution_status      VARCHAR(24)  NULL,
    join_name                 VARCHAR(64)  NULL,
    join_tag                  VARCHAR(64)  NULL,
    clear_target              VARCHAR(64)  NULL,
    PRIMARY KEY (run_id, file_id, join_seq)
);

CREATE TABLE IF NOT EXISTS wf_environment_commands (
    run_id            VARCHAR(32)  NOT NULL,
    file_id           INT          NOT NULL,
    command_seq       INT          NOT NULL,
    statement_seq     INT          NOT NULL,
    line_number       INT          NOT NULL,
    command_kind      VARCHAR(16)  NOT NULL COMMENT 'SET | FILEDEF | APP | ENGINE | STATE | SQL',
    name              VARCHAR(256) NULL,
    value_text        TEXT         NULL,
    raw_text          MEDIUMTEXT   NOT NULL,
    PRIMARY KEY (run_id, file_id, command_seq)
);
