# Contexto do projeto

Projeto final da disciplina de IA: **detector de falhas em eixo de motor** por vibração (acelerômetro de 3 eixos).
Deve ser simples, mas "impactante". Idioma da conversa e das interfaces: português (pt-BR).
Última atualização: 01/11/2026.

> **Estratégia atual (mudou em nov/2026):** **não é mais TinyML.** O ESP32-C3 + LSM6DS3 são só um **sensor de
> vibração Wi-Fi**; os modelos de ML rodam em **Python no Windows**. Como **ainda não existe motor**, há um
> **simulador de vibração** (com interface gráfica) que se conecta ao coletor por WebSocket como se fosse o ESP, e uma
> pasta de **análise em Jupyter** sobre os dados gerados. Tudo que era TinyML (int8, TFLM, `firmware/infer/`) foi abandonado.

## Entrega (enunciado: UFPE, DEE, Inteligência Artificial, Prof. Jeydson Lopes da Silva, Projeto Final 2026.2)

- Aplicação prática com as **ferramentas de IA vistas na disciplina** (o enunciado não lista quais; confirmar com o professor/ementa que classificadores como Random Forest/SVM/MLP se encaixam).
- **Relatório em forma de artigo** (template do professor em anexo, não está na pasta) com: Introdução (problema, conceitos, alternativas, proposta, justificativas), Metodologia, Apresentação dos Resultados, Análise dos resultados (pontos positivos/negativos, vantagens/desvantagens, **o que não foi feito**), Considerações Finais, Referências (ABNT completas).
- **Vídeo** de apresentação (seminário) cobrindo os mesmos tópicos. Critérios: qualidade e clareza da apresentação, texto + referências, conhecimento do assunto.
- Implicação: os resultados sobre dados **simulados** precisam ser declarados como tal no artigo; coletar dados reais com o motor fortalece muito a seção de resultados. O notebook já segue a ordem do artigo e documenta limitações.

## Hardware e ambiente

- **Sensor:** ESP32-C3 + **LSM6DS3** (I2C), só acelerômetro, 1,66 kHz, ±4 g. (O WROOM existe mas não é usado.) A Orange Pi Zero 3 (1 GB) não tem papel agora; poderia ser gateway/dashboard no futuro.
- **PC:** Windows 11, usuário `rodri`, Python 3.12.10. PlatformIO está instalado (extensão do VS Code, em `~/.platformio/penv/Scripts/pio.exe`).
- **Armadilhas do ambiente:**
  - A porta 8000 é do Docker; o coletor usa **8765**. **O usuário também roda o coletor nessa porta**: ao testar, use outra (`COLLECTOR_PORT=8799`) e outra pasta (`COLLECTOR_DATA`), senão o teste cai na instância dele (já aconteceu uma vez; ver "Incidentes").
  - `localhost` pode levar ~2 s no Windows; use `127.0.0.1`.
  - `Set-Content` do PowerShell 5.1 sem `-Encoding utf8` corrompe acentos. Processos iniciados em segundo plano pelo venv deixam o filho órfão (usar `run_in_background` com término próprio, p. ex. `os._exit` por timer).
  - `pip` escreve avisos no stderr; o PowerShell os trata como erro (ignorar).

## Estrutura

```
Projeto_IA/
├─ context.md                  este arquivo
├─ Projeto IA 2026.2.pdf       enunciado da disciplina (lido em 01/11/2026; resumo na seção "Entrega")
├─ collector/                  coletor Windows (FastAPI + WebSocket + frontend) — testado
├─ firmware/collect/           firmware do sensor que serve o próprio coletor (LittleFS) — compilado e testado em hardware
├─ simulator/                  simulador de motor com GUI + gerador de dataset — testado
├─ analysis/                   análise e classificação em Jupyter — executada sobre dados simulados
└─ inferidor/                  app com janela que mostra a falha ao vivo (servidor do sensor) — testado com o simulador
```

**Regra do usuário: cada aplicação (coletor, simulador, inferidor) é 100 % standalone**: pasta própria, `run.bat`, `.venv` e `requirements.txt` próprios, sem importar código das outras. O que é compartilhado é cópia (ex.: as features do inferidor), nunca import.

### `collector/`

