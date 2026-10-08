"""Fixed research registries; no model-selected SQL or independent budget reset."""
TABLES={'population':'population_research_jobs','paper':'paper_research_jobs'}


def table(kind):
    if kind not in TABLES:raise ValueError('Known research origin required')
    return TABLES[kind]


def request_count(store):
    total=0
    for name in TABLES.values():
        if store.connection.execute("select 1 from sqlite_master where type='table' and name=?",(name,)).fetchone():
            total+=store.connection.execute('select count(*) from '+name).fetchone()[0]
    return total
