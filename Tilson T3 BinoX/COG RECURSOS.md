# COG: recursos opcionais e testes

O indicador continua como **Cog By BinoX V1**. Em **Recursos de teste**, ative os recursos e escolha:

| Configuracao | Calculo | Confirmacao adicional |
|---|---|---|
| Personalizado | Parametros originais, incluindo suavizacao e tema | 0 a 5 velas |
| Base COG 9 / ALMA 3 | COG 9 sem RMA, ALMA 3 / 0,85 / 6 | 0 |
| COG 9 / ALMA 5 | COG 9 sem RMA, ALMA 5 / 0,85 / 6 | 0 |
| COG 9 / ALMA 3 + confirmacao | COG 9 sem RMA, ALMA 3 / 0,85 / 6 | 1 |

Os presets preservam a fonte selecionada. Selecione fechamento para comparar com o estudo anterior. Nos presets fixos, os controles originais de periodo, RMA e ALMA nao sao usados; volte a Personalizado para edita-los. Os temas continuam controlando elementos auxiliares; CLEAN pode mostrar sua SMA branca, mas o gatilho de teste e sempre o ALMA efetivo.

## Filtros implementados

Em **Filtro de teste**, habilite um filtro de cada vez: KAMA, DSMA, JMA, T3 ou EMA. Todos possuem parametros editaveis. A fonte dos filtros e o fechamento do preco no timeframe do indicador, nao os valores do COG. A escolha entre preco, inclinacao ou ambos define as entradas permitidas; dados indisponiveis bloqueiam entradas com filtro ligado. Inclinacao zero e neutra, nao alta/baixa.

Uma entrada Long exige cruzamento de alta do COG/ALMA e permissao do filtro na barra de confirmacao. Short e simetrico. A confirmacao exige continuidade estrita do lado novo: igualdade ou retorno ao outro lado cancela a sequencia. Um sinal bloqueado pelo filtro nao e repetido mais tarde sem novo cruzamento.

As saidas usam o cruzamento oposto, sem a confirmacao adicional das entradas. Opcionalmente saem ao perder o filtro. Alertas de saida do indicador representam condicoes, nao conhecimento de uma posicao aberta. Crie os alertas de entrada/saida disponiveis no menu TradingView; com confirmacao ligada, use fechamento de vela.

O valor do filtro e suas permissoes aparecem na Janela de Dados. O filtro de preco nao e desenhado na escala do oscilador. Os marcadores de virada visual continuam separados das entradas de teste, que nao possuem offset para o passado.

DSMA usa a estrutura de Ehlers com alpha limitado a 1 para estabilidade em periodos curtos; e uma variante documentada, nao equivalencia irrestrita ao artigo. KAMA ordena os periodos rapido/lento e inicia pela SMA do periodo ER. JMA usa o surrogate publico do arquivo JMA BinoX (power 2), nao uma alegacao de acesso ao algoritmo proprietario. T3 usa o nucleo de seis EMAs com fator fixo, sem os offsets visuais ou ER do indicador Tilson.

## Strategy Tester

Abra **COG Testes.pine** como outro script e adicione ao grafico. Ele e gerado do indicador por `python build_cog_strategy.py`, mantendo os mesmos calculos. No indicador, os recursos sao desligados por padrao; na estrategia sao ligados.

- Padrao: Long, 10.000 de capital inicial, 100% do patrimonio nominal por entrada e 0,15% de comissao por lado. Altere quantidade, capital, comissao e slippage nas Propriedades.
- Escolha Long, Short ou ambos, datas e aquecimento no grupo Simulacao. Para filtros lentos, aumente o aquecimento e carregue historico anterior ao inicio.
- Ordens de mercado sao executadas na abertura seguinte ao sinal. O encerramento do intervalo e solicitado no primeiro fechamento fora dele; isso difere de liquidar exatamente no ultimo fechamento do estudo Python.
- Stop ATR opcional: distancia congelada na barra do sinal, arredondada a ticks e aplicada sobre o preco efetivo de entrada. Ele pode atuar na vela de entrada; nao e trailing stop. Use Bar Magnifier quando disponivel para examinar a execucao intrabar.
- O padrao de margem e 100%. Este arquivo testa sinais; nao reproduz 75x, funding, mark price ou margem cruzada de uma corretora. Nao compare resultados como se fosse o simulador de futuros proposto.
- Compare primeiro a base, ALMA 5 e confirmacao; depois adicione KAMA, DSMA, JMA ou T3 individualmente. Nenhum resultado novo de performance foi produzido nesta alteracao.

FRAMA, MAMA/FAMA, ADX/DMI, Supertrend, VWAP, periodo adaptativo e divergencias permanecem candidatos para etapas posteriores. Nao ha controles vazios fingindo executar esses modelos.

## Ponto e halo: COG, JMA e T3

No grupo **Viradas**, ponto e halo possuem visibilidade, tamanho e transparencia independentes. Tamanho do ponto: 1 a 30; halo: 1 a 50. Exemplo: ponto 5, halo 10, transparencia do ponto 0 e do halo 60.

Ative **Sobrescrever cor do ponto** e/ou **Sobrescrever cor do halo** para usar um RGB fixo em todas as viradas. As transparencias numericas substituem a transparencia do seletor e da linha: 0 e opaco, 100 e invisivel. Um halo menor que o ponto pode ficar encoberto. Ao ocultar o halo, o ponto e a linha continuam visiveis; ao ocultar o ponto, o disco do halo pode continuar visivel.

Em JMA/T3, o grupo **Halo** controla separadamente o radar da ponta, com cores fixas opcionais e transparencia independente. Os aneis desvanecem conforme o pulso; transparencia inicial zero nao os mantem opacos durante todo o ciclo. A animacao depende de ticks.

O TradingView usa tamanho relativo em `plot.style_circles`, e tamanho tipografico nos labels. Valores 1, 5 e 10 sao configuraveis, mas nao garantem diametros de 1, 5 e 10 pixels fisicos. A posicao das viradas JMA/T3 e suas regras de sinais foram preservadas.

## Verificacao

`python verify_cog_research.py` verifica as expressoes de entrada com um oraculo de cruzamento/confirmacao, cancelamento, filtros, ausencia de dados futuros e sincronizacao entre indicador e estrategia. Nao compila Pine. Compilacao e aparencia ainda precisam ser verificadas no editor TradingView.

Referencias: [plots e tamanhos](https://www.tradingview.com/pine-script-docs/visuals/plots/), [cores](https://www.tradingview.com/pine-script-docs/visuals/colors/), [ordens e stops](https://www.tradingview.com/pine-script-docs/concepts/strategies/), [DSMA](https://traders.com/Documentation/FEEDbk_docs/2018/07/TradersTips.html), [JMA publica](https://www.tradingview.com/script/nZuBWW9j-Jurik-Moving-Average/).
