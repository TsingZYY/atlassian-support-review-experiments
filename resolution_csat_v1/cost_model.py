"""Conditional break-even only. Elapsed ticket intervals are not labour savings."""
import argparse
import json
import math


def calculate(volume, fixed_cost, variable_cost_per_ticket, hourly_cost,
              realizable_fraction, minutes_saved=None):
    values = [volume, fixed_cost, variable_cost_per_ticket, hourly_cost, realizable_fraction]
    if not all(math.isfinite(x) for x in values):
        raise ValueError('All parameters must be finite')
    if volume <= 0 or volume != int(volume):
        raise ValueError('volume must be a positive integer')
    if min(fixed_cost, variable_cost_per_ticket, hourly_cost) < 0:
        raise ValueError('Costs must be nonnegative')
    if not 0 <= realizable_fraction <= 1:
        raise ValueError('realizable_fraction must be in [0,1]')
    if minutes_saved is not None and not math.isfinite(minutes_saved):
        raise ValueError('minutes_saved must be finite when supplied')
    extra_cost = volume * variable_cost_per_ticket + fixed_cost
    cash_rate = hourly_cost * realizable_fraction / 60
    if cash_rate > 0:
        threshold = extra_cost / volume / cash_rate
        state = 'FINITE'
    elif extra_cost == 0:
        threshold, state = 0.0, 'ZERO_COST_ZERO_MONETIZED_BENEFIT'
    else:
        threshold, state = None, 'NO_FINITE_BREAK_EVEN'
    net = None if minutes_saved is None else volume * minutes_saved * cash_rate - extra_cost
    return {'volume':int(volume), 'fixed_cost':fixed_cost,
            'variable_cost_per_ticket':variable_cost_per_ticket, 'hourly_cost':hourly_cost,
            'realizable_fraction':realizable_fraction, 'total_extra_cost':extra_cost,
            'break_even_minutes_per_ticket':threshold, 'break_even_state':state,
            'assumed_labour_minutes_saved':minutes_saved, 'conditional_net_profit':net,
            'retention_conversion_contribution':0, 'actual_profit_measured':False,
            'elapsed_ticket_interval_used_as_labour_saving':False}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--volume',type=int,default=1000)
    p.add_argument('--fixed-cost',type=float,default=100)
    p.add_argument('--variable-cost-per-ticket',type=float,default=.5)
    p.add_argument('--hourly-cost',type=float,default=30)
    p.add_argument('--realizable-fraction',type=float,default=1)
    p.add_argument('--minutes-saved',type=float,default=None,
                   help='Actual labour minutes saved, or an explicitly hypothetical scenario; never the observed ticket interval')
    args = vars(p.parse_args())
    print(json.dumps(calculate(**args),ensure_ascii=False,indent=2,allow_nan=False))