- Executar: `run.bat` (ou `.venv\Scripts\python run.py`) → <http://localhost:8765>. Variáveis: `COLLECTOR_PORT`, `COLLECTOR_DATA`.
- Dispositivo conecta em `ws://<ip-do-pc>:8765/ws/device` (um por vez; nova conexão substitui a anterior!).
- Protocolo: texto JSON `hello` `{"type":"hello","device","fw","fs","lsb_g","range_g"}`; depois binário little-endian `A5 5A | seq u16 | count u8 | 0 | count × (int16 x,y,z)`. Perda de pacote = salto de `seq`. O servidor responde `welcome` e `recording` (ativo/inativo).
- Grava `.npy` int16 `(n,3)` + `.json` (`fs`, `lsb_g`, `label`, `speed`, `session`, `trim_s`, `gaps`, `issues`, `quality`...) em `data/recordings/`. Frontend: ondas e espectro ao vivo, formulário de gravação, tabela com visualização/download/exclusão. Cards de cobertura e checklist foram removidos a pedido (ferramenta simples).
- As 4 gravações `teste_*` do usuário não existem mais em `collector/data/recordings/` (pasta vazia em 01/11/2026; o usuário as removeu).
- Coletas simuladas em tempo real (simulador → coletor real, 01/11/2026), separadas em pastas irmãs de `recordings/` (o coletor e `vibfeatures.load_recordings` só leem uma pasta, sem subpastas, então elas não aparecem na UI do coletor; para analisar, aponte `DATA_DIR` para a pasta):
  - `collector/data/teste_rapido_45x20s/`: 45 gravações de 20 s (5 classes × 3 velocidades × sessões 1–3).
  - `collector/data/completa_75x60s/`: 75 gravações de 60 s, 75 min (5 classes × 3 velocidades × sessões 4–8, ordem embaralhada por sessão). Todas `quality=ok`, 0 pacotes perdidos.
  - Nas duas, `notes` = "simulado em tempo real"; não têm `source` nem `sim` nos metadados (diferente de `simulator/data/recordings`). Não misturar com dados reais sem separar.
  - `recordings/` ficou vazia para as próximas coletas.

### `firmware/collect/`

**Compilado e testado em hardware em 03/11/2026** (ESP32-C3 na COM3; PlatformIO fica em `~/.platformio/penv/Scripts/pio.exe`, não está no PATH). Estrutura: `include/` (`configuracao.h`, `coletor.h`, `lsm6ds3.h`), `src/` (`main.cpp`, `coletor.cpp`, `lsm6ds3.cpp`), `data/` (interface web, vai para o LittleFS com `pio run -t uploadfs`) e `README.md` próprio.

**Arquitetura nova: o ESP é SERVIDOR e serve o próprio coletor.** Não conecta mais em ninguém. Rede WIFI_AP_STA: AP `sensor-coleta` (192.168.4.1) + roteador (IP no log serial; era 192.168.1.9) + mDNS `sensor.local`. Porta 80 (`ESPAsyncWebServer`): `data/index.html|app.js|style.css` e `/api/rede` (GET/POST, SSID/senha na NVS; o botão "Rede" da página usa isso). Porta **81** (`links2004/WebSockets`, `WebSocketsServer`): stream binário no mesmo protocolo do coletor, só que com `count` = **128** amostras por pacote (~13 pacotes/s). `data/app.js` faz no navegador o que o `collector/` Python fazia: FFT/espectro, contagem de perdas, gravação e geração de `<id>.npy` + `<id>.json` (mesmo formato). **Nada é baixado automaticamente** (pedido do usuário): as gravações ficam no IndexedDB do aparelho (sobrevivem a recarregar; testado no hardware real) e o download é pelos botões `.npy`/`.json` da lista. Não há gravações persistentes no ESP nem em disco; a persistência é o **Google Drive** (abaixo).

**Interface para celular** (03/11/2026): CSS responsivo (≤700 px: gravação no topo, alvos de toque de 44 px, tabela vira cartões, diálogos em tela cheia). Validada em captura de `iframe` de 390 px (o Edge headless não renderiza janela < 500 px: **não use `--window-size` pequeno para testar mobile**, use iframe). Bug corrigido: `grid-template-columns: 1fr` alargava a página; precisa de `minmax(0, 1fr)`.

