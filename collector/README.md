# Coletor de vibração

Ferramenta local (Windows) para coletar dados de acelerômetro enviados por um ESP32: recebe o sinal por
WebSocket, mostra forma de onda e espectro em tempo real e grava sessões rotuladas para treinar o modelo.

## Rodar

Precisa de Python 3.10+ (`winget install Python.Python.3.12`). Depois, dê dois cliques em `run.bat`
(ele cria o `.venv`, instala as dependências e inicia o servidor) e abra <http://localhost:8765>.

O terminal mostra o endereço que o ESP32 deve usar, algo como `ws://192.168.0.20:8765/ws/device`.
A porta padrão é 8765 (8000 costuma estar ocupada pelo Docker); mude com a variável `COLLECTOR_PORT`.
Se o ESP32 não conectar, libere a porta no firewall (PowerShell como administrador):

```powershell
netsh advfirewall firewall add rule name="Coletor vibracao" dir=in action=allow protocol=TCP localport=8765
```

Sem hardware, teste com o simulador (em outro terminal, dentro de `collector`):

```powershell
.venv\Scripts\python simulate.py --state unbalance --rpm 1800
```

Opções: `--state normal|unbalance|looseness|stopped`, `--drop 0.02` (perde 2% dos pacotes), `--seconds 30`.

## Protocolo do dispositivo — `ws://<ip-do-pc>:8765/ws/device`

1. Ao conectar, enviar **uma vez** uma mensagem de texto (JSON):

   ```json
   {"type":"hello","device":"esp32-wroom","fw":"0.1","fs":1600,"lsb_g":0.0039,"range_g":2}
   ```

   `fs` é a taxa em Hz, `lsb_g` é quantos g vale 1 LSB (ADXL345 full-res: 0,0039) e `range_g` é o fundo de
   escala (usado para detectar saturação).

2. Depois, mensagens **binárias** com pacotes de amostras (little-endian). Uma mensagem pode ter vários
   pacotes concatenados:

   | offset | tamanho | campo |
   |---|---|---|
   | 0 | 2 | magic `A5 5A` |
   | 2 | 2 | `seq` uint16, +1 a cada pacote (dá a volta em 65535) |
   | 4 | 1 | `count`, nº de amostras |
   | 5 | 1 | reservado (0) |
   | 6 | 6·count | `count` × (int16 x, int16 y, int16 z) |

   Os saltos em `seq` viram "pacotes perdidos" na interface e ficam registrados em cada gravação.
   Em C++, o cabeçalho é `struct __attribute__((packed)) { uint8_t m0=0xA5, m1=0x5A; uint16_t seq; uint8_t count, rsv; }`.

3. O servidor responde com texto JSON: `{"type":"welcome",...}` ao conectar e
   `{"type":"recording","active":true|false,"label":"..."}` quando uma gravação começa ou termina
   (útil para acender um LED). O dispositivo pode enviar `{"type":"ping"}` e recebe `{"type":"pong"}`.

O dispositivo transmite continuamente; gravar é decisão do servidor. Se reconectar, o servidor reinicia
os contadores do fluxo. Só um dispositivo por vez (uma nova conexão substitui a anterior).

## Dados gravados (`data/recordings/`)

Cada gravação gera dois arquivos com o mesmo nome (`<classe>_<velocidade>_s<sessão>_<data-hora>`):

- `.npy`: `int16`, shape `(n_amostras, 3)`, colunas x, y, z. Para g: `raw * lsb_g`.
- `.json`: metadados (classe, velocidade, sessão, notas, `fs`, `lsb_g`, duração, `trim_s`, `gaps`
  com os pacotes perdidos, `issues`, `quality`).

```python
import json, numpy as np
meta = json.load(open("data/recordings/<id>.json"))
g = np.load("data/recordings/<id>.npy").astype(np.float32) * meta["lsb_g"]
a, b = int(meta["trim_s"] * meta["fs"]), len(g) - int(meta["trim_s"] * meta["fs"])
g = g[a:b]          # trecho útil, sem a aceleração e a parada do motor
```

Ao treinar, divida treino/teste **por sessão** (`session`), nunca por janela, e descarte janelas que
cruzem um `gap`. Classes e velocidades novas digitadas no formulário são salvas em `data/config.json`
e passam a aparecer como sugestão nos campos.

## API HTTP

| método | rota | |
|---|---|---|
| GET | `/api/status` | estado do dispositivo e da gravação |
| GET/PUT | `/api/config` | classes, velocidades, metas |
| POST | `/api/recordings/start` | `{label, speed, session, notes, duration_s, delay_s, trim_s}` |
| POST | `/api/recordings/stop` · `/cancel` | salva / descarta |
| GET | `/api/recordings` | lista |
| PATCH/DELETE | `/api/recordings/{id}` | corrige rótulo/notas · apaga |
| GET | `/api/recordings/{id}/download` · `/preview` | `.npy` · RMS, trecho e espectro |
| WS | `/ws/ui` | dados ao vivo para a página |

Documentação interativa em <http://localhost:8765/docs>.
