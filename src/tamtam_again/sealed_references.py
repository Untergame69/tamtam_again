"""Lossless short notation for SHA-256 archive references in sealed packets."""
from copy import deepcopy
import base64
import re
from .engine import fingerprint

VERSION='raw-sha256-base85-v1'
RAW=re.compile(r'raw_observations:([0-9]+)#sha256:([a-f0-9]{64})\Z')
SHORT=re.compile(r'raw85:([0-9]+):(.{40})\Z')
RANGE_VERSION='sealed-root-reference-ranges-v1'


def section_reference_indices(section,pool_size):
    indices=section.get('evidence_ref_indices');runs=section.get('evidence_ref_runs')
    if indices is not None and runs is not None:raise ValueError('Only one reference index representation permitted')
    if runs is not None:
        if (section.get('reference_projection',{}).get('version')!=RANGE_VERSION
                or not isinstance(runs,list) or not runs):raise ValueError('Versioned reference runs required')
        indices=[]
        for run in runs:
            if (not isinstance(run,list) or len(run)!=2 or any(type(i) is not int for i in run)
                    or run[0]<0 or run[1]<1 or run[0]+run[1]>pool_size
                    or len(indices)+run[1]>100000):raise ValueError('Reference range bound exceeded')
            indices.extend(range(run[0],run[0]+run[1]))
    if (not isinstance(indices,list) or not indices or len(indices)>100000
            or any(type(i) is not int or not 0<=i<pool_size for i in indices)):
        raise ValueError('Bounded reference indices required')
    return indices


def compact_section_reference_indices(section):
    indices=section.get('evidence_ref_indices')
    projection=section.get('reference_projection',{})
    if (not isinstance(indices,list) or not indices
            or projection.get('version')!='sealed-root-reference-indices-v1'):return
    runs=[]
    for index in indices:
        if type(index) is not int or index<0:raise ValueError('Nonnegative reference indices required')
        if runs and index==runs[-1][0]+runs[-1][1]:runs[-1][1]+=1
        else:runs.append([index,1])
    from .engine import canonical
    if len(canonical(runs))>=len(canonical(indices)):return
    section.pop('evidence_ref_indices');section['evidence_ref_runs']=runs
    projection['version']=RANGE_VERSION
    projection['note']='Every original reference index retained in order as [start, count] runs into the expanded sealed root pool.'


def expand_reference(reference):
    if not isinstance(reference,str):raise ValueError('String evidence reference required')
    if not reference.startswith('raw85:'):return reference
    match=SHORT.fullmatch(reference)
    if match is None:raise ValueError('Invalid compact archive reference')
    try:raw=base64.b85decode(match[2].encode('ascii'))
    except (ValueError,UnicodeError) as exc:raise ValueError('Invalid SHA-256 base85 reference') from exc
    if len(raw)!=32 or base64.b85encode(raw).decode('ascii')!=match[2]:
        raise ValueError('Canonical 32-byte SHA-256 reference required')
    return 'raw_observations:'+match[1]+'#sha256:'+raw.hex()


def expanded_evidence_refs(packet):
    if 'model_packet_view' in packet:raise ValueError('Model packet views cannot be used as sealed sources')
    pool=packet.get('evidence_refs',[])
    if not isinstance(pool,list) or any(not isinstance(ref,str) for ref in pool):
        raise ValueError('Ordered string evidence pool required')
    if any(ref.startswith('proof_ref:') for ref in pool):raise ValueError('Model aliases cannot form a sealed evidence pool')
    projection=packet.get('evidence_reference_projection')
    if projection is None:
        if any(ref.startswith('raw85:') for ref in pool):raise ValueError('Compact references require a sealed projection header')
        return pool
    if not isinstance(projection,dict) or projection.get('version')!=VERSION:
        raise ValueError('Unsupported sealed reference projection')
    original=[expand_reference(ref) for ref in pool]
    if (projection.get('reference_count')!=len(original)
            or projection.get('ordered_source_fingerprint')!=fingerprint(original)):
        raise ValueError('Sealed reference projection fingerprint mismatch')
    return original


def compact_evidence_refs(packet):
    original=expanded_evidence_refs(packet)
    pool=[]
    for ref in original:
        match=RAW.fullmatch(ref)
        pool.append('raw85:'+match[1]+':'+base64.b85encode(bytes.fromhex(match[2])).decode('ascii') if match else ref)
    if pool==original:return
    packet['evidence_refs']=pool
    packet['evidence_reference_projection']={'version':VERSION,'reference_count':len(original),
        'ordered_source_fingerprint':fingerprint(original),
        'meaning':'raw85:<observation_id>:<base85 SHA-256, all 32 bytes retained>; indices resolve to the expanded original reference pool.'}


