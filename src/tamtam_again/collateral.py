"""Causal instrument/collateral catalog; metadata never values shared balances."""
from __future__ import annotations
from typing import Any
import json
import time
from .storage import Store,utc_now

def build_catalog(perp_payload: Any, spot_payload: Any, *, available_ms: int,
                  evidence_refs: list[str]) -> dict[str, Any]:
    if not isinstance(perp_payload,list) or not isinstance(spot_payload,list) or not spot_payload or not isinstance(spot_payload[0],dict):
        raise ValueError('Invalid public metadata envelopes')
    tokens=spot_payload[0].get('tokens',[])
    if not isinstance(tokens,list):raise ValueError('Invalid spot token metadata')
    by_index={};names={}
    for token in tokens:
        if not isinstance(token,dict) or type(token.get('index')) is not int:continue
        index=token['index']
        if index in by_index:raise ValueError('Duplicate token index')
        by_index[index]=token
        names.setdefault(token.get('name'),[]).append(index)
    instruments={};dexes={};unknown=[]
    for entry in perp_payload:
        # Official page shows meta/context envelopes; live API also returns metas.
        meta=entry[0] if isinstance(entry,list) and entry else entry
        if not isinstance(meta,dict) or not isinstance(meta.get('universe'),list):
            raise ValueError('Invalid perpetual metadata')
        index=meta.get('collateralToken');token=by_index.get(index) if type(index) is int else None
        currency=None
        if token and isinstance(token.get('name'),str) and token.get('tokenId') and len(names[token['name']])==1:
            currency=token['name']
        universe=meta['universe']
        prefixes={a['name'].split(':',1)[0] if ':' in a['name'] else '' for a in universe if isinstance(a,dict) and isinstance(a.get('name'),str)}
        if len(prefixes)!=1:
            unknown.append({'reason':'empty or mixed dex universe; no positional dex inference','collateral_token':index});continue
        dex=next(iter(prefixes))
        if dex in dexes:raise ValueError('Duplicate dex metadata')
        proof={'dex':dex,'collateral_token':index,'token_id':token.get('tokenId') if token else None,
               'currency':currency,'available_ms':available_ms,'evidence_refs':evidence_refs,
               'status':'identified' if currency else 'unknown'}
        dexes[dex]=proof
        for asset in universe:
            if not isinstance(asset,dict) or not isinstance(asset.get('name'),str):continue
            if asset['name'] in instruments:raise ValueError('Duplicate instrument metadata')
            instruments[asset['name']]={**proof,'instrument':asset['name'],
                'sz_decimals':asset.get('szDecimals'),'max_leverage':asset.get('maxLeverage'),
                'margin_mode':asset.get('marginMode'),'is_delisted':asset.get('isDelisted',False)}
    return {'schema_version':1,'available_ms':available_ms,'instruments':instruments,'dexes':dexes,
            'unknown':unknown,'evidence_refs':evidence_refs,
            'limits':['token identification is not an FX quote','no historical validity inferred before receipt','no sum of shared collateral or account valuation']}

def resolve_currency(catalogs: list[dict[str,Any]], *, event_ms: int,
                     instrument: str|None=None, dex: str|None=None) -> dict[str,Any]|None:
    eligible=[c for c in catalogs if c['available_ms']<=event_ms]
    if not eligible:return None
    catalog=max(eligible,key=lambda c:c['available_ms'])
    proof=catalog['instruments'].get(instrument) if instrument is not None else catalog['dexes'].get(dex)
    return proof if proof and proof['status']=='identified' else None

def refresh_catalog(store: Store, client: Any, *, max_age_seconds: int=3600,
                    force: bool=False) -> dict[str,Any]:
    """Two shared public calls per refresh, using the client's project quota."""
    if type(max_age_seconds) is not int or max_age_seconds<60:
        raise ValueError('Metadata refresh must be at least sixty seconds')
    store.connection.execute('create table if not exists collateral_catalogs (catalog_id integer primary key,network text not null,available_ms integer not null,payload_json text not null)')
    store.connection.commit()
    latest=store.connection.execute('select available_ms,payload_json from collateral_catalogs where network=? order by available_ms desc limit 1',(client.network,)).fetchone()
    if not force and latest and 0<=int(time.time()*1000)-latest['available_ms']<max_age_seconds*1000:
        return json.loads(latest['payload_json'])
    values={};refs=[];previous=getattr(client,'task',None)
    if previous is not None:client.task='population-collateral-metadata'
    try:
        for endpoint in ('allPerpMetas','spotMetaAndAssetCtxs'):
            query={'type':endpoint};requested=utc_now();values[endpoint]=client.post_info(query)
            store.save_observation(network=client.network,source='hyperliquid-population-rest-v1',entity_type='market',entity_id='collateral:all',endpoint=endpoint,payload=values[endpoint],request_payload={**query,'phase':'shared_metadata'},requested_at=requested)
            row=store.connection.execute("select observation_id from raw_observations where network=? and source='hyperliquid-population-rest-v1' and entity_id='collateral:all' and endpoint=? order by observation_id desc limit 1",(client.network,endpoint)).fetchone()
            refs.append('raw_observations:'+str(row['observation_id']))
        catalog=build_catalog(values['allPerpMetas'],values['spotMetaAndAssetCtxs'],available_ms=int(time.time()*1000),evidence_refs=refs)
        store.connection.execute('insert into collateral_catalogs(network,available_ms,payload_json) values (?,?,?)',(client.network,catalog['available_ms'],json.dumps(catalog,sort_keys=True)));store.connection.commit()
        return catalog
    finally:
        if previous is not None:client.task=previous
