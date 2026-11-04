-- Dialogue Manager assignments, variable uses, and branches.

CREATE TABLE IF NOT EXISTS wf_dm_assignments (
    run_id            VARCHAR(32)  NOT NULL,
    file_id           INT          NOT NULL,
    assignment_seq    INT          NOT NULL,
    statement_seq     INT          NOT NULL,
    line_number       INT          NOT NULL,
    command           VARCHAR(16)  NOT NULL COMMENT 'SET | DEFAULT | DEFAULTH | READ',
    variable_name     VARCHAR(256) NOT NULL,
    scope             VARCHAR(8)   NOT NULL COMMENT 'local (&) | global (&&)',
    expression_text   TEXT         NOT NULL,
    read_source       VARCHAR(256) NULL COMMENT 'Hold file read by -READ',
    PRIMARY KEY (run_id, file_id, assignment_seq),
    KEY idx_wf_dm_assignments_variable (run_id, variable_name)
);

CREATE TABLE IF NOT EXISTS wf_dm_references (
    run_id            VARCHAR(32)  NOT NULL,
    file_id           INT          NOT NULL,
    reference_seq     INT          NOT NULL,
    statement_seq     INT          NOT NULL,
    line_number       INT          NOT NULL,
    variable_name     VARCHAR(128) NOT NULL,
    scope             VARCHAR(8)   NOT NULL COMMENT 'local (&) | global (&&)',
    PRIMARY KEY (run_id, file_id, reference_seq),
    KEY idx_wf_dm_references_variable (run_id, variable_name)
);

CREATE TABLE IF NOT EXISTS wf_dm_control_flow (
    run_id            VARCHAR(32)  NOT NULL,
    file_id           INT          NOT NULL,
    control_seq       INT          NOT NULL,
    statement_seq     INT          NOT NULL,
    line_number       INT          NOT NULL,
    command           VARCHAR(8)   NOT NULL COMMENT 'IF | GOTO | REPEAT',
    condition_text    TEXT         NULL,
    target_label      VARCHAR(128) NULL,
    else_label        VARCHAR(128) NULL,
    PRIMARY KEY (run_id, file_id, control_seq)
);
