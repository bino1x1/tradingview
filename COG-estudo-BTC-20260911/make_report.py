import csv
import json
from pathlib import Path

p = Path(__file__).parent
r = json.loads((p / 'results.json').read_text())
names = {
    'A_COG9_virada': 'COG 9: virada da inclinação',
    'B_COG9_ALMA3': 'COG 9 × ALMA 3 (base)',
    'C_COG9_RMA2_ALMA3': 'COG 9 + RMA 2 × ALMA 3',
    'D_COG21_ALMA3': 'COG 21 × ALMA 3',
    'E_COG9_ALMA5': 'COG 9 × ALMA 5',
    'F_COG9_ALMA3_EMA200': 'Base + filtro EMA 200 do preço',
    'G_COG9_LSMA200_EMA200': 'COG 9 × LSMA 200 + filtro EMA 200',
    'H_COG9_ALMA3_confirma2': 'Base + confirmação por mais uma vela',
}
rows = sorted(((k, v) for k, v in r['validation'].items() if k in names), key=lambda x: x[1]['win_rate'], reverse=True)
with (p / 'ranking-validation.csv').open('w', newline='', encoding='utf-8-sig') as f:
    w = csv.writer(f)
    w.writerow(['ranking', 'regra', 'operacoes', 'acerto_pct', 'retorno_pct', 'drawdown_pct', 'profit_factor', 'retorno_custo_dobrado_pct'])
    for i, (k, v) in enumerate(rows, 1):
        w.writerow([i, names[k], v['trades'], v['win_rate'], v['return_pct'], v['max_dd_pct'], v['pf'], v['stress_cost']['return_pct']])

report = '''# COG — estudo exploratório com Bitcoin

Data: 11/09/2026. O estudo não altera os indicadores Pine.

## Indicador e interpretação

Referência: Center Of Gravity Oscillator, de veryfid. Configuração-base: fechamento, período 9, sem suavização, gatilho ALMA 3, offset 0,85 e sigma 6. O script inclui LSMA, níveis históricos e Fibonacci; esses elementos não fazem parte da fórmula central do COG.

A fórmula é -Σ(preço[i] × (i+1))/Σ(preço[i]), com i=0 na barra atual. Para preço constante, COG 9 vale -5, não zero. O cálculo usa preços e não volume. Alterar dinamicamente o período desloca também essa referência: uma versão adaptativa precisa tratar esse deslocamento para não criar sinais artificiais.

O código original recebido calcula a RMA antes de mudar o parâmetro do tema CLEAN; atribuir um novo período depois não recalcula a série já obtida. Temas devem ser auditados separadamente das regras matemáticas. A versão local já explicita a suavização usada.

## Oportunidades

| Prioridade | Mudança | Justificativa e evidência |
|---|---|---|
| Essencial | Separar sinal confirmado de marcador deslocado | Um ponto desenhado na barra anterior só é conhecido depois; não pode virar entrada retroativa no teste. |
| Alta | ALMA 3 → 5 | Maior retorno entre as oito regras em 2023–2025; hipótese promissora, ainda precisa de teste independente. |
| Alta | Confirmar permanência acima do gatilho por mais uma vela | Maior acerto observado e menos operações que a base; atrasa a entrada. |
| Média | RMA 2 | Menos operações, mas drawdown maior que a base; suavização não significa necessariamente menor risco. |
| Média | Regime pelo preço e EMA 200 | Menor drawdown observado na variante F, mas retorno baixo e negativo com custo dobrado. |
| Pesquisa | Stops e tamanho de posição por ATR | Pode controlar perdas e exposição; não testado aqui. Exige modelar gaps e execução intrabar. |
| Pesquisa | Período adaptativo, ER e normalização | Pode distinguir ruído e tendência; não testado. Corrigir a referência dependente do período antes de avaliar. |
| Pesquisa | Divergências com pivôs confirmados | Coerente com uso discricionário; testar somente após confirmação dos pivôs, sem olhar o futuro. |
| Visual | Cores, sombra, halo e tamanho dos pontos | Melhoram leitura; não demonstram vantagem estatística por si mesmos. |

## Método reproduzível

- Dados públicos Binance: BTCUSDT, candles diários UTC, janeiro/2018 a dezembro/2025; 2.922 candles, meses ZIP conferidos por SHA256.
- 2018 aquece os indicadores. Desenvolvimento: 2019–2022. Validação exploratória: 2023–2025, iniciada com caixa independente.
- Oito regras fixadas antes da leitura dos resultados; nenhuma busca extensiva de parâmetros. A escolha posterior do vencedor torna necessário outro período independente.
- Capital inicial de 10.000 USDT, compra com todo o capital disponível, uma posição por vez, somente comprado ou em caixa. Sem alavancagem, venda a descoberto, juros, impostos ou funding.
- Sinal calculado no fechamento e execução na abertura seguinte. Custo combinado de 0,15% em cada lado, representando 0,10% de taxa e 0,05% de fricção de execução; hipótese, não tabela real de tarifas. Estresse: 0,30% por lado.
- Saída pelo sinal oposto; variantes com filtro também saem quando o regime deixa de valer. Sem stop ou alvo. Posições restantes são liquidadas no último fechamento, com custo, e identificadas no arquivo de operações.
- Acerto: operação com lucro líquido positivo. Retorno: acumulado com reinvestimento. Drawdown: maior queda da curva marcada nos fechamentos diários, não risco intradiário. Profit factor: ganhos monetários divididos por perdas monetárias absolutas.
- Filtro de regime: fechamento acima da EMA 200 do preço e EMA não decrescente. LSMA: regressão linear do COG, janela 200, ponto final. ALMA mantém offset 0,85 e sigma 6 em todas as variantes.
- Confirmação adicional: cruzamento de alta na vela anterior e COG ainda acima do gatilho no fechamento atual; entrada na abertura seguinte. Saída no cruzamento de baixa sem confirmação adicional.
- A regra de virada compra quando COG cruza sua própria série defasada para cima e vende no cruzamento para baixo. Isso não reproduz filtros MTF nem todos os detalhes visuais dos indicadores locais.

## Ranking por acerto — 2023–2025

| # | Regra | Operações | Acerto | Retorno líquido | Drawdown | Profit factor |
|---|---|---:|---:|---:|---:|---:|
'''
for i, (k, v) in enumerate(rows, 1):
    report += f"| {i} | {names[k]} | {v['trades']} | {v['win_rate']:.2f}% | {v['return_pct']:.2f}% | {v['max_dd_pct']:.2f}% | {v['pf']:.2f} |\n"
