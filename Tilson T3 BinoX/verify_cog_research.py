"""Verifica expressoes de entrada do Pine com um oraculo independente.

Nao e um compilador Pine: a compilacao e o desenho devem ser conferidos no TV.
"""
from pathlib import Path
import random
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
code = (ROOT / 'COG.pine').read_text(encoding='utf-8')
expressions = {
    name: re.search(rf'^{name} = (.+)$', code, re.M).group(1)
    for name in ['researchLong', 'researchShort']
}


def signals(values, extra, enabled, bull, bear):
    """Avalia as expressoes reais de entrada, com barssince/contagens em Python."""
    last_up = last_dn = None
    above = below = 0
    result = []
    for i, value in enumerate(values):
        if i and value > 0 and values[i - 1] <= 0:
            last_up = i
        if i and value < 0 and values[i - 1] >= 0:
            last_dn = i
        above = above + 1 if value > 0 else 0
        below = below + 1 if value < 0 else 0
        state = dict(researchReady=enabled[i], barsAfterUp=i-last_up if last_up is not None else -1,
                     barsAfterDn=i-last_dn if last_dn is not None else -1,
                     effectiveConfirmation=extra, aboveCount=above, belowCount=below,
                     bullAllowed=bull[i], bearAllowed=bear[i])
        result.append(tuple(eval(expressions[name], {'__builtins__': {}}, state)
                            for name in ['researchLong', 'researchShort']))
    return result


def oracle(values, extra, enabled, bull, bear):
    result = [[False, False] for _ in values]
    for crossed in range(1, len(values)):
        for side, permission, slot in [(1, bull, 0), (-1, bear, 1)]:
            end = crossed + extra
            if end >= len(values):
                continue
            if values[crossed-1] * side <= 0 and values[crossed] * side > 0:
                holds = all(x * side > 0 for x in values[crossed:end+1])
                result[end][slot] = holds and enabled[end] and permission[end]
    return [tuple(pair) for pair in result]


rng = random.Random(20260911)
fixtures = [[-1, 1, 1, 1, 1, 1, 1, 1], [-1, 1, 0, 1, -1, -1],
            [1, -1, -1, 0, -1, 1, 1], [0]*20]
fixtures += [[rng.choice([-2, -1, 0, 1, 2]) for _ in range(200)] for _ in range(40)]
checks = 0
for values in fixtures:
    for extra in range(6):
        for gated in [False, True]:
            masks = [[bool(rng.randrange(2)) if gated else True for _ in values] for _ in range(3)]
            got = signals(values, extra, *masks)
            assert got == oracle(values, extra, *masks)
            cut = len(values)//2
            assert signals(values[:cut], extra, *(m[:cut] for m in masks)) == got[:cut]
            checks += 1

# A estrategia deve ser gerada sem alteracoes nas regras de sinal/filtro.
target = ROOT / 'COG Testes.pine'
before = target.read_bytes()
subprocess.run([sys.executable, str(ROOT / 'build_cog_strategy.py')], check=True)
assert before == target.read_bytes(), 'Estrategia estava fora de sincronia com o indicador'
strategy = target.read_text(encoding='utf-8')
for name, expression in expressions.items():
    assert f'{name} = {expression}' in strategy
assert 'process_orders_on_close=false' in strategy
assert 'timeframe=' not in strategy
assert 'alertcondition(' not in strategy

print(f'OK: {checks} cenarios de confirmacao/filtros, cancelamento e causalidade; estrategia sincronizada.')
