"""Normalize public accounting events without guessing collateral or fee semantics."""
from __future__ import annotations
import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any

def normalize_event(endpoint: str, row: Any, *, address: str,
                    available_ms: int, evidence_ref: str) -> dict[str, Any]:
    """Single-address HyperCore boundary; related accounts are not consolidated.

    Ledger flows belong to this boundary, never automatically to every perp dex.
    Unsupported fields/types remain explicit and preserve their raw evidence.
    """
    result = {'status':'unknown','evidence_ref':evidence_ref,'endpoint':endpoint}
    if not isinstance(row,dict) or type(row.get('time')) is not int:
        return {**result,'reason':'event timestamp absent or malformed'}
    stamp=row['time'];delta=row.get('delta')
    if not isinstance(delta,dict):return {**result,'reason':'delta absent or malformed'}
    result.update({'event_ms':stamp,'available_ms':available_ms,'type':delta.get('type')})
    if stamp<0 or stamp>available_ms:return {**result,'reason':'event not causally available'}
    # Hash alone may identify several asset deltas in one transaction.
    if not row.get('hash'):return {**result,'reason':'transaction identity absent'}
    identity=hashlib.sha256(json.dumps({'time':stamp,'hash':row['hash'],
        'type':delta.get('type'),'coin':delta.get('coin'),'nonce':delta.get('nonce'),
        'user':delta.get('user'),'destination':delta.get('destination')},
        sort_keys=True,separators=(',',':')).encode()).hexdigest()
    base={'id':identity,'event_ms':stamp,'available_ms':available_ms,'evidence_ref':evidence_ref}
    def number(key: str) -> Decimal:
        value=delta[key]
        if isinstance(value,bool):raise ValueError('Boolean monetary amount')
        n=Decimal(str(value).strip())
        if not n.is_finite():raise ValueError('Nonfinite monetary amount')
        return n
    try:
        kind=delta.get('type')
        if endpoint=='userFunding':
            if kind!='funding' or not isinstance(delta.get('coin'),str) or not delta['coin']:
                return {**result,'reason':'funding type or instrument absent'}
            coin=delta['coin'];dex=coin.split(':',1)[0] if ':' in coin else ''
            amount=number('usdc')
            event={**base,'kind':'funding','scope_id':'perp:'+dex,'coin':coin,
                'amount':str(amount),'currency':'USDC' if not dex else 'UNVERIFIED_DEX_CURRENCY'}
            return {**result,'status':'normalized' if not dex else 'currency_unverified',
                'event':event,'reason':None if not dex else 'HIP-3 collateral currency requires metadata proof'}
        if endpoint!='userNonFundingLedgerUpdates':
            return {**result,'reason':'unsupported accounting endpoint'}
        event={**base,'kind':'flow','scope_id':'hypercore:'+address.lower(),
               'currency':'USDC','boundary_evidence_ref':evidence_ref}
        if kind=='send':
            amount=number('amount');source=str(delta.get('user','')).lower()
            destination=str(delta.get('destination','')).lower();account=address.lower()
            if (amount<0 or account not in (source,destination)
                or not source or not destination or not isinstance(delta.get('token'),str)
                or not delta['token'] or not isinstance(delta.get('sourceDex'),str)
                or not isinstance(delta.get('destinationDex'),str)):
                return {**result,'reason':'send identity, asset or scope absent'}
            # Gross/net fee semantics are unnecessary only for explicitly zero fees.
            if number('fee')!=0 or number('nativeTokenFee')!=0:
                return {**result,'reason':'nonzero send fee accounting not established'}
            event.update(currency=delta['token'],
                amount=str(Decimal(0) if source==destination else amount if destination==account else -amount),
                boundary_classification='internal' if source==destination else 'external',
                transfer_principal=str(amount),source_account=source,destination_account=destination,
                source_dex=delta['sourceDex'],destination_dex=delta['destinationDex'])
        elif kind=='deposit':
            amount=number('usdc')
            if amount<0:raise ValueError('Negative deposit')
            event.update(amount=str(amount),boundary_classification='external')
        elif kind in ('internalTransfer','subAccountTransfer'):
            amount=number('usdc')
            if amount<0:raise ValueError('Negative transfer magnitude')
            source=str(delta.get('user','')).lower();destination=str(delta.get('destination','')).lower()
            account=address.lower()
            if not source or not destination or account not in (source,destination):
                return {**result,'reason':'transfer direction not established for this address'}
            # The name internalTransfer does not imply internal to our boundary.
            fee=number('fee') if kind=='internalTransfer' else Decimal(0)
            if fee!=0:return {**result,'reason':'transfer fee gross/net semantics not established',
                'reported_principal':str(amount),'reported_fee':str(fee)}
            event.update(amount=str(Decimal(0) if source==destination else amount if destination==account else -amount),
                         boundary_classification='internal' if source==destination else 'external')
        elif kind=='accountClassTransfer':
            amount=number('usdc')
            if amount<0 or type(delta.get('toPerp')) is not bool:
                raise ValueError('Malformed account class transfer')
            event.update(amount='0',boundary_classification='internal',reported_principal=str(amount),
                         to_perp=delta['toPerp'])
        elif kind=='withdraw':
            return {**result,'reason':'withdrawal fee gross/net semantics not established',
                'reported_principal':str(number('usdc')),'reported_fee':str(number('fee'))}
        else:
            return {**result,'reason':'unsupported ledger mechanism: '+str(kind)}
        return {**result,'status':'normalized','event':event,'reason':None}
    except (KeyError,ValueError,InvalidOperation,TypeError):
        return {**result,'reason':'monetary fields absent, nonfinite or malformed'}
