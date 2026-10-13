"""Fixed research registries; no model-selected SQL or independent budget reset."""
TABLES={'population':'population_research_jobs','paper':'paper_research_jobs'}


def table(kind):
    if kind not in TABLES:raise ValueError('Known research origin required')
    return TABLES[kind]


def request_count(store):
    total=0
    for kind,name in TABLES.items():
        if store.connection.execute("select 1 from sqlite_master where type='table' and name=?",(name,)).fetchone():
            # A deterministic, prepared paper handoff makes no inference and
            # does not reserve a shared model call. Count it only on activation.
            if kind=='paper':
                columns={r[1] for r in store.connection.execute('pragma table_info(paper_research_jobs)')}
                if 'activated_ms' in columns:
                    total+=store.connection.execute("select count(*) from paper_research_jobs where activated_ms is not null or status in ('sealed','running','interrupted','suspended','failed','error','timeout','expired','hypothesis_recorded','needs_data','non_identifiable','unsupported_mechanism','reject')").fetchone()[0]
                else:
                    # Before activation timestamps existed, only non-archived
                    # states prove that a paper research attempt was engaged.
                    total+=store.connection.execute("select count(*) from paper_research_jobs where status not in ('budget_required','archived')").fetchone()[0]
            else:
                total+=store.connection.execute('select count(*) from '+name).fetchone()[0]
    return total