MODEL_VIEW_VERSION='ordered-evidence-alias-view-v1'
ALIAS=re.compile(r'proof_ref:(0|[1-9][0-9]*)\Z')
MODEL_REFERENCE_INSTRUCTIONS = ('packet.evidence_refs contains proof_ref:<index> display aliases, '
    'one for each inline sealed reference in exactly the same order. Cite these exact aliases '
    'in hypothesis.evidence_refs or experiment_profile.axes[*].evidence_refs; runtime binds them '
    'to the original immutable source before validation. Literal original references and admitted '
    'section paths remain valid. Existing evidence_ref_indices, evidence_ref_runs [start,count] and reference_projection fingerprints '
    'describe the ORIGINAL expanded source pool named by reference_pool, never hashes of display aliases. If evidence_source_manifest is supplied, section indices/runs address that full archived pool and its count/hash; cite an admitted section path or the exact source_reference for bulk history. All selected-market observations are inline; the model cannot read the archive. '
    'The model_packet_view header identifies a display view, not a new sealed source.')


def model_packet_view(packet):
    """Display every observation unchanged, shortening only the root proof pool."""
    original=expanded_evidence_refs(packet)
    view=deepcopy(packet)
    claimed=view.pop('fingerprint',None)
    view['evidence_refs']=['proof_ref:'+str(index) for index in range(len(original))]
    view['model_packet_view']={'version':MODEL_VIEW_VERSION,
        'source_body_fingerprint':fingerprint(packet),
        'source_sealed_fingerprint':claimed,'reference_count':len(original),
        'ordered_source_reference_fingerprint':fingerprint(original),
        'meaning':'Display aliases address the unchanged original expanded source pool in order; all existing index/projection fingerprints remain source-oriented.'}
    return view


def bind_model_evidence_refs(response,packet):
    """Bind aliases only at finite evidence-list locations, preserving the source."""
    pool=expanded_evidence_refs(packet)
    resolved=deepcopy(response);bindings=[]
    if not isinstance(resolved,dict):return resolved,bindings
    locations=[('evidence_refs',resolved)]
    hypothesis=resolved.get('hypothesis')
    if isinstance(hypothesis,dict):
        locations.append(('hypothesis.evidence_refs',hypothesis))
        profile=hypothesis.get('experiment_profile')
        axes=profile.get('axes') if isinstance(profile,dict) else None
        if isinstance(axes,list):
            locations.extend(('hypothesis.experiment_profile.axes['+str(index)+'].evidence_refs',axis)
                for index,axis in enumerate(axes) if isinstance(axis,dict))
    for path,owner in locations:
        refs=owner.get('evidence_refs')
        if not isinstance(refs,list):continue
        for index,ref in enumerate(refs):
            if not isinstance(ref,str) or not ref.startswith('proof_ref:'):continue
            match=ALIAS.fullmatch(ref)
            if match is None or int(match[1])>=len(pool):
                raise ValueError('Canonical in-range model evidence alias required')
            source_index=int(match[1]);refs[index]=pool[source_index]
            bindings.append({'field':path+'['+str(index)+']','alias':ref,
                'source_index':source_index,'reference':pool[source_index]})
    if bindings:
        body=deepcopy(packet);claimed=body.pop('fingerprint',None)
        if claimed is not None and claimed!=fingerprint(body):
            raise ValueError('Model evidence aliases require an unchanged sealed packet')
        return resolved,[{'version':MODEL_VIEW_VERSION,'source_body_fingerprint':fingerprint(packet),
            'ordered_source_reference_fingerprint':fingerprint(pool),'reference_count':len(pool),
            'bindings':bindings}]
    return resolved,[]


MANIFEST_VERSION='archived-ordered-evidence-pool-v1'


