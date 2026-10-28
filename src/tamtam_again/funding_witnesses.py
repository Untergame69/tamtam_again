"""Frozen, public settled-funding witnesses; cost coefficients only, no signals."""
from datetime import datetime, timezone
import json
import re

from .engine import number

VERSION='settled-funding-witnesses-v1'
MAX_EXTRAS=9


def _ms(value):
    return int(datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()*1000)


def validate_contract(contract, *, network=None, market=None, address=None):
    if (not isinstance(contract,dict) or contract.get('version')!=VERSION
            or not isinstance(contract.get('network'),str) or not contract['network']
            or not isinstance(contract.get('market'),str) or not contract['market']
            or contract.get('currency')!='USDC'
            or type(contract.get('available_ms')) is not int or contract['available_ms']<0):
        raise ValueError('Versioned frozen USDC funding witness scope required')
    addresses=contract.get('addresses');refs=contract.get('evidence_refs')
    if (not isinstance(addresses,list) or not 1<=len(addresses)<=MAX_EXTRAS
            or any(not isinstance(a,str) or not re.fullmatch(r'0x[0-9a-f]{40}',a) for a in addresses)
            or len(set(addresses))!=len(addresses)
            or not isinstance(refs,list) or len(refs)!=2 or len(set(refs))!=2
            or any(not isinstance(ref,str) or not re.fullmatch(r'raw_observations:[0-9]+',ref) for ref in refs)):
        raise ValueError('At most nine distinct frozen extra witnesses and two exact catalog roots required')
    if ((network is not None and contract['network']!=network)
            or (market is not None and contract['market']!=market)
            or (address is not None and address.lower() in addresses)):
        raise ValueError('Funding witness contract differs from execution scope')


def _verify_market(store, contract):
    """Only public catalog payloads; verify source, receipt and content hashes."""
    from .collateral import build_catalog
    from .population_local_join import _decode_verified
    payloads={}
    for ref in contract['evidence_refs']:
        row=store.connection.execute('select * from raw_observations where observation_id=? '
            'and length(response_json)<=2000000',(int(ref.split(':')[1]),)).fetchone()
        if (row is None or row['network']!=contract['network']
                or row['source']!='hyperliquid-population-rest-v1'
                or row['entity_type']!='market' or row['entity_id']!='collateral:all'
                or row['endpoint'] not in {'allPerpMetas','spotMetaAndAssetCtxs'}
                or row['endpoint'] in payloads or _ms(row['observed_at'])>contract['available_ms']
                or json.loads(row['request_json']).get('type')!=row['endpoint']):
            raise ValueError('Causal matching public collateral catalog roots required')
        payloads[row['endpoint']]=_decode_verified(row,max_decoded_bytes=2_000_000)
    if set(payloads)!={'allPerpMetas','spotMetaAndAssetCtxs'}:
        raise ValueError('Both perpetual and token catalogs required')
    catalog=build_catalog(payloads['allPerpMetas'],payloads['spotMetaAndAssetCtxs'],
        available_ms=contract['available_ms'],evidence_refs=contract['evidence_refs'])
    asset=catalog['instruments'].get(contract['market'])
    if not asset or asset.get('currency')!='USDC' or asset.get('is_delisted') is not False:
        raise ValueError('Funding witnesses require a verified matching active USDC perpetual')


