"""Measured workload decomposition; scenario reserves are policy assumptions."""
from __future__ import annotations
import math

PHASES = {
    'population-rest-history_backfill': 'history_backfill',
    'population-rest-incremental': 'incremental_history',
    'population-rest-overview': 'account_inventory',
    'population-collateral-metadata': 'shared_metadata',
    'tamtam-market-collector': 'market_collection',
    'tamtam-whale-collector': 'legacy_account_collection_mixed',
}


def workload_budget(report, *, local_budget=900, recovery_fraction=.2):
    minutes=report['window_minutes']
    if not math.isfinite(minutes) or minutes<=0 or local_budget<=0:
        raise ValueError('Positive measured window and budget required')
    if not 0<=recovery_fraction<1:
        raise ValueError('Recovery reserve must be between zero and one')
    phases={}
    for group in report['groups']:
        phase=PHASES.get(group['task'],'unclassified')
        values=phases.setdefault(phase,{'reserved_weight':0,'attempts':0,
                                     'retry_attempts':0,'rate_limits':0,'wait_seconds':0})
        for key in values:
            value=group.get(key,0) or 0
            if not math.isfinite(value) or value<0:
                raise ValueError('Invalid measured workload')
            values[key]+=value
    for values in phases.values():
        values['reserved_weight_per_minute']=values['reserved_weight']/minutes
    measured=sum(v['reserved_weight_per_minute'] for v in phases.values())
    operational_budget=local_budget*(1-recovery_fraction)
    return {'version':'workload-decomposition-v1','phases':phases,
            'local_reserved_weight_budget_per_minute':local_budget,
            'recovery_fraction_assumption':recovery_fraction,
            'operational_budget_per_minute':operational_budget,
            'measured_reserved_weight_per_minute':measured,
            'additional_headroom_with_recovery_per_minute':max(0,operational_budget-measured),
            'excess_above_operational_budget_per_minute':max(0,measured-operational_budget),
            'expansion_status':'no_measured_margin' if measured>=operational_budget else 'margin_requires_full_job_cost_measurement',
            'sustainable_account_capacity':None,
            'limits':['reserved weight is not measured server charge',
                      'legacy collection mixes backfill and incremental requests',
                      'account capacity needs full job cost, cadence and retention evidence',
                      'recovery reserve is a configurable planning assumption, not an exchange requirement']}