**Google Drive** (`firmware/collect/drive/`, `Code.gs` + `LEIA-ME.md`): a página é HTTP, então não dá OAuth (exige HTTPS). Solução: **Google Apps Script** publicado na conta do usuário (implantação "Qualquer pessoa", protegido por um `TOKEN` no corpo do POST; `FOLDER_ID` fica no script). A página faz POST `text/plain` (sem preflight CORS) com ações `ping|upload|list|get|delete`. Upload automático ao terminar a gravação (idempotente por id; `.npy` antes do `.json`), fila persistente em IndexedDB com retry a cada 20 s e no evento `online`, selos *só neste aparelho / na fila / enviando / no Drive*, lista mesclada local + Drive, "Ver"/".npy" baixam do Drive sob demanda, excluir = lixeira do Drive. Depois de enviada a gravação sai da memória do celular. **Limitação conhecida (apontada pelo usuário):** no Wi-Fi do sensor o celular fica sem internet, então o upload só ocorre com sensor e celular no mesmo roteador/hotspot; o IndexedDB é **por origem** (192.168.4.1 ≠ sensor.local ≠ IP do roteador), então uma fila feita num endereço só sobe naquele mesmo endereço. A página mostra "Drive · sem internet · N na fila". Ideia ainda não feita: o ESP como gateway de upload (celular no AP do sensor; o ESP, com internet pelo STA, repassa ao Apps Script por TLS em streaming). **Testado só contra emulação** (o `Code.gs` real rodando num mock de `DriveApp`/`Utilities`, ver pendência): **URL do script do usuário embutida como padrão** (`DRIVE_URL_PADRAO` em `data/app.js`); a senha nunca vem de fábrica: enquanto não houver senha (e o usuário não tiver escolhido "Não usar o Drive", guardado em `vc.driveSkip`), um popup a pede ao abrir a página, e o Drive só liga depois de salva. O resultado de "Testar conexão" é um selo **dentro** do diálogo (toast fica atrás do modal). Verificado em 03/11/2026 contra o script real publicado: responde a POST do navegador com CORS legível (`senha (token) inválida` para token falso), então a implantação "Qualquer pessoa" está correta; **upload/list/get/delete reais ainda não foram exercitados** (o token verdadeiro só o usuário tem). Dica de teste: dá para guiar o Edge headless por CDP (`--remote-debugging-port` + `WebSocket` nativo do Node) e emular celular com `Emulation.setDeviceMetricsOverride`; o ponto de maior risco real é o CORS da resposta do Apps Script após o redirect 302 (padrão conhecido, mas não verificado aqui).

**Armadilhas já resolvidas (não repetir):**
- `Serial` não existia: `ARDUINO_USB_CDC_ON_BOOT=1` exige também `-DARDUINO_USB_MODE=1`.
- `namespace link` colide com `link()` do POSIX; um `src/config.h` antigo ofuscava o `include/config.h` (aspas procuram na pasta do arquivo primeiro).
- O `AsyncWebSocket` (mathieucarbou, 3.6.0) **trava** depois de 40–80 s de stream: fila com 32 mensagens paradas e janela TCP livre (`space=5760`, `state=ESTABLISHED`). Protegê-lo contra fragmentação não resolveu. Por isso o stream usa o `WebSocketsServer` do links2004. Com ele: 150 s a 1649 Hz, 0 perdidos, e HTTP em paralelo não atrapalha.
- Mesmo sem travar, o `AsyncWebSocket` entrega só ~20 msg/s (espera ACK de cada mensagem): por isso pacotes de 128 amostras.
- **Salvar o Wi-Fi com a página aberta travava o stream** (relato do usuário: "após configurar o wifi o dispositivo não conecta", mas a página abria). Reproduzido no Brave via CDP: o `WiFi.disconnect()/begin()` derruba o link com o stream aberto, a conexão morre **sem FIN/RST** para o navegador, `onclose` nunca dispara e a página fica parada ("conectado" sem pacotes, ou "desconectado" sem retentar). Corrigido nos dois lados: **firmware** (só reconecta se SSID/senha mudaram; espera 1,5 s para a resposta do POST sair; `wss.disconnect()` antes de derrubar o link; `WEBSOCKETS_TCP_TIMEOUT=400` em vez de 5000 porque a escrita do links2004 é **bloqueante** e congelava o laço/FIFO com um cliente que não lê; envio cliente a cliente medindo o tempo e derrubando quem fica lento 2×; heartbeat 5 s/2 s/2) e **página** (`watchStream`: 4 s sem pacotes, 8 s gravando, ou handshake > 6 s => `ws.kill()` e reconecta; gravação interrompida é salva como `interrompida: dispositivo desconectou`, nunca perdida). Verificado: queda simulada com a página aberta => volta sozinha em ~9 s; queda durante gravação => salva com aviso. O cliente "zumbi" (handshake e não lê) sozinho NÃO travou o ESP por 60 s (a janela TCP do Windows demora a fechar). A rota de teste `/api/_bounce` foi removida.
- Abrir a porta serial com pyserial **reinicia a ESP-C3** (DTR/RTS): para monitorar sem resetar, `dtr=False; rts=False` antes de `open()`.

