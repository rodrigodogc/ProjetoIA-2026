#pragma once
#include <Arduino.h>

// LSM6DS3: acelerômetro a 1,66 kHz, ±4 g, amostrando sozinho na FIFO interna.
constexpr float FS_HZ   = 1666.0f;    // ODR de 1,66 kHz
constexpr float LSB_G   = 0.000122f;  // sensibilidade em ±4 g (0,122 mg/LSB)
constexpr float RANGE_G = 4.0f;

namespace imu {

bool begin();                                   // detecta 0x6A/0x6B e configura; false se não achou
void fifoReset();                               // bypass -> contínuo
int  fifoSamples(bool *overrun);                // amostras (x,y,z) completas na FIFO
bool readSamples(uint8_t *dst, int count);      // count × (int16 x,y,z) little-endian
void selfCheck();                               // sensor parado deve dar |a| ≈ 1 g

}  // namespace imu
