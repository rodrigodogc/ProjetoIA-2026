# Firmware de coleta (ESP32-C3 + LSM6DS3)

O ESP serve a própria interface de coleta. O navegador mostra forma de onda e espectro, grava e baixa
`<id>.npy` + `<id>.json` (mesmo formato de `collector/README.md`). Não precisa de PC rodando nada.

## Gravar

```
pio run -t upload      # firmware
pio run -t uploadfs    # interface (pasta data/) na flash (LittleFS)
```

Depois de mexer em `data/` só o `uploadfs` é necessário.

## Usar

- Celular/notebook no Wi-Fi **sensor-coleta** (senha em `include/configuracao.h`) e abrir <http://192.168.4.1>
  ou <http://sensor.local>.
- Ou pelo roteador: botão **Rede** na página grava SSID/senha na flash; o IP aparece na serial e no diálogo.

## Arquitetura

| Parte | Onde | Observação |
|---|---|---|
| Página e `/api/rede` | `ESPAsyncWebServer`, porta 80 | arquivos de `data/` servidos do LittleFS |
| Stream de amostras | `links2004/WebSockets`, porta 81 | pacotes binários de 128 amostras (~13/s) |
| Sensor | `src/lsm6ds3.cpp` | FIFO interna, ODR 1,66 kHz, ±4 g |
| Gravação, FFT, `.npy` | `data/app.js` (navegador) | o ESP não guarda sessões |

Por que o stream não usa o `AsyncWebSocket`: em teste a fila de envio travava depois de 40–80 s (mensagens paradas
com a janela TCP livre). Com o servidor do links2004: 150 s a 1649 Hz, 0 pacotes perdidos.

## Celular

A interface é responsiva: abaixo de 700 px a gravação vai para o topo, campos e botões ficam com tamanho de toque e a
tabela de gravações vira lista de cartões. Pelo celular, o mais simples é colocar celular e sensor no mesmo roteador
(botão **Rede**) para ter internet e falar com o sensor ao mesmo tempo.

## Google Drive

Envio automático e gerência das gravações numa pasta do Drive, via Google Apps Script que você publica na sua conta:
veja [`drive/LEIA-ME.md`](drive/LEIA-ME.md) e [`drive/Code.gs`](drive/Code.gs). O botão **Drive** da página guarda URL
e senha; sem internet a gravação fica numa fila (IndexedDB) e sobe depois.

Mantenha a aba aberta e a tela ligada durante a gravação (celular com a aba em segundo plano pode atrasar o stream).
