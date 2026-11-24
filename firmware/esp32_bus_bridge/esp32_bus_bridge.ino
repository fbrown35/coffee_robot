/*
 * SO-ARM100 무선 브리지 (ESP32)
 * ------------------------------------------------------------
 * PC(LeRobot) ──WiFi TCP:8888──> ESP32 ──UART 1Mbps──> Feetech 버스 서보 드라이버 보드 ──> STS3215 x6
 *
 * - 프로토콜을 해석하지 않는 투명(transparent) 브리지. PC 쪽에서는 socat 으로 가상 시리얼 포트를 만들어
 *   LeRobot 이 평소처럼 "시리얼 포트"로 쓰게 함 (coffee_robot/wifi_serial.py 참고).
 * - Waveshare Bus Servo Adapter(A) 기준: 점퍼를 'B'(UART/ESP32) 위치로, ESP32 TX→보드 RX, RX→보드 TX, GND 공통.
 * - 연결이 끊기면(비상) 기본은 '현재 자세 유지'. RELAX_ON_DISCONNECT=1 이면 전 서보 토크 해제.
 *   (토크 해제는 팔이 떨어지므로 컵/머신에 부딪힐 수 있음 → 기본값 0 권장)
 * - Arduino IDE: 보드 "ESP32 Dev Module" (ESP32-S3 도 가능, 핀만 변경)
 */
#include <WiFi.h>
#include <ESPmDNS.h>
#include "secrets.h"

#define HOSTNAME            "coffee-arm"   // → coffee-arm.local
#define TCP_PORT            8888
#define BUS_BAUD            1000000
#define BUS_RX_PIN          16
#define BUS_TX_PIN          17
#define LED_PIN             2
#define RELAX_ON_DISCONNECT 0
#define BUF_SIZE            512

WiFiServer server(TCP_PORT);
WiFiClient client;
uint8_t buf[BUF_SIZE];

// Feetech 브로드캐스트(ID 0xFE) WRITE: Torque_Enable(주소 40) = 0
void relaxAllServos() {
  const uint8_t id = 0xFE, len = 4, instr = 0x03, addr = 40, val = 0;
  uint8_t chk = ~(uint8_t)(id + len + instr + addr + val);
  uint8_t pkt[] = {0xFF, 0xFF, id, len, instr, addr, val, chk};
  Serial2.write(pkt, sizeof(pkt));
  Serial2.flush();
}

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);              // 절전 끄기: 지연(latency) 크게 줄어듦
  WiFi.setHostname(HOSTNAME);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    digitalWrite(LED_PIN, !digitalRead(LED_PIN));
    delay(250);
  }
  digitalWrite(LED_PIN, LOW);
  Serial.printf("WiFi OK: %s\n", WiFi.localIP().toString().c_str());
  MDNS.begin(HOSTNAME);
  MDNS.addService("coffeearm", "tcp", TCP_PORT);
}

void setup() {
  pinMode(LED_PIN, OUTPUT);
  Serial.begin(115200);
  Serial2.setRxBufferSize(1024);
  Serial2.begin(BUS_BAUD, SERIAL_8N1, BUS_RX_PIN, BUS_TX_PIN);
  connectWifi();
  server.begin();
  server.setNoDelay(true);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWifi();
  }

  // 새 클라이언트 (한 번에 하나만 허용: 버스 충돌 방지)
  if (server.hasClient()) {
    WiFiClient incoming = server.available();
    if (client && client.connected()) {
      incoming.stop();
    } else {
      client = incoming;
      client.setNoDelay(true);       // Nagle 끄기
      while (Serial2.available()) Serial2.read();
      digitalWrite(LED_PIN, HIGH);
      Serial.println("client connected");
    }
  }

  if (client && client.connected()) {
    // PC → 서보
    int n = client.available();
    if (n > 0) {
      n = client.read(buf, min(n, BUF_SIZE));
      Serial2.write(buf, n);
    }
    // 서보 → PC (응답 패킷을 모아서 한 번에 보냄)
    n = Serial2.available();
    if (n > 0) {
      delayMicroseconds(150);        // 같은 패킷의 남은 바이트가 도착하도록 잠깐 대기
      n = Serial2.read(buf, min(Serial2.available(), BUF_SIZE));
      client.write(buf, n);
    }
  } else if (client) {
    client.stop();
    digitalWrite(LED_PIN, LOW);
    Serial.println("client disconnected");
#if RELAX_ON_DISCONNECT
    relaxAllServos();
#endif
  }
}
