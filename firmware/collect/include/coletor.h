#pragma once
#include <Arduino.h>

// Servidor da interface de coleta: arquivos estáticos em LittleFS (data/) + WebSocket /ws que transmite
// as amostras para o navegador (protocolo em collector/README.md). A gravação acontece no navegador.
namespace coletor {

constexpr int COUNT = 16;             // amostras por pacote

void begin();                         // sobe o AP, conecta no roteador, mDNS, HTTP e WebSocket
void loop();                          // chamar a cada iteração: tarefas de manutenção (reconexão, clientes mortos)
void enviar(const uint8_t *samples);  // COUNT × (int16 x,y,z) -> todos os navegadores conectados
void skipSeq();                       // pula um seq: o navegador registra o buraco
int  clientes();                      // navegadores conectados

}  // namespace coletor