def compact_reference_manifest(packet, source_packet, source_fingerprint):
    """Replace only bulk root proofs; their exact source remains in the existing archive."""
    from .engine import canonical
    pool=expanded_evidence_refs(source_packet)
    if source_fingerprint!=fingerprint(source_packet):raise ValueError('Exact archived source required')
    source_ref='continuous_research_projections:'+source_fingerprint
    observations=packet.get('observations',{})
    sections=[(observations.get('descriptive_history_v1'),'summary_fingerprint')]
    sections.extend((section,'detail_fingerprint') for section in observations.get('market_execution_detail_v1',{}).values())
    positions={ref:index for index,ref in enumerate(pool)}
    for section,field in sections:
        if not isinstance(section,dict):continue
        refs=section.get('evidence_refs')
        if isinstance(refs,list) and refs and all(ref in positions for ref in refs):
            section['evidence_ref_indices']=[positions[ref] for ref in refs]
            section.pop('evidence_refs')
            section['reference_projection']={'version':'sealed-root-reference-indices-v1',
                'reference_pool':'packet.evidence_refs','reference_count':len(refs),
                'ordered_reference_fingerprint':fingerprint(refs)}
            compact_section_reference_indices(section)
    # Preserve every explicit nested reference (especially wake proof pages and
    # market rules), plus all descriptive/context scope references, in source order.
    explicit=set()
    def visit(value):
        if isinstance(value,str):explicit.add(value)
        elif isinstance(value,dict):
            for key,item in value.items():
                if key!='evidence_refs' or value is not packet:visit(item)
        elif isinstance(value,list):
            for item in value:visit(item)
    visit(packet)
    packet['evidence_refs']=[ref for ref in pool if not RAW.fullmatch(ref) or ref in explicit]+[source_ref]
    packet.pop('evidence_reference_projection',None)
    packet['evidence_source_manifest']={'version':MANIFEST_VERSION,'source_reference':source_ref,
        'source_fingerprint':source_fingerprint,'source_canonical_bytes':len(canonical(source_packet).encode()),
        'network':source_packet.get('network'),'address':source_packet.get('address'),
        'available_ms':source_packet.get('available_ms'),'reference_count':len(pool),
        'ordered_source_fingerprint':fingerprint(pool),'source_periods':_declared_source_periods(source_packet),
        'meaning':'Complete original ordered proof pool is losslessly stored in the existing source archive. Section indices/runs and hashes address that pool. All selected-market observations remain inline. Host verifies the archive before inference; model has no archive tools.'}
    for section,field in sections:
        if not isinstance(section,dict) or not isinstance(section.get('reference_projection'),dict):continue
        section['reference_projection']['reference_pool']=source_ref+'.evidence_refs'
        section.pop(field,None);section[field]=fingerprint(section)


def verified_manifest_pool(packet, source_pool=None):
    """Require an explicitly host-verified pool for archived section citations."""
    manifest=packet.get('evidence_source_manifest')
    if manifest is None:return expanded_evidence_refs(packet)
    if (not isinstance(manifest,dict) or manifest.get('version')!=MANIFEST_VERSION
            or not isinstance(source_pool,list) or any(not isinstance(ref,str) for ref in source_pool)
            or type(manifest.get('reference_count')) is not int
            or manifest.get('reference_count')!=len(source_pool)
            or manifest.get('ordered_source_fingerprint')!=fingerprint(source_pool)):
        raise ValueError('Verified archived ordered proof pool required')
    return source_pool


def _declared_source_periods(packet):
    """The finite inherited source union already carried by research packets."""
    from .engine import canonical
    periods=[]
    for field in ('source_periods','funding_witness_source_periods'):
        value=packet.get(field,[])
        if not isinstance(value,list):raise ValueError('Declared source period list required')
        periods.extend(value)
    for entry in packet.get('research_memory',[]):periods.extend(entry['item']['periods'])
    for entry in packet.get('research_evaluation_memory',[]):periods.extend(entry['periods'])
    unique={canonical(period):period for period in periods}
    return [deepcopy(unique[key]) for key in sorted(unique)]


def _authorize_manifest_periods(store,packet,manifest,blocked):
    from .research_memory import authorized_account_history,authorized_period
    declared=manifest.get('source_periods')
    if not isinstance(declared,list):raise ValueError('Archived source period union required')
    periods=declared+_declared_source_periods(packet)
    has_plans=store.connection.execute("select 1 from sqlite_master where name='validation_plans'").fetchone()
    for period in periods:
        # Source periods are half-open, while packet availability is inclusive.
        # The account guard at the exact cutoff prevents a release at +1ms
        # from granting access to a reservation active at the decision time.
        if (not isinstance(period,dict) or not {'network','address','market','start_ms','end_ms'}<=period.keys()
                or any(not isinstance(period[key],str) or not period[key] for key in ('network','address','market'))
                or type(period['start_ms']) is not int or type(period['end_ms']) is not int
                or not 0<=period['start_ms']<period['end_ms']<=packet['available_ms']+1
                or period['address'].lower() in blocked
                or not authorized_account_history(store,period['network'],period['address'].lower(),packet['available_ms'])
                or (has_plans and not authorized_period(store,period,packet['available_ms']+1))):
            raise ValueError('Archived inherited source period is reserved or unavailable')