report += '''
Comprar e manter BTC no mesmo intervalo, com custos: retorno de 428,27% e drawdown de 32,02%. Não faz sentido ranquear seu acerto com apenas uma operação. Nenhuma das oito estratégias superou seu retorno nesse intervalo.

## Desenvolvimento e sensibilidade aos custos

| Regra | Retorno 2019–2022 | Drawdown 2019–2022 | Retorno 2023–2025 com custo dobrado | IC 95% do acerto na validação |
|---|---:|---:|---:|---|
'''
for k, v in rows:
    d = r['development'][k]
    report += f"| {names[k]} | {d['return_pct']:.2f}% | {d['max_dd_pct']:.2f}% | {v['stress_cost']['return_pct']:.2f}% | {v['ci95'][0]:.1f}%–{v['ci95'][1]:.1f}% |\n"
report += '''
Os intervalos de Wilson são apenas aproximações binomiais: operações financeiras podem ser dependentes. A sobreposição e a seleção entre oito variantes impedem tratar o ranking como prova de superioridade estatística.

## Conclusão e próximo experimento

ALMA 5 é a primeira candidata pelo retorno; confirmação adicional, pelo acerto. Nenhuma é vencedora universal. Acerto abaixo de 50% pode coexistir com lucro quando ganhos superam perdas. A maior parte das variantes também sofreu perdas em 2025; resultados agregados escondem regimes desfavoráveis.

Próximo experimento: congelar base, ALMA 5 e confirmação adicional; executar walk-forward com janelas cronológicas e testar em período ainda não inspecionado, incluindo 2026. Depois avaliar dimensionamento por volatilidade, custos por corretora e execução em conta simulada. Não escolher dezenas de parâmetros no mesmo intervalo usado para anunciar o resultado.

## Verificação e limites

verify.py verifica causalidade por truncamento das séries, execução na abertura seguinte, aplicação dos custos e saída forçada. São testes da implementação Python, não certificação de equivalência com o motor Pine/TradingView. O histórico não estima uma taxa de sucesso futura. Não foram simulados livro de ofertas, liquidez intrabar, posições vendidas ou regras discricionárias do autor.

Reprodução: executar python study.py e depois python verify.py nesta pasta. O downloader reutiliza arquivos existentes; acesso à internet é necessário para baixar os arquivos ausentes. results.json contém métricas completas, inclusive testes anuais independentes; trades.csv contém operações, equity-validation.csv contém curvas, sources.json registra a origem e hashes.

## Fontes

- [Indicador original e descrição do autor](https://www.tradingview.com/script/8et1jfIn-Center-Of-Gravity-Oscillator/)
- [Referência oficial Pine v4 — cog](https://in.tradingview.com/pine-script-reference/v4/)
- [Documentação dos dados públicos Binance](https://github.com/binance/binance-public-data)
- [Arquivo público Binance](https://data.binance.vision/)
- [TradingView — simulação, custos e vieses de estratégias](https://www.tradingview.com/pine-script-docs/concepts/strategies/)
'''
(p / 'RELATORIO.md').write_text(report, encoding='utf-8')
print('Relatório e ranking CSV gerados.')
