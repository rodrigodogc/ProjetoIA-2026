// Coleta: ESP32-C3 + LSM6DS3 (I2C). O ESP serve a interface (LittleFS) e transmite as amostras por
// WebSocket para o navegador, que mostra, grava e baixa os dados (.npy + .json).
// O sensor amostra sozinho a 1,66 kHz e guarda na FIFO; aqui só esvaziamos a FIFO em pacotes de 16
// amostras e mandamos como estão (protocolo descrito em collector/README.md).
#include <Arduino.h>
#include "coletor.h"
#include "lsm6ds3.h"

void setup() {
  Serial.begin(115200);
  delay(1000);
  coletor::begin();                   // rede primeiro: o AP e a página sobem mesmo sem sensor
  while (!imu::begin()) {
    Serial.println("LSM6DS3 nao encontrado: confira fios (3V3, GND, SDA, SCL) e CS em 3V3");
    for (int i = 0; i < 200; i++) {   // ~2 s atendendo a manutenção da rede
      coletor::loop();
      delay(10);
    }
  }
  imu::selfCheck();
}

void loop() {
  coletor::loop();

  bool over = false;
  int samples = imu::fifoSamples(&over);
  if (over) {                         // perdeu amostras: limpa a FIFO e pula um seq para o navegador registrar o buraco
    imu::fifoReset();
    coletor::skipSeq();
    Serial.println("FIFO overrun");
    return;
  }

  uint8_t buf[coletor::COUNT * 6];
  while (samples >= coletor::COUNT) {
    if (!imu::readSamples(buf, coletor::COUNT)) break;   // x,y,z int16 little-endian, já no formato certo
    coletor::enviar(buf);
    samples -= coletor::COUNT;
  }
  delay(2);
}
