# Inferidor de falhas em motor

Aplicativo independente (janela, tkinter): carrega um modelo e mostra, em tempo real, qual é a falha do motor. Não depende
do coletor, do simulador nem do notebook; só precisa do arquivo do modelo.

## Rodar

Dê dois cliques em `run.bat` (cria o `.venv`, instala as dependências e abre a janela).

1. **Modelo:** o botão *Carregar outro modelo (.joblib)* abre qualquer arquivo, mesmo com o sensor transmitindo; o
   último escolhido fica lembrado (`inferidor.json`). Na primeira vez abre o primeiro `.joblib` de `modelos/` (vem com
   `rf_falhas.joblib`). Um arquivo inválido (não é um modelo deste projeto, ou usa features que o inferidor não calcula) é
   recusado e o modelo atual continua valendo. A barra lateral mostra o algoritmo, o treino, as entradas, as classes e o
   peso de cada grupo de features.
2. **Iniciar escuta:** o inferidor passa a ser o servidor do sensor (no lugar do coletor). Aponte o ESP32 ou o simulador
   para a URL mostrada (`ws://<ip deste PC>:8766/ws/device`). No simulador, é o campo de URL ao lado de *Conectar*.
3. **Rotação aproximada:** informe o rpm do motor (1200, 1800, 2700...). O modelo trabalha em ordens da rotação e precisa
   saber onde procurar o 1×.
4. Em ~6 s aparece o diagnóstico: falha atual, probabilidade por classe, linha do tempo dos últimos 2 min, onda e espectro
   (com as marcas 0,5×, 1×, 2×, 3×, 4×).

Não rode junto com o coletor na mesma porta (o coletor usa 8765, o inferidor 8766). Fecha pelo botão da janela ou com
Ctrl+C no terminal.

Opções de linha de comando: `--modelo arquivo.joblib`, `--porta 8766`, `--rpm 1800`, `--iniciar` (já começa escutando).

## Como decide

- A cada 1 s classifica a última janela de 2 s (mesmas features usadas no treino).
- Média das últimas N probabilidades (controle *Média de janelas*) e **INCERTO** quando a maior probabilidade fica abaixo
  do *Limiar de confiança*.
- Janelas que cruzam perda de pacotes são puladas.
- Mais lento para reagir que uma janela só (2 a 3 s), em troca de menos oscilação.

## Observações

- `inferidor.py` é um arquivo só. As funções de features são **cópia** de `analysis/vibfeatures.py`; se mudar lá, mude aqui
  (conferido: diferença 0,0 na mesma janela).
- `scikit-learn` está fixado em 1.9.1, a versão que salvou o modelo; outra versão pode não abrir o `.joblib`.
- O modelo que acompanha foi treinado só com dados **simulados**. Com o motor real, treine de novo (`analysis/analise.ipynb`)
  e carregue o novo `.joblib`.
