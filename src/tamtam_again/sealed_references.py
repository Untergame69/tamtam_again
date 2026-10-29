"""Lossless short notation for SHA-256 archive references in sealed packets."""
from copy import deepcopy
import base64
import re
from .engine import fingerprint

VERSION='raw-sha256-base85-v1'
RAW=re.compile(r'raw_observations:([0-9]+)#sha256:([a-f0-9]{64})\Z')
SHORT=re.compile(r'raw85:([0-9]+):(.{40})\Z')


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
    'one for each original expanded sealed reference in exactly the same order. Cite these exact aliases '
    'in hypothesis.evidence_refs or experiment_profile.axes[*].evidence_refs; runtime binds them '
    'to the original immutable source before validation. Literal original references and admitted '
    'section paths remain valid. Existing evidence_ref_indices and reference_projection fingerprints '
    'describe the ORIGINAL expanded sealed source pool, never hashes of display aliases. '
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
