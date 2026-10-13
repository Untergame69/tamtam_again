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
                total+=store.connection.execute("select count(*) from paper_research_jobs where status!='budget_required'").fetchone()[0]
            else:
                total+=store.connection.execute('select count(*) from '+name).fetchone()[0]
    return total