**Medido:** LSM6DS3 em **0x6B**, WHO_AM_I 0x69, autoteste |a| = 1,04 g (a leitura em rajada da FIFO funciona), taxa real 1649 Hz entregues / 1666 declarados, 0 overruns de FIFO. O erro `requestFrom ... Error -1` no boot é só a sondagem do 0x6A.

**Incompatibilidade a resolver:** `collector/` (Python), `inferidor/` e o `simulator/` esperam o ESP como **cliente** WebSocket (`ws://<pc>:PORTA/ws/device`); o firmware novo é servidor, então **não conecta mais neles**. Falta: ou o inferidor/coletor passam a conectar no ESP (`ws://sensor.local:81/`), ou o firmware ganha um modo cliente de volta. A interface web no ESP **não foi testada em navegador real** (só a lógica em Node + `.npy` lido com NumPy + stream com cliente Python).

### `simulator/`

- `run.bat` abre a GUI (tkinter; deps: numpy, scipy, websockets). **Conectar** envia ao coletor como o ESP (`sim-motor`). `python -m motorsim --headless ...` roda sem GUI. Modo `--shot` (dev) captura a janela.
- **Escopo das falhas (decisão do usuário, 01/11/2026): só falhas simples que dá para provocar ao vivo na bancada**, como amarrar um peso (maior ou menor) no eixo, ou afrouxar o parafuso de fixação. **Rolamentos foram removidos** de todo o projeto (simulador, GUI, features, notebook). Desalinhamento (calço sob o motor) existe no simulador mas fora do dataset padrão.
- GUI: sliders de severidade (peso preso ao eixo = desbalanceamento, parafuso frouxo = folga, calço = desalinhamento), presets (Normal, Parado, Peso pequeno, Peso grande, Parafuso frouxo, Calço), motor ligado/desligado, inversor (rpm 600–6000) ou rede 60 Hz, carga, ruído, perda de pacotes, **Remontar sensor** (nova sessão), rótulo sugerido para digitar no coletor, ondas dos 3 eixos, espectro com marcas 1×–4× (e 0,5×/1,5× na folga) e órbita X×Z.
- Modelo (`motorsim/engine.py`): rotor com inércia e flutuação; estrutura com ressonância por eixo (resposta de excitação rotativa, ~f⁴); 1× residual; componente elétrica em 2×f_alimentação modulada pelo escorregamento; assinaturas de falha por ordem (desbalanceamento: 1× radial/órbita elíptica; desalinhamento: 1× e 2× axiais, 2× radial; folga: harmônicos, sub-harmônicos intermitentes, impactos 1×/rot excitando a ressonância da carcaça); sensor com gravidade/inclinação, offset, ganho, ruído, anti-aliasing 520 Hz, ODR real ±1,5 %, quantização de 0,122 mg, saturação ±4 g. Eixos: X radial horizontal, Y axial, Z radial vertical. Amplitudes seguem ISO 10816-3 (100 % ≈ 7 mm/s RMS ≈ 0,19 g a 1800 rpm).
- **Sem calibração com dados reais**: nenhum dataset público foi baixado ou usado; parâmetros vêm da literatura de análise de vibração. Candidato para calibrar depois: MaFaulDa (UFRJ; desbalanceamento com massas conhecidas). Resultados sobre o simulado são **otimistas**.
- Gerador: `python -m motorsim.dataset --sessions 5 --duration 60` → `simulator/data/recordings/` (formato do coletor + `"source":"simulator"` e verdade-terreno em `"sim"`, que **não** deve virar feature). Existem **75 gravações** (5 classes × 3 velocidades × 5 sessões × 60 s, ~43 MB): `parado, normal, desbalanceado_leve` (peso pequeno)`, desbalanceado_forte` (peso grande)`, folga` (parafuso frouxo); `baixa`≈1200, `media`≈1800, `alta`≈2700 rpm. Cada sessão = uma montagem do sensor. `--classes desalinhado` inclui o calço.

