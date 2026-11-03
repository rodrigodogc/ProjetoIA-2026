# Análise de dados e classificação de falhas

`analise.ipynb` carrega as gravações do coletor (ou do simulador), extrai features, compara algoritmos, escolhe e
valida o classificador, e salva o modelo final. Ele segue a ordem de um artigo: dados → sinal → método → resultados →
robustez → conclusões.

## Rodar

`run.bat` (cria o `.venv`, instala as dependências e abre o JupyterLab no notebook). Ou, no VS Code, abra
`analise.ipynb` e selecione o Python de `analysis\.venv`. O notebook entregue já está executado, então os resultados
aparecem sem rodar; para refazer, *Run All* (~10 min).

Dados: a primeira célula de código define `DATA_DIR` e `SOURCE`. Por padrão usa o dataset sintético de
`../simulator/data/recordings` (gere com `simulator\run.bat` ou `python -m motorsim.dataset`). Para dados reais, aponte
para `../collector/data/recordings` e use `SOURCE = None`; ajuste também `SPEED_BANDS_HZ` (faixa de rotação de cada
velocidade, vinda do setpoint do seu motor) e os nomes das classes.

## Estratégia (resumo; a justificativa completa está no topo do notebook)

- **Algoritmo: Random Forest** sobre features espectrais; desafiantes: regressão logística, SVM-RBF, MLP, Extra Trees,
  Gradient Boosting. Regra fixada antes dos resultados: ganha o maior F1-macro em validação por sessão; empate dentro de
  1 desvio-padrão → o mais simples e estável. Sem deep learning: poucas sessões independentes.
- **Features:** amplitudes nas ordens da rotação (0,5×–8×) e suas razões, curtose/crest, bandas, relação
  axial/radial (~80 no total). Janela de 2 s, 50 % de sobreposição.
- **Escopo:** só falhas que dá para provocar na bancada (peso no eixo, leve ou forte; parafuso frouxo). Sem rolamentos.
- **Validação:** leave-one-session-out. Sessão = uma montagem do sensor; é o que mede generalização para uma remontagem
  nova. Nunca dividir por janela.
- **Decisão ao vivo:** média causal de N janelas + limiar de confiança ("incerto") + detector de anomalia treinado só
  com "normal" para falhas inéditas.
- **Rotação:** deve ser informada (faixa esperada). Estimá-la só pelo espectro é ambíguo (0,5×/1×/2×).

## Resultados do notebook entregue (dados simulados)

F1-macro por sessão de teste: **Random Forest 0,918 ± 0,108**, SVM-RBF 0,918 ± 0,077, MLP 0,909, regressão logística 0,903,
Gradient Boosting 0,895, Extra Trees 0,882. Parado, normal e folga: 100 %; o erro está todo em distinguir o peso leve do motor
normal (recall 0,75; 0,50 em baixa rotação). Suavizar janelas não melhora; o modelo não extrapola para velocidade nunca vista
(F1 0,48–0,67); treinado só com dados limpos ele colapsa com ruído extra (+15 mg), o que *augmentation* resolve (0,88);
com 4 sessões no treino o F1 ainda sobe. Uma janela leva ~30 ms. Detalhes, gráficos e a justificativa de cada escolha estão no notebook.

## Arquivos

- `analise.ipynb`: análise completa.
- `exemplo_coleta.ipynb`: análise curta (poucos minutos, já executada) sobre a coleta completa do simulador no coletor
  (`../collector/data/completa_75x60s`, 75 × 60 s): espectro em ordens, features, validação por sessão e matriz de
  confusão. F1-macro 0,89 ± 0,11 (pior sessão 0,69).
- O inferidor ao vivo é um aplicativo à parte: pasta `../inferidor/` (janela, standalone). Para usar um modelo novo, copie
  `models/rf_falhas.joblib` para `../inferidor/modelos/` ou use *Carregar modelo* nele.
- `vibfeatures.py`: carga das gravações, estimativa de rotação, janelas e features. É o mesmo código que deve rodar na
  classificação ao vivo.
- `models/rf_falhas.joblib`: modelo final com a lista de features e classes (gerado pelo notebook; não versionado).

## Ressalva sobre os resultados

Os números do notebook entregue vêm de dados **simulados**, que compartilham a física assumida pelas features. Servem
para validar o método e o pipeline, e são **otimistas** em relação a um motor real (ressonâncias, ruído e falhas reais são
mais bagunçados). No artigo, apresente-os como tal e substitua por dados reais assim que houver motor.
