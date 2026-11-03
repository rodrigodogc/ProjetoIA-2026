#pragma once

// Rede do roteador (modo estação), opcional. Também dá para trocar pela página (botão "Rede").
// Se não conectar, o ESP segue só com o ponto de acesso.
#define WIFI_SSID   ""
#define WIFI_PASS   ""

// Ponto de acesso próprio do ESP (para ligar direto no notebook/celular). Senha com no mínimo 8 caracteres.
// A página fica em http://192.168.4.1 (ou http://sensor.local).
#define AP_SSID     "sensor-coleta"
#define AP_PASS     "12345678"

// o ESP responde em sensor.local
#define MDNS_NOME   "sensor"

// porta do WebSocket com as amostras (a página usa location.hostname:81)
#define WS_PORTA    81

// I2C do LSM6DS3
#define PIN_SDA 8
#define PIN_SCL 9