def load_manifest_reference_pool(store,packet,*,frozen_plan_id=None,request_id=None,reviewed_ms=None):
    """Read the one authorized existing source archive, never from a model tool."""
    import gzip
    import io
    import json
    from .discovery import protected_addresses
    from .research_memory import authorized_account_history
    from .population_local_join import MAX_MARKET_DECODED_BYTES_PER_LOT
    manifest=packet.get('evidence_source_manifest')
    if manifest is None:return None
    if (not isinstance(manifest,dict) or manifest.get('version')!=MANIFEST_VERSION
            or re.fullmatch(r'[a-f0-9]{64}',str(manifest.get('source_fingerprint'))) is None
            or manifest.get('source_reference')!='continuous_research_projections:'+manifest['source_fingerprint']
            or manifest.get('source_reference') not in expanded_evidence_refs(packet)
            or manifest.get('network')!=packet.get('network')
            or str(manifest.get('address')).lower()!=str(packet.get('address')).lower()
            or type(manifest.get('available_ms')) is not int
            or type(packet.get('available_ms')) is not int
            or not 0<=manifest['available_ms']<=packet['available_ms']
            or type(manifest.get('source_canonical_bytes')) is not int
            or not 0<manifest['source_canonical_bytes']<=MAX_MARKET_DECODED_BYTES_PER_LOT):
        raise ValueError('Bounded same-scope archived reference manifest required')
    network,address,cutoff=manifest['network'],str(manifest['address']).lower(),manifest['available_ms']
    blocked=protected_addresses(store)
    if address in blocked and frozen_plan_id is not None:
        # Registration/recovery may reread only its already-exposed prefix.
        # A legacy or unrelated holdout can never obtain this exception.
        plan_row=store.connection.execute('select network,address,created_ms,plan_json from validation_plans where plan_id=?',
            (frozen_plan_id,)).fetchone()
        if plan_row:
            plan=json.loads(plan_row['plan_json'])
            others=store.connection.execute('select plan_id,plan_json from validation_plans where synthetic=0 and address=? and plan_id!=?',
                (address,frozen_plan_id)).fetchall()
            other=False
            import time
            clock=int(time.time()*1000)
            releases=store.connection.execute("select 1 from sqlite_master where name='research_window_releases'").fetchone()
            for candidate in others:
                if not releases or not json.loads(candidate['plan_json']).get('population_origin'):
                    other=True;break
                stages={row[0] for row in store.connection.execute('select stage from research_window_releases '
                    'where plan_id=? and released_ms<=?',(candidate['plan_id'],clock))}
                if stages!={'comparison','final'}:other=True;break
            if (not other and plan_row['network']==network and plan_row['address'].lower()==address
                    and request_id is not None and plan.get('population_origin',{}).get('request_id')==request_id
                    and type(reviewed_ms) is int and cutoff<=reviewed_ms<=plan_row['created_ms']
                    and packet['available_ms']<plan['comparison']['start_ms']):
                blocked=blocked-{address}
    if address in blocked or not authorized_account_history(store,network,address,cutoff):
        raise ValueError('Archived reference source is reserved or unauthorized')
    _authorize_manifest_periods(store,packet,manifest,blocked)
    row=store.connection.execute('select available_ms,length(body_gzip) from continuous_research_projections where source_fingerprint=?',
        (manifest['source_fingerprint'],)).fetchone()
    if not row or row[0]!=cutoff or not 0<row[1]<=MAX_MARKET_DECODED_BYTES_PER_LOT:
        raise ValueError('Archived reference source cutoff or size mismatch')
    body=store.connection.execute('select body_gzip from continuous_research_projections where source_fingerprint=?',
        (manifest['source_fingerprint'],)).fetchone()[0]
    with gzip.GzipFile(fileobj=io.BytesIO(body)) as archive:
        decoded=archive.read(manifest['source_canonical_bytes']+1)
    if len(decoded)!=manifest['source_canonical_bytes']:raise ValueError('Archived reference source size mismatch')
    source=json.loads(decoded)
    if (fingerprint(source)!=manifest['source_fingerprint'] or source.get('network')!=network
            or str(source.get('address')).lower()!=address or source.get('available_ms')!=cutoff):
        raise ValueError('Archived reference source identity mismatch')
    if manifest['source_periods']!=_declared_source_periods(source):
        raise ValueError('Archived source period union mismatch')
    pool=verified_manifest_pool(packet,expanded_evidence_refs(source))
    inline=expanded_evidence_refs(packet)
    if any(ref not in pool and ref!=manifest['source_reference'] for ref in inline):
        raise ValueError('Inline reference absent from verified archive')
    return pool
