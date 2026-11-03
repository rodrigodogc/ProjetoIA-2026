#include "lsm6ds3.h"
#include <Wire.h>
#include "configuracao.h"

namespace imu {

constexpr uint8_t REG_WHO_AM_I = 0x0F, REG_CTRL1_XL = 0x10, REG_CTRL3_C = 0x12;
constexpr uint8_t REG_FIFO_CTRL1 = 0x06, REG_FIFO_CTRL2 = 0x07, REG_FIFO_CTRL3 = 0x08;
constexpr uint8_t REG_FIFO_CTRL4 = 0x09, REG_FIFO_CTRL5 = 0x0A;
constexpr uint8_t REG_FIFO_STATUS1 = 0x3A, REG_FIFO_DATA_L = 0x3E;

static uint8_t addr = 0;

static void writeReg(uint8_t reg, uint8_t v) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(v);
  Wire.endTransmission();
}

static bool readRegs(uint8_t reg, uint8_t *dst, uint8_t n) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(addr, n) != n) return false;
  for (uint8_t i = 0; i < n; i++) dst[i] = Wire.read();
  return true;
}

void fifoReset() {
  writeReg(REG_FIFO_CTRL5, 0x00);
  writeReg(REG_FIFO_CTRL5, 0x46);     // contínuo, 1,66 kHz, só acelerômetro
}

int fifoSamples(bool *overrun) {
  uint8_t s[2];
  if (!readRegs(REG_FIFO_STATUS1, s, 2)) return 0;
  *overrun = s[1] & 0x40;
  return (s[0] | ((s[1] & 0x0F) << 8)) / 3;   // palavras de 16 bits -> amostras de 3 eixos
}

bool readSamples(uint8_t *dst, int count) {
  // 16 amostras = 96 B, cabe no buffer do Wire (128 B); a FIFO avança sozinha a cada byte lido.
  return readRegs(REG_FIFO_DATA_L, dst, count * 6);
}

bool begin() {
  Wire.begin(PIN_SDA, PIN_SCL, 400000);
  for (uint8_t a : {0x6A, 0x6B}) {    // SA0 em GND = 0x6A, em 3V3 = 0x6B
    addr = a;
    uint8_t id = 0;
    if (!readRegs(REG_WHO_AM_I, &id, 1) || (id != 0x69 && id != 0x6A)) continue;
    Serial.printf("LSM6DS3 em 0x%02X (WHO_AM_I=0x%02X)\n", a, id);
    writeReg(REG_CTRL3_C, 0x01);      // reset
    delay(20);
    writeReg(REG_CTRL3_C, 0x44);      // BDU + auto-incremento de endereço
    writeReg(REG_CTRL1_XL, 0x88);     // acelerômetro: 1,66 kHz, ±4 g
    writeReg(REG_FIFO_CTRL1, 0x00);
    writeReg(REG_FIFO_CTRL2, 0x00);
    writeReg(REG_FIFO_CTRL3, 0x01);   // só acelerômetro na FIFO, sem decimação
    writeReg(REG_FIFO_CTRL4, 0x00);
    fifoReset();
    return true;
  }
  return false;
}

void selfCheck() {
  constexpr int N = 16;
  uint8_t buf[N * 6];
  delay(100);
  bool over;
  if (fifoSamples(&over) < N || !readSamples(buf, N)) {
    Serial.println("Autoteste: FIFO sem dados");
    return;
  }
  const int16_t *s = (const int16_t *)buf;
  float sum = 0;
  for (int i = 0; i < N; i++) {
    float x = s[3 * i], y = s[3 * i + 1], z = s[3 * i + 2];
    sum += sqrtf(x * x + y * y + z * z) * LSB_G;
  }
  float m = sum / N;
  Serial.printf("Autoteste: |a| medio = %.2f g (esperado ~1 g)%s\n", m, (m < 0.6f || m > 1.4f) ? "  <-- SUSPEITO" : "");
}

}  // namespace imu