### `analysis/`

- `run.bat` abre o JupyterLab em `analise.ipynb` (deps em `requirements.txt`, venv próprio). `vibfeatures.py` = carga + features (reutilizável ao vivo). `models/rf_falhas.joblib` = modelo final (ignorado pelo git).
- `DATA_DIR`/`SOURCE` na 1ª célula escolhem simulado (`../simulator/data/recordings`) ou real (`../collector/data/recordings`, `SOURCE=None`). `SPEED_BANDS_HZ` = faixa esperada de rotação por velocidade (no real, vem do setpoint do motor).

## Decisões de ML (justificativas completas no topo do notebook)

- **Algoritmo: Random Forest** (scikit-learn) sobre ~90 features espectrais. Desafiantes: regressão logística, SVM-RBF, Extra Trees, Gradient Boosting. Regra fixada antes dos resultados: vence o maior F1-macro em validação por sessão; empate dentro de 1 desvio → o mais simples/estável (RF). **Sem deep learning**: poucas sessões independentes, a rede decora a montagem do sensor; falhas de eixo têm assinatura conhecida.
- **Features em ordens da rotação** (0,5×…8×, razões 0,5×/1×, 2×/1×, 3×/1×), curtose/crest, bandas, relação axial/radial, `fr` (~80 features). Janela de 2 s, 50 % de sobreposição.
- **Validação: leave-one-session-out** (nunca por janela). Métricas: F1-macro, acurácia balanceada, matriz de confusão. Extras no notebook: recall por classe×velocidade, velocidade nunca vista, ablação por família de features, sem `fr`, ruído extra, **curva de aprendizado em nº de sessões**, suavização causal de N janelas, limiar de confiança ("incerto"), Isolation Forest só com "normal" e falha inédita por baixa confiança.
- **A rotação precisa ser informada** (faixa esperada pelo setpoint): estimativa cega é ambígua (0,5×/1×/2×); no simulado errou em folga (pega 0,5×) e, quando presente, desalinhamento (pega 2×).

## Resultados da análise (dados SIMULADOS; notebook executado, reproduzível: duas execuções deram números idênticos)

Dataset: 75 gravações, 5 sessões, 3 velocidades, 4125 janelas de 2 s (825 por classe), 78 features. Validação leave-one-session-out.

- **F1-macro (média ± desvio entre sessões):** Random Forest **0,918 ± 0,108** (pior sessão 0,71), SVM-RBF **0,918 ± 0,077** (pior 0,79), MLP 0,909 ± 0,104, regressão logística 0,903 ± 0,095, Gradient Boosting 0,895 ± 0,092, Extra Trees 0,882 ± 0,139. **Empate técnico RF/SVM**; pela regra pré-fixada ficou o **Random Forest** (SVM é a alternativa se os dados reais repetirem o padrão).
- **Onde acerta/erra:** `parado`, `normal` e `folga` 100 %. Todo o erro é a graduação do peso: `desbalanceado_leve` recall 0,75 (20 % viram normal; em baixa rotação 0,50), `desbalanceado_forte` 0,87. A amplitude do desbalanço cai ~f⁴ com a rotação, então peso leve em baixa rotação se confunde com o motor saudável (limite físico, não do algoritmo).
- **Suavização de N janelas não ajuda** (F1 0,922 → 0,925 com N = 15): erros são sistemáticos por sessão. Limiar de confiança serve para o "incerto".
- **Velocidade nunca vista:** F1 0,48–0,67 (o modelo não extrapola) → treinar com todas as velocidades.
- **Ruído extra:** treinado limpo, 0,92 → 0,84 (+5 mg) → **colapsa para 1 classe** (0,067) com +15 mg. Com augmentation de ruído: 0,88–0,90 em todos os níveis.
- **Sessões no treino (curva de aprendizado):** 0,80 (1) → 0,87 (2) → 0,89 (3) → 0,91 (4), ainda subindo → **≥ 4–5 sessões com remontagem** na coleta real.
- **Importância por grupo:** bandas absolutas (0,12), tempo/curtose (0,11), razões entre ordens (0,09); o modelo usa níveis absolutos (daí a sensibilidade a ruído/ganho). Sem `fr`: 0,898.
- **Anomalia (Isolation Forest só com `normal`):** AUROC folga 1,00, peso forte 0,91, peso leve 0,76. **Falha inédita** pela baixa confiança: folga 0,97, leve 0,93, forte 0,54.
- **Custo:** 1 janela de 2 s = ~30 ms (features + modelo), 1,5 % do tempo real; treino ~1 s. Modelo em `analysis/models/rf_falhas.joblib`.
- **Ressalvas:** dados simulados = otimistas; só 5 sessões (desvio grande); rotação precisa ser informada (a estimativa cega erra −50 % na folga).

