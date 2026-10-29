"""Lossless short notation for SHA-256 archive references in sealed packets."""
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
    pool=packet.get('evidence_refs',[])
    if not isinstance(pool,list) or any(not isinstance(ref,str) for ref in pool):
        raise ValueError('Ordered string evidence pool required')
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
