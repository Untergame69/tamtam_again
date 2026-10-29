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
                if 'status' not in columns:
                    # Minimal legacy registries cannot prove non-activation.
                    # Count every retained row rather than refund unknown work.
                    total+=store.connection.execute('select count(*) from paper_research_jobs').fetchone()[0]
                elif 'activated_ms' in columns:
                    total+=store.connection.execute("select count(*) from paper_research_jobs where activated_ms is not null or status in ('sealed','running','interrupted','suspended','failed','error','timeout','expired','hypothesis_recorded','needs_data','non_identifiable','unsupported_mechanism','reject')").fetchone()[0]
                else:
                    # Before activation timestamps existed, only non-archived
                    # states prove that a paper research attempt was engaged.
                    total+=store.connection.execute("select count(*) from paper_research_jobs where status not in ('budget_required','archived')").fetchone()[0]
            else:
                # Dedicated allowances retain every attempt in the same jobs
                # registry, but never consume or reset the historical shared
                # allowance. Schemas can appear independently during migration.
                exclusions=[]
                for dedicated in ('population_research_pilot_tasks','continuous_research_tasks'):
                    if store.connection.execute(
                            "select 1 from sqlite_master where type='table' and name=?",(dedicated,)).fetchone():
                        exclusions.append('not exists(select 1 from '+dedicated+' d where d.request_id=j.request_id)')
                query='select count(*) from population_research_jobs j'
                if exclusions:query+=' where '+' and '.join(exclusions)
                total+=store.connection.execute(query).fetchone()[0]
    return total