## Incidentes e cuidados

- Em 01/11/2026 meu teste de ponta a ponta caiu no coletor que o usuário já tinha rodando na 8765 (meu servidor não conseguiu subir e o simulador conectou no dele). Isso pode ter **derrubado a conexão do ESP real dele** (nova conexão substitui a anterior) e criou 1 gravação de teste, **já apagada**. Não resta nada meu em `collector/data/recordings/`.
- O dataset sintético foi movido para `simulator/data/` para não se misturar com dados reais.

## Pendências e próximos passos

1. ~~Compilar o firmware e conferir autoteste e taxa~~ **feito** (03/11/2026, ver `firmware/collect/`). Agora: publicar o Apps Script do Drive (`firmware/collect/drive/LEIA-ME.md`) e testar a conexão de verdade; abrir a interface do ESP em um navegador/celular real (<http://sensor.local> ou o IP do roteador), gravar uma sessão curta e conferir o `.npy`; e decidir a incompatibilidade ESP-servidor × inferidor/coletor-Python.
2. Comprar/montar o motor; coletar de verdade (≥ 3–4 sessões com remontagem do sensor, 3 velocidades, classes do simulador viáveis na bancada) e rodar o notebook com `DATA_DIR` apontando para `collector/data/recordings`.
3. Registrar o rpm (ou a faixa) de cada gravação; hoje o coletor só guarda um rótulo de velocidade.
4. Calibrar o simulador com MaFaulDa/CWRU se quiser medir quanto os resultados simulados superestimam.
5. ~~Classificador ao vivo~~ **feito**: `inferidor/` (app com janela tkinter, arquivo único `inferidor.py`, `modelos/rf_falhas.joblib` copiado, venv próprio com scikit-learn fixado em 1.9.1). Duas versões anteriores foram descartadas a pedido do usuário (uma lia o `/ws/ui` do coletor e era complexa; a seguinte era só console, sem interface, e o Ctrl+C não fechava). É um **servidor WebSocket** no protocolo do coletor (porta 8766): o ESP/simulador conecta nele no lugar do coletor, sem coletor. Janela de 2 s a cada 1 s, rotação procurada em ±25 % de `--rpm` num buffer de até 10 s, média causal de N janelas (padrão 3), "incerto" abaixo do limiar (padrão 60 %); perda de pacotes invalida a janela. Tela: diagnóstico grande, barras de probabilidade, linha do tempo de 2 min, onda e espectro. As features são **cópia** de `vibfeatures.py` (diferença 0,0 conferida); se mudar uma, mude a outra. Fecha pelo botão ou Ctrl+C (testado com sensor transmitindo; processo sai com `os._exit`). Modelo escolhido pela interface (botão "Carregar outro modelo", troca ao vivo sem derrubar o sensor; valida o arquivo; lembra o último em `inferidor.json`); barra lateral mostra detalhes do modelo (algoritmo, treino, famílias de features, classes, importância Gini por grupo). Um erro ao classificar não derruba a conexão do sensor (vira nota na tela). Testado só com o simulador: normal → forte → folga → parado → leve; peso leve fica "incerto" (~0,54), coerente com o recall 0,75 do notebook. Modelo treinado apenas com dados simulados.
6. Escrever o artigo (template do professor) e gravar o vídeo; confirmar com a ementa quais ferramentas de IA a disciplina cobriu e se falta algum paradigma que o professor espera ver (ex.: redes neurais, que já entram como desafiante MLP no notebook).
