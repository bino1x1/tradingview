"""Gera a estrategia a partir do mesmo codigo do indicador, sem duplicar regras."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
source = (ROOT / 'COG.pine').read_text(encoding='utf-8')
old = 'indicator("Cog By BinoX V1", shorttitle="Cog By BinoX V1", timeframe="")'
assert source.count(old) == 1
source = source.replace(old, '''// Comparacao de sinais. Nao simula funding nem margem cruzada de corretoras.
// Quantidade, custos e capital podem ser alterados nas Propriedades.
strategy("Cog By BinoX V1 - Testes", overlay=false, initial_capital=10000, default_qty_type=strategy.percent_of_equity, default_qty_value=100, commission_type=strategy.commission.percent, commission_value=0.15, pyramiding=0, process_orders_on_close=false, calc_on_every_tick=false, margin_long=100, margin_short=100)''')
source = source.replace('enableResearch = input.bool(false,', 'enableResearch = input.bool(true,')
# alertcondition nao produz alertas de estrategia; usar alertas de ordens.
source = '\n'.join(line for line in source.splitlines() if not line.startswith('alertcondition('))
source += '''

// EXECUCAO — sinal no fechamento e ordem a mercado na abertura seguinte.
tradeSide = input.string("Long", "Operacoes", options=["Long", "Short", "Long e Short"], group="Simulacao")
testStart = input.time(timestamp("01 Jan 2023 00:00 +0000"), "Inicio", group="Simulacao")
testEnd = input.time(timestamp("01 Jan 2026 00:00 +0000"), "Fim (exclusivo)", group="Simulacao", tooltip="A ordem de encerramento e enviada no primeiro fechamento fora do intervalo e executada na abertura seguinte.")
warmupBars = input.int(300, "Barras minimas de aquecimento", minval=50, maxval=5000, group="Simulacao")
useAtrStop = input.bool(false, "Ativar stop fixo por ATR", group="Simulacao")
stopAtrLength = input.int(14, "ATR do stop", minval=1, maxval=200, group="Simulacao", active=useAtrStop)
stopAtrMultiple = input.float(2.0, "Distancia do stop (ATR)", minval=0.1, maxval=20, step=0.1, group="Simulacao", active=useAtrStop, tooltip="Distancia congelada com o ATR da barra do sinal e aplicada a partir do preco de entrada. Nao e trailing stop. Para maior precisao intrabar, use Bar Magnifier.")
stopAtr = ta.atr(stopAtrLength)
var int longStopTicks = na
var int shortStopTicks = na
inTest = time >= testStart and time < testEnd and bar_index >= warmupBars
wantLong = inTest and researchLong and tradeSide != "Short"
wantShort = inTest and researchShort and tradeSide != "Long"

if testEnd <= testStart
    runtime.error("O fim do teste deve ser posterior ao inicio.")

if not inTest or not enableResearch
    strategy.cancel_all()
    strategy.close_all(comment="Fora do teste")
else
    // Uma ordem de reversao ja encerra o lado anterior: nao duplicar close.
    if wantLong and strategy.position_size <= 0
        strategy.cancel("Stop Short")
        longStopTicks := int(math.max(1, math.round(stopAtr * stopAtrMultiple / syminfo.mintick)))
        strategy.entry("Long", strategy.long)
        if useAtrStop
            strategy.exit("Stop Long", "Long", loss=longStopTicks)
    else if wantShort and strategy.position_size >= 0
        strategy.cancel("Stop Long")
        shortStopTicks := int(math.max(1, math.round(stopAtr * stopAtrMultiple / syminfo.mintick)))
        strategy.entry("Short", strategy.short)
        if useAtrStop
            strategy.exit("Stop Short", "Short", loss=shortStopTicks)
    else
        if strategy.position_size > 0 and researchExitLong
            strategy.close("Long", comment="Saida Long")
        if strategy.position_size < 0 and researchExitShort
            strategy.close("Short", comment="Saida Short")
'''
(ROOT / 'COG Testes.pine').write_text(source, encoding='utf-8', newline='\r\n')
print('COG Testes.pine gerado a partir do indicador.')
