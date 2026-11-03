# Simulador de vibração de motor

Faz o papel do ESP32 + LSM6DS3 enquanto não há motor: gera o sinal de um acelerômetro de 3 eixos montado num motor
elétrico (com ou sem falhas) e o envia ao coletor pelo mesmo WebSocket e protocolo do firmware. Tem interface gráfica
para ligar falhas e ver o sinal, e um gerador de dataset que escreve gravações no formato do coletor sem esperar o
tempo real.

## Rodar

Dê dois cliques em `run.bat` (cria o `.venv`, instala `numpy`, `scipy`, `websockets` e abre a janela). Com o coletor
aberto (`collector\run.bat`), clique em **Conectar**: o dispositivo `sim-motor` aparece no coletor e você grava como
se fosse o ESP. O quadro **Rótulo para digitar no coletor** mostra o nome da classe para o estado atual.

Sem interface (testes e scripts):

```powershell
.venv\Scripts\python -m motorsim --headless --unbalance 0.6 --seconds 60      # desbalanceamento 60 %
.venv\Scripts\python -m motorsim --headless --looseness 0.8 --drop 0.02       # folga, 2 % de pacotes perdidos
```

Se a porta 8765 do coletor estiver ocupada por outra coisa, o simulador acaba falando com quem estiver lá. Confira
o IP/porta no campo de URL.

## O que é simulado

| Camada | Detalhe |
|---|---|
| Rotor | rpm por inversor (600–6000) ou rede 60 Hz (indução 4 polos, escorregamento ∝ carga); inércia e flutuação lenta de velocidade (picos largos como no real) |
| Estrutura | uma ressonância por eixo (X ≈ 200 Hz, Y ≈ 280, Z ≈ 400, ±12 % por montagem); amplitude varia com a rotação como numa excitação rotativa (~f⁴ abaixo da ressonância) |
| Saudável | 1× residual (menor com maior grau de balanceamento), 2×–4× pequenos, componente magnética em 2× a frequência de alimentação modulada pelo escorregamento, piso de ruído estrutural |
| **Peso preso ao eixo** (desbalanceamento) | 1× radial forte, órbita elíptica (rigidez vertical > horizontal), pouco axial. Severidade ≈ tamanho do peso: ~25 % = peso pequeno, ~80 % = peso grande |
| **Parafuso frouxo** (folga) | harmônicos 2×–8×, sub-harmônicos 0,5× 1,5× 2,5× que ligam e desligam, impactos 1×/rot (2× se severa) excitando a ressonância da carcaça, piso de ruído maior |
| Calço sob o motor (desalinhamento, opcional) | 1× e 2× axiais, 2× radial, 3× e 4× (mistura angular/paralelo sorteada por montagem). Fica fora do dataset padrão |
| Sensor | gravidade projetada pela inclinação da montagem, offset e ganho por eixo, ruído branco ajustável, filtro anti-aliasing (520 Hz) com superamostragem 4×, ODR real ±1,5 % do nominal, quantização de 0,122 mg, saturação em ±4 g |
| Rede | perda de pacotes opcional (o `seq` avança e o coletor registra o buraco) |

Eixos: **X** radial horizontal, **Y** axial, **Z** radial vertical (gravidade). Severidade 0–100 %: a escala de amplitude
segue a ISO 10816-3 para motores pequenos (100 % ≈ 7 mm/s RMS ≈ 0,19 g de pico em 1× a 1800 rpm).

**Remontar sensor** sorteia uma nova *sessão*: ressonâncias, inclinação, offsets, ganhos, acoplamento por eixo, fases,
sensibilidade a cada falha e ODR real. Entre sessões o sinal muda como mudaria ao desmontar e remontar o sensor, e isso
é o que a validação por sessão da análise testa.

### Limites (leia antes de confiar nos resultados)

- É um modelo físico simplificado, **escrito sem calibrar com dados reais** (nenhum dataset público foi usado). As
  assinaturas seguem a literatura de análise de vibração (ISO 10816, tabelas de falhas por ordem), mas amplitudes e
  proporções são plausíveis, não medidas. Resultados de classificação sobre estes dados são **otimistas**.
- **Só falhas que dá para provocar ao vivo** (peso no eixo, parafuso frouxo, calço). Rolamentos não são simulados: o
  defeito de rolamento tem a assinatura principal em kHz, acima do que o LSM6DS3 a 1,66 kHz captura, e não dá para
  reproduzir na bancada de forma controlada.
- Para calibrar contra dados públicos, o candidato é o **MaFaulDa** (UFRJ), que tem desbalanceamento com massas
  conhecidas e desalinhamento em bancada; dá para comparar amplitudes por ordem e proporções entre eixos.

## Gerar dataset

```powershell
.venv\Scripts\python -m motorsim.dataset --sessions 5 --duration 60      # 5 classes × 3 velocidades × 5 sessões
```

Grava em `data\recordings\` (`.npy` int16 + `.json`, igual ao coletor, com `"source": "simulator"` e a verdade-terreno
em `"sim"`; **não use `sim` como feature**). Fica separado de `collector\data` de propósito, para não misturar com dados
reais. Classes padrão: `parado`, `normal`, `desbalanceado_leve` (peso pequeno), `desbalanceado_forte` (peso grande) e
`folga` (parafuso frouxo); velocidades `baixa` (1200 rpm), `media` (1800), `alta` (2700), com severidade, rpm exato e
carga sorteados por gravação. Use `--classes` (aceita também `desalinhado`), `--speeds` e `--seed` para variar.

## Código

- `motorsim/engine.py`: sinal (física, estrutura, falhas, cadeia do sensor). `Engine.read(n)` devolve n amostras `int16 (n, 3)`.
- `motorsim/link.py`: cliente WebSocket (protocolo do ESP) e laço em tempo real na taxa do sensor.
- `motorsim/gui.py`: interface (tkinter, sem dependências extras).
- `motorsim/dataset.py`: gerador offline.
