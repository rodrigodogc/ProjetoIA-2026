#include "coletor.h"
#include <WiFi.h>
#include <ESPmDNS.h>
#include <LittleFS.h>
#include <Preferences.h>
#include <ESPAsyncWebServer.h>
#include <WebSocketsServer.h>
#include "configuracao.h"
#include "lsm6ds3.h"

namespace coletor {

constexpr int HDR = 6;                // A5 5A | seq u16 | count u8 | 0
// Juntamos BLOCOS × COUNT amostras (128 = ~13 msg/s) em cada pacote: menos chamadas de envio.
constexpr int BLOCOS = 8;
constexpr int AMOSTRAS = BLOCOS * COUNT;
constexpr int PKT = HDR + AMOSTRAS * 6;
static uint8_t pkt[PKT];
static int blocos = 0;                // blocos de COUNT amostras já copiados para pkt
static uint16_t seq = 0;

static AsyncWebServer http(80);             // página estática e API
// O stream usa o servidor WebSocket do links2004 (porta 81), não o AsyncWebSocket: em teste a fila do
// AsyncWebSocket travava depois de ~40-80 s de stream (mensagens paradas com a janela TCP livre).
static WebSocketsServer wss(WS_PORTA);
static Preferences prefs;
static String cfgSsid, cfgPass;       // salvos na flash (NVS); padrão vem de configuracao.h
static volatile uint32_t reconectarEm = 0;   // millis() em que o loop() troca de rede (0 = nada pendente)

static void onWs(uint8_t num, WStype_t type, uint8_t *, size_t) {
  if (type == WStype_CONNECTED) {
    char hello[160];
    snprintf(hello, sizeof hello,
             "{\"type\":\"hello\",\"device\":\"esp32c3-lsm6ds3\",\"fw\":\"0.2\",\"fs\":%.0f,\"lsb_g\":%.6f,\"range_g\":%.0f}",
             FS_HZ, LSB_G, RANGE_G);
    wss.sendTXT(num, hello);
    Serial.printf("navegador conectado (%d)\n", wss.connectedClients());
  } else if (type == WStype_DISCONNECTED) {
    Serial.println("navegador desconectado");
  }
}

static String jsonStr(const String &s) {
  String o = "\"";
  for (char c : s) {
    if (c == '"' || c == '\\') { o += '\\'; o += c; }
    else if ((uint8_t)c >= 0x20) o += c;
  }
  return o + '"';
}

static void apiRedeGet(AsyncWebServerRequest *r) {
  bool ok = WiFi.status() == WL_CONNECTED;
  String j = "{\"ssid\":" + jsonStr(cfgSsid) + ",\"conectado\":" + (ok ? "true" : "false") +
             ",\"ip\":" + jsonStr(ok ? WiFi.localIP().toString() : "") +
             ",\"ap_ssid\":" + jsonStr(AP_SSID) + ",\"ap_ip\":" + jsonStr(WiFi.softAPIP().toString()) + "}";
  r->send(200, "application/json", j);
}

static void apiRedePost(AsyncWebServerRequest *r) {
  String ssid = r->hasParam("ssid", true) ? r->getParam("ssid", true)->value() : "";
  String pass = r->hasParam("pass", true) ? r->getParam("pass", true)->value() : "";
  ssid.trim();
  if (ssid.isEmpty()) {
    r->send(400, "application/json", "{\"detail\":\"SSID é obrigatório\"}");
    return;
  }
  bool mudou = ssid != cfgSsid || (!pass.isEmpty() && pass != cfgPass) || WiFi.status() != WL_CONNECTED;
  if (!pass.isEmpty()) cfgPass = pass;   // senha vazia mantém a anterior
  cfgSsid = ssid;
  prefs.putString("ssid", cfgSsid);
  prefs.putString("pass", cfgPass);
  // Só mexe no WiFi se algo mudou, e 1,5 s depois: derrubar o link agora atropelaria a resposta HTTP deste POST.
  if (mudou) reconectarEm = millis() + 1500 | 1;
  r->send(200, "application/json", "{\"ok\":true}");
}

void begin() {
  prefs.begin("coletor", false);
  cfgSsid = prefs.getString("ssid", WIFI_SSID);
  cfgPass = prefs.getString("pass", WIFI_PASS);

  WiFi.mode(WIFI_AP_STA);
  WiFi.setSleep(false);               // sem economia de energia: menos atraso no envio
  WiFi.setHostname(MDNS_NOME);
  // mDNS ANTES do softAP/begin: o IDF só habilita a interface do AP/STA se o mDNS já estiver de pé nos eventos
  if (MDNS.begin(MDNS_NOME)) {
    MDNS.addService("http", "tcp", 80);
    Serial.println("mDNS: " MDNS_NOME ".local");
  }
  WiFi.softAP(AP_SSID, AP_PASS);
  Serial.printf("AP '%s' em %s\n", AP_SSID, WiFi.softAPIP().toString().c_str());

  if (!LittleFS.begin(true)) Serial.println("LittleFS: falha ao montar");
  pkt[0] = 0xA5;
  pkt[1] = 0x5A;
  pkt[4] = AMOSTRAS;
  pkt[5] = 0;

  http.on("/api/rede", HTTP_GET, apiRedeGet);
  http.on("/api/rede", HTTP_POST, apiRedePost);
  if (LittleFS.exists("/index.html")) {
    http.serveStatic("/", LittleFS, "/").setDefaultFile("index.html").setCacheControl("no-cache");
  } else {
    Serial.println("index.html ausente: rode 'pio run -t uploadfs'");
    http.on("/", HTTP_GET, [](AsyncWebServerRequest *r) {
      r->send(200, "text/plain; charset=utf-8", "Interface nao gravada na flash. Rode: pio run -t uploadfs");
    });
  }
  http.begin();
  wss.begin();
  wss.onEvent(onWs);
  wss.enableHeartbeat(5000, 2000, 2);    // derruba navegador que sumiu sem fechar (~9 s)

  if (!cfgSsid.isEmpty()) {
    WiFi.begin(cfgSsid.c_str(), cfgPass.c_str());   // reconecta sozinho se cair
    for (int i = 0; i < 30 && WiFi.status() != WL_CONNECTED; i++) {   // até ~9 s
      delay(300);
      Serial.print('.');
    }
  }
  if (WiFi.status() == WL_CONNECTED)
    Serial.printf("\nWiFi OK, IP %s\n", WiFi.localIP().toString().c_str());
  else
    Serial.println("\nSem roteador: usando so o AP");
}

void loop() {
  wss.loop();
  if (reconectarEm && (int32_t)(millis() - reconectarEm) >= 0) {
    reconectarEm = 0;
    wss.disconnect();                 // fecha os navegadores de forma limpa ANTES de derrubar o link
    WiFi.disconnect();                // o AP continua no ar
    WiFi.begin(cfgSsid.c_str(), cfgPass.c_str());
  }
}

static uint8_t lentos[WEBSOCKETS_SERVER_CLIENT_MAX];   // envios lentos seguidos, por cliente

void enviar(const uint8_t *samples) {
  if (!wss.connectedClients()) { blocos = 0; seq++; return; }   // ninguém ouvindo: só conta o seq
  memcpy(pkt + HDR + blocos * COUNT * 6, samples, COUNT * 6);
  if (++blocos < BLOCOS) return;
  blocos = 0;
  pkt[2] = seq & 0xFF;
  pkt[3] = seq >> 8;
  seq++;
  // Um cliente por vez, medindo: o envio do links2004 BLOQUEIA até WEBSOCKETS_TCP_TIMEOUT quando o navegador não lê
  // (aba congelada, link que caiu sem avisar). Cliente lento 2 vezes seguidas é derrubado (a página reconecta sozinha):
  // o laço, que também esvazia a FIFO do sensor, não pode ficar parado por causa de um cliente.
  for (uint8_t n = 0; n < WEBSOCKETS_SERVER_CLIENT_MAX; n++) {
    if (!wss.clientIsConnected(n)) { lentos[n] = 0; continue; }
    uint32_t t = millis();
    bool ok = wss.sendBIN(n, pkt, PKT);
    uint32_t dt = millis() - t;
    lentos[n] = (!ok || dt > 150) ? lentos[n] + 1 : 0;
    if (lentos[n] >= 2) {
      Serial.printf("cliente %u lento/morto (%lu ms): desconectando\n", n, (unsigned long)dt);
      lentos[n] = 0;
      wss.disconnect(n);
    }
  }
}

void skipSeq() {                      // FIFO foi limpa: o bloco parcial não é contínuo com o próximo
  blocos = 0;
  seq++;
}

int clientes() { return wss.connectedClients(); }

}  // namespace coletor