def archive_funding_events(store, contract, *, network, address, market, start_ms, end_ms,
                           after_observation_id=0):
    """Read only authorized funding envelopes from the immutable witness pool.

    Whole-account guards precede EACH payload SELECT, because funding snapshots
    may contain older settlements and other markets. Such rows never become
    trade signals or proof of zero funding. No collector or provider is called.
    """
    from .discovery import protected_addresses
    from .research_memory import authorized_account_history
    from .population_local_join import _decode_verified
    validate_contract(contract,network=network,market=market,address=address)
    _verify_market(store,contract)
    if contract['available_ms']>start_ms:
        raise ValueError('Funding witness pool must be frozen before observation begins')
    start=datetime.fromtimestamp(start_ms/1000,timezone.utc).isoformat(timespec='milliseconds')
    end=datetime.fromtimestamp(end_ms/1000,timezone.utc).isoformat(timespec='milliseconds')
    events=[];cursor=after_observation_id;total=0;decoded_bytes=0;funding_records=0
    for witness in contract['addresses']:
        # Metadata only: never SELECT a reserved witness's response_json.
        if witness in protected_addresses(store) or not authorized_account_history(store,network,witness,end_ms):
            continue
        tracked=store.connection.execute("select added_at from candidates where network=? and address=? and status='tracked'",
            (network,witness)).fetchone()
        if tracked is None or _ms(tracked['added_at'])>contract['available_ms']:
            continue
        rows=store.connection.execute('select observation_id,observed_at,requested_at,response_sha256 '
            "from raw_observations where network=? and source='hyperliquid-websocket-v1' "
            "and entity_type='account' and entity_id=? and endpoint='userFundings' "
            'and observation_id>? and observed_at>=? and observed_at<? and requested_at<? '
            'order by observation_id limit 10001',(network,witness,after_observation_id,start,end,end)).fetchall()
        total+=len(rows)
        if total>10000:
            raise ValueError('Frozen funding witness archive exceeds bounded row budget')
        for meta in rows:
            if witness in protected_addresses(store) or not authorized_account_history(store,network,witness,end_ms):
                break
            row=store.connection.execute('select * from raw_observations where observation_id=? and length(response_json)<=2000000',
                (meta['observation_id'],)).fetchone()
            if row is None or row['response_sha256']!=meta['response_sha256']:
                raise ValueError('Funding witness archive identity changed')
            payload,decoded=_decode_verified(row,max_decoded_bytes=2_000_000,with_size=True)
            decoded_bytes+=decoded
            if decoded_bytes>20_000_000:
                raise ValueError('Funding witness total decoding budget exceeded')
            cursor=max(cursor,row['observation_id'])
            receipt=_ms(row['requested_at']);available=max(receipt,_ms(row['observed_at']))
            if not start_ms<=receipt<=available<end_ms:continue
            if not isinstance(payload,dict) or payload.get('channel')!='userFundings':continue
            data=payload.get('data',{})
            if not isinstance(data,dict) or not isinstance(data.get('user'),str) or data['user'].lower()!=witness:continue
            fundings=data.get('fundings')
            if not isinstance(fundings,list):continue
            funding_records+=len(fundings)
            if len(fundings)>10000 or funding_records>100000:
                raise ValueError('Funding witness envelope exceeds row budget')
            for index,funding in enumerate(fundings):
                if not isinstance(funding,dict) or funding.get('coin')!=market:continue
                stamp=funding.get('time')
                if type(stamp) is not int or not start_ms<=stamp<=receipt:continue
                if 'szi' not in funding or 'usdc' not in funding:continue
                size=number(funding['szi'])
                if not size:continue
                coefficient=number(funding['usdc'])/size
                period={'network':network,'address':witness,'market':'*',
                        'start_ms':0,'end_ms':available+1}
                events.append({'id':f"funding-witness:{row['observation_id']}:{index}",
                    'kind':'funding','event_ms':stamp,'received_ms':receipt,'available_ms':available,
                    'unit_funding_usdc':str(coefficient),
                    'provenance':'settled_public_witness_usdc_divided_by_signed_szi',
                    'cost_only':True,'source_address':witness,'source_market':market,
                    'is_snapshot':data.get('isSnapshot'),'source_period':period,
                    'evidence_ref':f"raw_observations:{row['observation_id']}",
                    'archive_response_sha256':row['response_sha256'],'archive_event_index':index,
                    'archive_available_ms':_ms(row['observed_at'])})
    return events,cursor
