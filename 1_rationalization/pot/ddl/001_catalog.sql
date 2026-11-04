-- POT rationalization catalog. Reads extraction tables; never rewrites them.
-- Scoped by the extraction run_id. Cleared and rewritten on each rationalization run.

CREATE TABLE IF NOT EXISTS wf_rat_phase_results (
    run_id        VARCHAR(32)  NOT NULL,
    phase         VARCHAR(32)  NOT NULL,
    status        VARCHAR(16)  NOT NULL COMMENT 'noop | completed',
    object_count  INT          NOT NULL,
    reason        TEXT         NOT NULL,
    PRIMARY KEY (run_id, phase)
);

CREATE TABLE IF NOT EXISTS wf_rat_scope (
    run_id    VARCHAR(32)  NOT NULL,
    file_id   INT          NOT NULL,
    in_scope  TINYINT      NOT NULL,
    reason    VARCHAR(255) NOT NULL,
    PRIMARY KEY (run_id, file_id)
);

CREATE TABLE IF NOT EXISTS wf_rat_requests (
    run_id           VARCHAR(32) NOT NULL,
    file_id          INT         NOT NULL,
    request_seq      INT         NOT NULL,
    graph_role       VARCHAR(16) NOT NULL COMMENT 'source_read | hold_producer | define | match | function',
    carries_forward  TINYINT     NOT NULL,
    PRIMARY KEY (run_id, file_id, request_seq)
);

CREATE TABLE IF NOT EXISTS wf_rat_fields (
    run_id       VARCHAR(32) NOT NULL,
    file_id      INT         NOT NULL,
    request_seq  INT         NOT NULL,
    field_seq    INT         NOT NULL,
    logic_class  VARCHAR(16) NOT NULL COMMENT 'aggregate | detail | group_by | across | compute | define | parameter | unparsed',
    PRIMARY KEY (run_id, file_id, request_seq, field_seq)
);

CREATE TABLE IF NOT EXISTS wf_rat_lineage (
    run_id             VARCHAR(32)  NOT NULL,
    edge_seq           INT          NOT NULL,
    edge_kind          VARCHAR(16)  NOT NULL COMMENT 'hold_to_table | define_on | join_to_table | filedef | flat_file | master',
    name_role          VARCHAR(16)  NOT NULL COMMENT 'source | match | hold | join_from | join_to | filedef | flat_file',
    from_file_id       INT          NULL,
    from_request_seq   INT          NULL,
    to_file_id         INT          NULL,
    to_request_seq     INT          NULL,
    via_name_raw       VARCHAR(512) NOT NULL,
    via_name_resolved  VARCHAR(512) NULL,
    match_status       VARCHAR(16)  NOT NULL COMMENT 'resolved | unresolved',
    anchor_file_id     INT          NULL,
    anchor_seq         INT          NULL COMMENT 'join_seq or environment command_seq when the edge is anchored there',
    PRIMARY KEY (run_id, edge_seq)
);

CREATE TABLE IF NOT EXISTS wf_rat_gaps (
    run_id       VARCHAR(32) NOT NULL,
    gap_seq      INT         NOT NULL,
    file_id      INT         NULL,
    request_seq  INT         NULL,
    gap_code     VARCHAR(32) NOT NULL COMMENT 'unresolved_source | unresolved_hold | unresolved_join | unresolved_include | missing_master | duplicate_master | unparsed_field | inferred_layout',
    severity     VARCHAR(8)  NOT NULL COMMENT 'info | warning',
    message      TEXT        NOT NULL,
    PRIMARY KEY (run_id, gap_seq)
);
