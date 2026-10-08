"""Bind reviewed executable population hypotheses to explicitly preregistered plans."""
import json
from .engine import canonical,fingerprint
from .experiments import register_family
from .population_routing import route
from .research import scheduler_lock
from .validation import now_ms


def register_experiment(store,request_id,plan_id,profile,*,kind='population'):
    with scheduler_lock(store):return _register_experiment(store,request_id,plan_id,profile,kind=kind)


def _register_experiment(store,request_id,plan_id,profile,*,kind='population'):
    from .research_jobs import table
    registry=table(kind)
    store.connection.execute('create table if not exists population_experiment_links '
        '(request_id text primary key,plan_id text unique not null,family_id text not null,'
        'contract_fingerprint text not null,created_ms integer not null)')
    store.connection.commit()
    contract=fingerprint({'request_id':request_id,'plan_id':plan_id,'profile':profile,**({'research_origin':kind} if kind!='population' else {})})
    prior=store.connection.execute('select * from population_experiment_links where request_id=?',(request_id,)).fetchone()
    if prior:
        if prior['contract_fingerprint']!=contract:raise ValueError('Existing experiment binding is immutable; use a new reviewed hypothesis')
        return {**dict(prior),'status':'already_registered','promotion_authorized':False}
    decision=route(store,request_id,kind=kind)
    if decision['state']!='prospective_plan_required':raise ValueError('Reviewed executable hypothesis without unresolved requirements required')
    job=store.connection.execute(f'select network,address,updated_ms,packet_json,result_json from {registry} where request_id=?',(request_id,)).fetchone()
    plan=store.connection.execute('select network,address,coin,created_ms,synthetic,plan_json from validation_plans where plan_id=?',(plan_id,)).fetchone()
    if not plan or plan['network']!=job['network'] or plan['address']!=job['address']:
        raise ValueError('New plan must preserve population account and network')
    data=json.loads(plan['plan_json']);packet=json.loads(job['packet_json'])
    hypothesis=json.loads(job['result_json'])['proposal']['hypothesis'];spec=hypothesis['executable_spec']
    if plan['coin']!=spec['market']:raise ValueError('Experiment market differs from hypothesis')
    from .population_compilation import validate_packet_compilation
    validate_packet_compilation(hypothesis,profile,packet,request_id)
    if profile.get('hypothesis_id')!=request_id:raise ValueError('Experiment profile must reference its reviewed hypothesis')
    if not plan['synthetic']:
        if plan['created_ms']<job['updated_ms'] or now_ms()>=data['comparison']['start_ms']:
            raise ValueError('Plan and family must be frozen after review and before future comparison')
        if data['exploration']['end_ms']<packet['available_ms']+1:
            raise ValueError('Exploration must cover all exposed packet information')
    # register_family is atomic and content-addressed. A crash between its
    # commit and this link can resume the same family, never another profile.
    expected=fingerprint({'plan_id':plan_id,'profile':profile,'base_spec':spec})
    existing=store.connection.execute("select 1 from sqlite_master where name='experiment_families'").fetchone()
    if existing:
        other=store.connection.execute('select family_id from experiment_families where plan_id=? and family_id!=?',(plan_id,expected)).fetchone()
        if other:raise ValueError('Plan already belongs to a different experiment family')
    result=register_family(store,plan_id,profile,spec)
    store.connection.execute('insert into population_experiment_links values(?,?,?,?,?)',
        (request_id,plan_id,result['family_id'],contract,now_ms()));store.connection.commit()
    return {'status':'registered',**result,'request_id':request_id,'promotion_authorized':False}
