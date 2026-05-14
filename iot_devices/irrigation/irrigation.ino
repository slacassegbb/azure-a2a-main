#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <WebServer.h>
#include <Preferences.h>
#include <ArduinoOTA.h>
#include <time.h>
#include "mbedtls/base64.h"
#include "mbedtls/md.h"
#include <OneWire.h>
#include <DallasTemperature.h>
#include "HX711.h"
#include <Wire.h>
#include "Adafruit_seesaw.h"

// ===========================
// Wi-Fi
// ===========================
const char* ssid     = "Zig420";
const char* password = "hip1hops";

// ===========================
// Azure Blob config (same as vision device)
// ===========================
const char* AZURE_ACCOUNT_NAME = "a2astoragefilesa2a";
const char* AZURE_ACCOUNT_KEY  = "CS6udqgXa//vXxtg2oPUGiXrQooHaIPVNqsLD0g8WAO09dTBm4zHm0SCkMDSIRmpTbZBrOjg33q8+AStPTyYGw==";
const char* AZURE_CONTAINER    = "garden-images";
const char* AZURE_BLOB_NAME    = "irrigation-command.json";
const char* AZURE_API_VERSION  = "2023-11-03";

// ===========================
// Relay / Irrigation
// ===========================
#define RELAY_PIN 4
#define VALVE_A_PIN 5     // Relay CH2 — nitrogen valve
#define VALVE_B_PIN 7     // Relay CH3 — phosphorus valve
#define VALVE_C_PIN 8     // Relay CH4 — plain water valve
#define SEESAW_SDA_PIN 10  // SeeSaw I2C SDA
#define SEESAW_SCL_PIN 9   // SeeSaw I2C SCL (reusing old moisture pin)
#define LIGHT_DIM_PIN 15  // PWM output to Mean Well XLG-100 DIM+ wire
#define TEMP_PIN 6        // DS18B20 OneWire data pin
#define WEIGHT_DT_PIN 17   // HX711 #1 data pin
#define WEIGHT_SCK_PIN 16  // HX711 #1 clock pin
#define WEIGHT2_DT_PIN 13  // HX711 #2 data pin
#define WEIGHT2_SCK_PIN 12 // HX711 #2 clock pin
const unsigned long DEFAULT_IRRIGATION_MS = 120000; // 2-minute default
const unsigned long MOISTURE_READ_INTERVAL_MS = 5000; // read every 5 seconds
const unsigned long MOISTURE_UPLOAD_INTERVAL_MS = 300000; // upload to blob every 5 minutes
const char* MOISTURE_BLOB_NAME = "moisture-data.json";
const int MAX_MOISTURE_HISTORY = 576; // 48 hours at 5-min intervals

// ===========================
// Grow Light (TP-Link Kasa KP405 — with dimming)
// ===========================
const char* KASA_LIGHT_IP = "10.0.0.182";   // KP401 — hard on/off for grow light power
const int KASA_PORT = 9999;
const char* LIGHT_SCHEDULE_BLOB = "light-schedule.json";
const unsigned long LIGHT_SCHEDULE_POLL_MS = 60000;  // poll schedule blob every 60s
const unsigned long LIGHT_UPDATE_MS = 60000;         // update dimmer every 60s

// ===========================
// Fan (TP-Link Kasa KP401 — on/off)
// ===========================
const char* KASA_FAN_IP = "10.0.0.169";   // KP405 — fan with dimmer speed control
const char* FAN_COMMAND_BLOB = "fan-command.json";
const unsigned long FAN_POLL_MS = 30000;  // poll fan command blob every 30s

// ===========================
// Valve irrigation
// ===========================
const char* VALVE_COMMAND_BLOB = "valve-command.json";
const unsigned long VALVE_POLL_MS = 5000;  // poll every 5s (same as irrigation)

// ===========================
// Tare command
// ===========================
const char* TARE_COMMAND_BLOB = "tare-command.json";
String lastTareRequestId = "";

// ===========================
// Polling
// ===========================
const unsigned long POLL_INTERVAL_MS = 5000; // poll every 5 seconds

// ===========================
// NTP
// ===========================
const char* NTP_SERVER_1 = "pool.ntp.org";
const char* NTP_SERVER_2 = "time.nist.gov";

// ===========================
// State
// ===========================
Preferences prefs;
String lastRequestId   = "";
bool   isIrrigating    = false;
unsigned long irrigationStartMs = 0;
unsigned long irrigationDurationMs = DEFAULT_IRRIGATION_MS;
unsigned long lastPollMs        = 0;
unsigned long lastMoistureReadMs = 0;
int lastMoistureRaw = 0;
float smoothedMoisture = 0.0;  // Exponential moving average
bool moistureInitialized = false;
unsigned long lastMoistureUploadMs = 0;
String pendingEvents = "";  // JSON events to include in next moisture upload
const int MAX_EVENTS = 50;  // keep last 50 events

// ===========================
// Moisture history — circular buffer in RAM
// No blob download needed; buffer rebuilt as valid JSON each upload cycle.
// ===========================
struct MoistureReading {
  char ts[25];
  int  raw;
  int  pct;
  float temp_c;
  int  light;
  int  fan;
  float weight_g;
  float weight2_g;
};
static MoistureReading moistureHistory[MAX_MOISTURE_HISTORY];
static int moistureHead  = 0;  // next write slot
static int moistureCount = 0;  // valid entries (0 … MAX_MOISTURE_HISTORY)

// Light schedule state
String lastLightRequestId = "";
unsigned long lastLightSchedulePollMs = 0;
unsigned long lastLightUpdateMs = 0;
int currentBrightness = -1;  // -1 = unknown, track to avoid redundant Kasa commands
unsigned long lastKasaSuccessMs = 0;  // track last successful Kasa command
const unsigned long KASA_RESEND_MS = 300000;  // re-send Kasa command every 5 min as safety net

// Valve state
String lastValveRequestId = "";
unsigned long lastValvePollMs = 0;
bool valveIrrigating = false;
unsigned long valveIrrigationStartMs = 0;
unsigned long valveIrrigationDurationMs = 0;
int activeValvePin = -1;

// Fan state
String lastFanRequestId = "";
unsigned long lastFanPollMs = 0;
bool fanOn = false;
int fanSpeed = 100;  // current fan speed (1-100)
unsigned long fanAutoOffAtMs = 0;  // 0 = no timer, otherwise millis() at which to turn off
// Default schedule: sunrise 6am (30min ramp), full sun, sunset 8pm (30min ramp), off at night
int schedSunriseHour = 6;
int schedSunriseRampMin = 30;
int schedPeakBrightness = 100;
int schedSunsetHour = 20;
int schedSunsetRampMin = 30;
int schedNightBrightness = 0;

// Temperature sensor (DS18B20)
OneWire oneWire(TEMP_PIN);
DallasTemperature tempSensor(&oneWire);
float lastTempC = -127.0;  // -127 = no reading
unsigned long lastTempReadMs = 0;
const unsigned long TEMP_READ_INTERVAL_MS = 30000;  // read every 30s

WebServer server(80);

// ===========================
// Soil Moisture (Adafruit SeeSaw I2C)
// ===========================
Adafruit_seesaw soilSensor;
bool seesawReady = false;

// ===========================
// Weight Scale (HX711)
// ===========================
HX711 scale;
float lastWeightG = 0.0;
HX711 scale2;
float lastWeight2G = 0.0;
unsigned long lastWeightReadMs = 0;
const unsigned long WEIGHT_READ_INTERVAL_MS = 30000;  // read every 30s
const float WEIGHT_CALIBRATION = 636.0;  // calibrated: 6oz iPhone = 170g

void recordEvent(const String& type, const String& detail = "") {
  time_t now = time(nullptr);
  if (now < 1700000000) return;
  struct tm tmInfo;
  gmtime_r(&now, &tmInfo);
  char isoBuf[30];
  strftime(isoBuf, sizeof(isoBuf), "%Y-%m-%dT%H:%M:%SZ", &tmInfo);
  String entry = "{\"ts\":\"" + String(isoBuf) + "\",\"type\":\"" + type + "\"";
  if (detail.length() > 0) entry += ",\"detail\":\"" + detail + "\"";
  entry += "}";
  if (pendingEvents.length() > 0) pendingEvents += ",";
  pendingEvents += entry;
  Serial.println("[EVENT] " + type + (detail.length() ? " " + detail : ""));
}

// ── Relay helpers (active LOW) ──
void relayOn()  { digitalWrite(RELAY_PIN, LOW);  }
void relayOff() { digitalWrite(RELAY_PIN, HIGH); }

// ------------------------------------------------------------------
// Crypto / encoding helpers  (same as vision device)
// ------------------------------------------------------------------
String base64Encode(const uint8_t* input, size_t inputLen) {
  size_t outLen = 0;
  size_t bufLen = 4 * ((inputLen + 2) / 3) + 1;
  unsigned char* out = (unsigned char*)malloc(bufLen);
  if (!out) return "";
  if (mbedtls_base64_encode(out, bufLen, &outLen, input, inputLen) != 0) {
    free(out);
    return "";
  }
  String s = String((char*)out);
  free(out);
  return s;
}

bool base64Decode(const char* input, uint8_t* output, size_t outputSize, size_t& decodedLen) {
  return mbedtls_base64_decode(output, outputSize, &decodedLen,
                               (const unsigned char*)input, strlen(input)) == 0;
}

String hmacSha256Base64(const String& message, const char* base64Key) {
  uint8_t keyBytes[128];
  size_t keyLen = 0;
  if (!base64Decode(base64Key, keyBytes, sizeof(keyBytes), keyLen)) return "";

  uint8_t hmac[32];
  const mbedtls_md_info_t* mdInfo = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  if (!mdInfo) return "";
  if (mbedtls_md_hmac(mdInfo, keyBytes, keyLen,
                      (const unsigned char*)message.c_str(), message.length(),
                      hmac) != 0) return "";
  return base64Encode(hmac, sizeof(hmac));
}

String formatRfc1123(time_t rawTime) {
  struct tm tmInfo;
  gmtime_r(&rawTime, &tmInfo);
  char buf[40];
  strftime(buf, sizeof(buf), "%a, %d %b %Y %H:%M:%S GMT", &tmInfo);
  return String(buf);
}

bool syncClock() {
  // Eastern Time with automatic DST (EST/EDT)
  configTzTime("EST5EDT,M3.2.0,M11.1.0", NTP_SERVER_1, NTP_SERVER_2);
  Serial.print("Syncing clock");
  time_t now = time(nullptr);
  int retries = 0;
  while (now < 1700000000 && retries < 30) {
    delay(500);
    Serial.print(".");
    now = time(nullptr);
    retries++;
  }
  Serial.println();
  if (now < 1700000000) {
    Serial.println("Clock sync failed");
    return false;
  }
  Serial.print("UTC time: ");
  Serial.println(formatRfc1123(now));
  return true;
}

// ------------------------------------------------------------------
// Azure Blob – Shared Key GET
// ------------------------------------------------------------------
String buildGetAuthorization(const String& xMsDate,
                             const String& canonicalizedResource) {
  String stringToSign =
      "GET\n"
      "\n"                      // Content-Encoding
      "\n"                      // Content-Language
      "\n"                      // Content-Length (empty for GET)
      "\n"                      // Content-MD5
      "\n"                      // Content-Type
      "\n"                      // Date
      "\n"                      // If-Modified-Since
      "\n"                      // If-Match
      "\n"                      // If-None-Match
      "\n"                      // If-Unmodified-Since
      "\n"                      // Range
      "x-ms-date:" + xMsDate + "\n" +
      "x-ms-version:" + String(AZURE_API_VERSION) + "\n" +
      canonicalizedResource;

  String signature = hmacSha256Base64(stringToSign, AZURE_ACCOUNT_KEY);
  if (signature.length() == 0) return "";
  return "SharedKey " + String(AZURE_ACCOUNT_NAME) + ":" + signature;
}

String azureBlobUrl() {
  return "https://" + String(AZURE_ACCOUNT_NAME) +
         ".blob.core.windows.net/" +
         String(AZURE_CONTAINER) + "/" +
         String(AZURE_BLOB_NAME);
}

String azureBlobBaseUrl(const String& blobName) {
  return "https://" + String(AZURE_ACCOUNT_NAME) +
         ".blob.core.windows.net/" +
         String(AZURE_CONTAINER) + "/" + blobName;
}

String buildPutAuthorization(size_t contentLength,
                             const String& contentType,
                             const String& xMsDate,
                             const String& canonicalizedResource) {
  String stringToSign =
      "PUT\n"
      "\n"                      // Content-Encoding
      "\n"                      // Content-Language
      + String(contentLength) + "\n" +
      "\n"                      // Content-MD5
      + contentType + "\n" +
      "\n"                      // Date
      "\n"                      // If-Modified-Since
      "\n"                      // If-Match
      "\n"                      // If-None-Match
      "\n"                      // If-Unmodified-Since
      "\n"                      // Range
      "x-ms-blob-type:BlockBlob\n" +
      "x-ms-date:" + xMsDate + "\n" +
      "x-ms-version:" + String(AZURE_API_VERSION) + "\n" +
      canonicalizedResource;

  String signature = hmacSha256Base64(stringToSign, AZURE_ACCOUNT_KEY);
  if (signature.length() == 0) return "";
  return "SharedKey " + String(AZURE_ACCOUNT_NAME) + ":" + signature;
}

bool uploadJsonToBlob(const String& blobName, const String& jsonData) {
  time_t now = time(nullptr);
  if (now < 1700000000) return false;

  String url = azureBlobBaseUrl(blobName);
  String xMsDate = formatRfc1123(now);
  String canonicalizedResource =
      "/" + String(AZURE_ACCOUNT_NAME) +
      "/" + String(AZURE_CONTAINER) +
      "/" + blobName;

  String auth = buildPutAuthorization(
      jsonData.length(), "application/json", xMsDate, canonicalizedResource);
  if (auth.length() == 0) return false;

  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient http;
  if (!http.begin(client, url)) return false;

  http.addHeader("x-ms-date", xMsDate);
  http.addHeader("x-ms-version", AZURE_API_VERSION);
  http.addHeader("x-ms-blob-type", "BlockBlob");
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", auth);

  int code = http.PUT((uint8_t*)jsonData.c_str(), jsonData.length());
  http.end();
  return code == 201;
}

String downloadBlob(const String& blobName) {
  time_t now = time(nullptr);
  if (now < 1700000000) return "";

  String url = azureBlobBaseUrl(blobName);
  String xMsDate = formatRfc1123(now);
  String canonicalizedResource =
      "/" + String(AZURE_ACCOUNT_NAME) +
      "/" + String(AZURE_CONTAINER) +
      "/" + blobName;

  String auth = buildGetAuthorization(xMsDate, canonicalizedResource);
  if (auth.length() == 0) return "";

  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient http;
  if (!http.begin(client, url)) return "";

  http.addHeader("x-ms-date", xMsDate);
  http.addHeader("x-ms-version", AZURE_API_VERSION);
  http.addHeader("Authorization", auth);

  int code = http.GET();
  String body = "";
  if (code == 200) body = http.getString();
  http.end();
  return body;
}

// ------------------------------------------------------------------
// TP-Link Kasa protocol (XOR autokey cipher over TCP:9999)
// ------------------------------------------------------------------
bool kasaSend(const char* ip, const String& jsonCmd) {
  WiFiClient client;
  if (!client.connect(ip, KASA_PORT)) {
    Serial.println("[LIGHT] Kasa connect failed");
    return false;
  }

  // Encrypt with XOR autokey cipher
  uint16_t len = jsonCmd.length();
  uint8_t* buf = (uint8_t*)malloc(4 + len);
  if (!buf) { client.stop(); return false; }

  // 4-byte big-endian length header
  buf[0] = (len >> 24) & 0xFF;
  buf[1] = (len >> 16) & 0xFF;
  buf[2] = (len >> 8) & 0xFF;
  buf[3] = len & 0xFF;

  // XOR autokey cipher — ciphertext becomes the next key
  uint8_t key = 171;
  for (uint16_t i = 0; i < len; i++) {
    uint8_t plain = jsonCmd[i];
    uint8_t cipher = plain ^ key;
    buf[4 + i] = cipher;
    key = cipher;  // Next key is the ciphertext (autokey)
  }

  client.write(buf, 4 + len);
  free(buf);

  // Wait for response (with timeout)
  unsigned long start = millis();
  while (client.available() == 0 && millis() - start < 3000) {
    delay(10);
  }

  if (client.available()) {
    // Read and discard response (we don't need it for set commands)
    while (client.available()) client.read();
  }

  client.stop();
  return true;
}

bool setLightBrightness(int brightness) {
  // PWM dimming via Mean Well XLG-100-H-AB through LR7843 MOSFET module
  // Inverted: MOSFET HIGH pulls DIM low (dim), MOSFET LOW lets DIM float high (bright)
  // KP401 cuts power at 0% for true darkness (Mean Well can't go below ~8%)
  brightness = constrain(brightness, 0, 100);
  bool kasaOk = true;

  if (brightness == 0) {
    analogWrite(LIGHT_DIM_PIN, 255);  // dim to minimum first
    if (strlen(KASA_LIGHT_IP) > 0) {
      kasaOk = kasaSend(KASA_LIGHT_IP, "{\"system\":{\"set_relay_state\":{\"state\":0}}}");
    }
    Serial.println("[LIGHT] OFF (KP401 power cut)" + String(kasaOk ? "" : " — KASA FAILED"));
  } else {
    // Ensure KP401 is on whenever brightness > 0
    if (strlen(KASA_LIGHT_IP) > 0 && currentBrightness <= 0) {
      kasaOk = kasaSend(KASA_LIGHT_IP, "{\"system\":{\"set_relay_state\":{\"state\":1}}}");
      if (kasaOk) delay(500);
    }
    int pwmValue = map(brightness, 0, 100, 255, 0);  // inverted
    analogWrite(LIGHT_DIM_PIN, pwmValue);
    Serial.println("[LIGHT] PWM brightness: " + String(brightness) + "% (pwm=" + String(pwmValue) + ")");
  }
  return kasaOk;
}

void kasaSetFan(bool on, int speed = 100) {
  if (strlen(KASA_FAN_IP) == 0) return;
  if (on) {
    kasaSend(KASA_FAN_IP, "{\"system\":{\"set_relay_state\":{\"state\":1}}}");
    if (speed < 100) {
      delay(200);
      kasaSend(KASA_FAN_IP, "{\"smartlife.iot.dimmer\":{\"set_brightness\":{\"brightness\":" + String(speed) + "}}}");
      Serial.println("[FAN] Kasa ON at " + String(speed) + "%");
    } else {
      Serial.println("[FAN] Kasa ON at 100%");
    }
  } else {
    kasaSend(KASA_FAN_IP, "{\"system\":{\"set_relay_state\":{\"state\":0}}}");
    Serial.println("[FAN] Kasa OFF");
  }
}

// ------------------------------------------------------------------
// Light schedule — calculate target brightness based on current time
// ------------------------------------------------------------------
int calculateTargetBrightness() {
  time_t now = time(nullptr);
  if (now < 1700000000) return -1;  // clock not synced

  struct tm tmInfo;
  localtime_r(&now, &tmInfo);
  int nowMinutes = tmInfo.tm_hour * 60 + tmInfo.tm_min;

  int sunriseStart = schedSunriseHour * 60;
  int sunriseEnd = sunriseStart + schedSunriseRampMin;
  int sunsetStart = schedSunsetHour * 60;
  int sunsetEnd = sunsetStart + schedSunsetRampMin;

  if (nowMinutes < sunriseStart) {
    // Before sunrise — night
    return schedNightBrightness;
  } else if (nowMinutes < sunriseEnd) {
    // During sunrise ramp
    int elapsed = nowMinutes - sunriseStart;
    return schedNightBrightness + (schedPeakBrightness - schedNightBrightness) * elapsed / schedSunriseRampMin;
  } else if (nowMinutes < sunsetStart) {
    // Daytime — peak brightness
    return schedPeakBrightness;
  } else if (nowMinutes < sunsetEnd) {
    // During sunset ramp
    int elapsed = nowMinutes - sunsetStart;
    return schedPeakBrightness - (schedPeakBrightness - schedNightBrightness) * elapsed / schedSunsetRampMin;
  } else {
    // After sunset — night
    return schedNightBrightness;
  }
}

void updateLights() {
  if (millis() - lastLightUpdateMs < LIGHT_UPDATE_MS) return;
  lastLightUpdateMs = millis();

  int target = calculateTargetBrightness();
  if (target < 0) return;  // clock not synced
  target = constrain(target, 0, 100);

  // Send Kasa command if brightness changed OR every 5 min as safety net
  bool needsResend = (millis() - lastKasaSuccessMs > KASA_RESEND_MS) && (target > 0 || currentBrightness != 0);
  if (target != currentBrightness || needsResend) {
    if (needsResend && target == currentBrightness) {
      Serial.println("[LIGHT] Periodic re-send (safety net)");
    }
    bool ok = setLightBrightness(target);
    if (ok) {
      currentBrightness = target;
      lastKasaSuccessMs = millis();
    } else {
      Serial.println("[LIGHT] Kasa failed — will retry next cycle");
      currentBrightness = -1;  // force retry
    }
  }
}

// ------------------------------------------------------------------
// Poll for light schedule updates from blob
// ------------------------------------------------------------------
void pollLightSchedule() {
  if (millis() - lastLightSchedulePollMs < LIGHT_SCHEDULE_POLL_MS) return;
  lastLightSchedulePollMs = millis();

  String body = downloadBlob(String(LIGHT_SCHEDULE_BLOB));
  if (body.length() < 5) return;

  // Extract request_id
  int idStart = body.indexOf("\"request_id\"");
  if (idStart < 0) return;
  int colonPos = body.indexOf(':', idStart);
  int quoteStart = body.indexOf('"', colonPos + 1);
  int quoteEnd = body.indexOf('"', quoteStart + 1);
  if (quoteStart < 0 || quoteEnd < 0) return;
  String requestId = body.substring(quoteStart + 1, quoteEnd);

  if (requestId == lastLightRequestId) return;  // no change

  // New schedule — parse it
  lastLightRequestId = requestId;
  prefs.putString("lastLightReq", requestId);

  // Helper lambda to extract int values
  auto extractInt = [&](const String& key, int defaultVal) -> int {
    int pos = body.indexOf("\"" + key + "\"");
    if (pos < 0) return defaultVal;
    int colon = body.indexOf(':', pos);
    if (colon < 0) return defaultVal;
    int numStart = colon + 1;
    while (numStart < (int)body.length() && body[numStart] == ' ') numStart++;
    String numStr = "";
    while (numStart < (int)body.length() && body[numStart] >= '0' && body[numStart] <= '9') {
      numStr += body[numStart++];
    }
    return numStr.length() > 0 ? numStr.toInt() : defaultVal;
  };

  schedSunriseHour = extractInt("sunrise_hour", schedSunriseHour);
  schedSunriseRampMin = extractInt("sunrise_ramp_min", schedSunriseRampMin);
  schedPeakBrightness = extractInt("peak_brightness", schedPeakBrightness);
  schedSunsetHour = extractInt("sunset_hour", schedSunsetHour);
  schedSunsetRampMin = extractInt("sunset_ramp_min", schedSunsetRampMin);
  schedNightBrightness = extractInt("night_brightness", schedNightBrightness);

  Serial.println("[LIGHT] New schedule: sunrise=" + String(schedSunriseHour) +
                 "h ramp=" + String(schedSunriseRampMin) +
                 "m peak=" + String(schedPeakBrightness) +
                 "% sunset=" + String(schedSunsetHour) +
                 "h night=" + String(schedNightBrightness) + "%");

  // Force immediate light update with new schedule
  currentBrightness = -1;
}

// ------------------------------------------------------------------
// Poll for fan command updates from blob
// ------------------------------------------------------------------
void pollFanCommand() {
  // Check auto-off timer
  if (fanOn && fanAutoOffAtMs > 0 && millis() >= fanAutoOffAtMs) {
    kasaSetFan(false);
    fanOn = false;
    fanAutoOffAtMs = 0;
    Serial.println("[FAN] Auto-off timer expired");
  }

  if (millis() - lastFanPollMs < FAN_POLL_MS) return;
  lastFanPollMs = millis();

  String body = downloadBlob(String(FAN_COMMAND_BLOB));
  if (body.length() < 5) return;

  // Extract request_id
  int idStart = body.indexOf("\"request_id\"");
  if (idStart < 0) return;
  int colonPos = body.indexOf(':', idStart);
  int quoteStart = body.indexOf('"', colonPos + 1);
  int quoteEnd = body.indexOf('"', quoteStart + 1);
  if (quoteStart < 0 || quoteEnd < 0) return;
  String requestId = body.substring(quoteStart + 1, quoteEnd);

  if (requestId == lastFanRequestId) return;  // no change

  // Parse state
  bool stateOn = body.indexOf("\"state\":true") >= 0
              || body.indexOf("\"state\": true") >= 0
              || body.indexOf("\"state\":\"on\"") >= 0;

  // Parse optional duration_min
  int durationMin = 0;
  int durStart = body.indexOf("\"duration_min\"");
  if (durStart >= 0) {
    int durColon = body.indexOf(':', durStart);
    if (durColon >= 0) {
      int numStart = durColon + 1;
      while (numStart < (int)body.length() && body[numStart] == ' ') numStart++;
      String numStr = "";
      while (numStart < (int)body.length() && body[numStart] >= '0' && body[numStart] <= '9') {
        numStr += body[numStart++];
      }
      if (numStr.length() > 0) durationMin = numStr.toInt();
    }
  }

  // Parse optional speed (1-100)
  int speed = 100;
  int spdStart = body.indexOf("\"speed\"");
  if (spdStart >= 0) {
    int spdColon = body.indexOf(':', spdStart);
    if (spdColon >= 0) {
      int numStart = spdColon + 1;
      while (numStart < (int)body.length() && body[numStart] == ' ') numStart++;
      String numStr = "";
      while (numStart < (int)body.length() && body[numStart] >= '0' && body[numStart] <= '9') {
        numStr += body[numStart++];
      }
      if (numStr.length() > 0) speed = constrain(numStr.toInt(), 1, 100);
    }
  }

  lastFanRequestId = requestId;
  prefs.putString("lastFanReq", requestId);

  Serial.println("[FAN] Command: " + String(stateOn ? "ON" : "OFF") +
                 " speed=" + String(speed) + "%" +
                 (durationMin > 0 ? (" for " + String(durationMin) + "min") : ""));

  kasaSetFan(stateOn, speed);
  fanOn = stateOn;
  fanSpeed = speed;
  fanAutoOffAtMs = (stateOn && durationMin > 0) ? (millis() + (unsigned long)durationMin * 60000UL) : 0;
}

// ------------------------------------------------------------------
// Valve irrigation — open valve + pump for a duration
// ------------------------------------------------------------------
void checkValveTimer() {
  if (!valveIrrigating) return;
  if (millis() - valveIrrigationStartMs >= valveIrrigationDurationMs) {
    relayOff();  // pump off
    if (activeValvePin >= 0) digitalWrite(activeValvePin, HIGH);  // valve off
    valveIrrigating = false;
    activeValvePin = -1;
    Serial.println("[VALVE] Irrigation complete");
  }
}

void pollValveCommand() {
  checkValveTimer();

  if (millis() - lastValvePollMs < VALVE_POLL_MS) return;
  lastValvePollMs = millis();

  String body = downloadBlob(String(VALVE_COMMAND_BLOB));
  if (body.length() < 5) return;

  // Extract request_id
  int idStart = body.indexOf("\"request_id\"");
  if (idStart < 0) return;
  int colonPos = body.indexOf(':', idStart);
  int quoteStart = body.indexOf('"', colonPos + 1);
  int quoteEnd = body.indexOf('"', quoteStart + 1);
  if (quoteStart < 0 || quoteEnd < 0) return;
  String requestId = body.substring(quoteStart + 1, quoteEnd);

  if (requestId == lastValveRequestId) return;

  lastValveRequestId = requestId;
  prefs.putString("lastValveReq", requestId);

  // Parse valve (a, b, c)
  String valve = "a";
  int vStart = body.indexOf("\"valve\"");
  if (vStart >= 0) {
    int vQuoteStart = body.indexOf('"', body.indexOf(':', vStart) + 1);
    int vQuoteEnd = body.indexOf('"', vQuoteStart + 1);
    if (vQuoteStart >= 0 && vQuoteEnd >= 0) {
      valve = body.substring(vQuoteStart + 1, vQuoteEnd);
      valve.toLowerCase();
    }
  }

  // Parse duration_seconds (default 120)
  int durationSec = 120;
  int durStart = body.indexOf("\"duration_seconds\"");
  if (durStart >= 0) {
    int durColon = body.indexOf(':', durStart);
    if (durColon >= 0) {
      int numStart = durColon + 1;
      while (numStart < (int)body.length() && body[numStart] == ' ') numStart++;
      String numStr = "";
      while (numStart < (int)body.length() && body[numStart] >= '0' && body[numStart] <= '9') {
        numStr += body[numStart++];
      }
      if (numStr.length() > 0) durationSec = numStr.toInt();
    }
  }

  // Map valve to pin
  int valvePin = VALVE_A_PIN;
  String valveName = "A (water)";
  if (valve == "b") { valvePin = VALVE_B_PIN; valveName = "B (grow)"; }
  else if (valve == "c") { valvePin = VALVE_C_PIN; valveName = "C (bloom)"; }

  Serial.println("[VALVE] Opening " + valveName + " + pump for " + String(durationSec) + "s");

  // Open valve and start pump
  digitalWrite(valvePin, LOW);  // valve open (active LOW)
  relayOn();  // pump on
  valveIrrigating = true;
  valveIrrigationStartMs = millis();
  valveIrrigationDurationMs = (unsigned long)durationSec * 1000UL;
  activeValvePin = valvePin;
  recordEvent("valve", valveName + " " + String(durationSec) + "s");
}

// ------------------------------------------------------------------
// Upload moisture data to blob
// Readings are kept in a fixed circular buffer in RAM — no blob download
// needed. Each upload writes a complete, valid JSON document from scratch,
// so a WiFi drop or power cycle can never corrupt the stored array.
// ------------------------------------------------------------------
void uploadMoistureData() {
  if (millis() - lastMoistureUploadMs < MOISTURE_UPLOAD_INTERVAL_MS) return;
  lastMoistureUploadMs = millis();

  time_t now = time(nullptr);
  if (now < 1700000000) return;

  int moisturePct = map(lastMoistureRaw, 347, 885, 0, 100);
  moisturePct = constrain(moisturePct, 0, 100);

  struct tm tmInfo;
  gmtime_r(&now, &tmInfo);
  char isoBuf[25];
  strftime(isoBuf, sizeof(isoBuf), "%Y-%m-%dT%H:%M:%SZ", &tmInfo);

  // Append new reading to circular buffer
  MoistureReading& slot = moistureHistory[moistureHead];
  strlcpy(slot.ts, isoBuf, sizeof(slot.ts));
  slot.raw      = lastMoistureRaw;
  slot.pct      = moisturePct;
  slot.temp_c   = lastTempC;
  slot.light    = constrain(currentBrightness, 0, 100);
  slot.fan      = fanOn ? fanSpeed : 0;
  slot.weight_g = lastWeightG;
  slot.weight2_g = lastWeight2G;

  moistureHead = (moistureHead + 1) % MAX_MOISTURE_HISTORY;
  if (moistureCount < MAX_MOISTURE_HISTORY) moistureCount++;

  // Serialize buffer oldest-first into the readings array
  int startIdx = (moistureCount == MAX_MOISTURE_HISTORY) ? moistureHead : 0;
  String readings;
  readings.reserve(moistureCount * 130);  // pre-allocate to avoid reallocs
  for (int i = 0; i < moistureCount; i++) {
    const MoistureReading& r = moistureHistory[(startIdx + i) % MAX_MOISTURE_HISTORY];
    if (i > 0) readings += ",";
    readings += "{\"ts\":\"";
    readings += r.ts;
    readings += "\",\"raw\":";   readings += r.raw;
    readings += ",\"pct\":";     readings += r.pct;
    if (r.temp_c > -100) { readings += ",\"temp_c\":"; readings += String(r.temp_c, 1); }
    readings += ",\"light\":";   readings += r.light;
    readings += ",\"fan\":";     readings += r.fan;
    readings += ",\"weight_g\":";  readings += String(r.weight_g, 1);
    readings += ",\"weight2_g\":"; readings += String(r.weight2_g, 1);
    readings += "}";
  }

  String json = "{\"current\":{\"raw\":" + String(lastMoistureRaw)
              + ",\"pct\":"       + String(moisturePct)
              + ",\"temp_c\":"    + String(lastTempC, 1)
              + ",\"weight_g\":"  + String(lastWeightG, 1)
              + ",\"weight2_g\":" + String(lastWeight2G, 1)
              + ",\"light\":"     + String(constrain(currentBrightness, 0, 100))
              + ",\"fan\":"       + String(fanOn ? fanSpeed : 0)
              + ",\"timestamp\":\"" + String(isoBuf) + "\""
              + ",\"irrigating\":" + String(isIrrigating ? "true" : "false")
              + "},\"readings\":[" + readings + "]}";

  if (uploadJsonToBlob(String(MOISTURE_BLOB_NAME), json)) {
    Serial.println("[MOISTURE] Uploaded to blob (" + String(moisturePct) + "%)");
  } else {
    Serial.println("[MOISTURE] Blob upload failed");
  }
}

// ------------------------------------------------------------------
// Poll Azure Blob for irrigation command
// ------------------------------------------------------------------
void pollForCommand() {
  if (millis() - lastPollMs < POLL_INTERVAL_MS) return;
  lastPollMs = millis();

  time_t now = time(nullptr);
  if (now < 1700000000) {
    Serial.println("[POLL] Clock not synced, skipping");
    return;
  }

  String url = azureBlobUrl();
  String xMsDate = formatRfc1123(now);
  String canonicalizedResource =
      "/" + String(AZURE_ACCOUNT_NAME) +
      "/" + String(AZURE_CONTAINER) +
      "/" + String(AZURE_BLOB_NAME);

  String auth = buildGetAuthorization(xMsDate, canonicalizedResource);
  if (auth.length() == 0) {
    Serial.println("[POLL] Auth generation failed");
    return;
  }

  WiFiClientSecure client;
  client.setInsecure();  // prototype only

  HTTPClient http;
  if (!http.begin(client, url)) {
    Serial.println("[POLL] http.begin() failed");
    return;
  }

  http.addHeader("x-ms-date", xMsDate);
  http.addHeader("x-ms-version", AZURE_API_VERSION);
  http.addHeader("Authorization", auth);

  int code = http.GET();
  if (code != 200) {
    if (code > 0) {
      Serial.println("[POLL] HTTP " + String(code));
    } else {
      Serial.println("[POLL] Failed: " + http.errorToString(code));
    }
    http.end();
    return;
  }

  String body = http.getString();
  http.end();

  // Parse irrigate flag
  bool irrigate = body.indexOf("\"irrigate\":true") >= 0
               || body.indexOf("\"irrigate\": true") >= 0;

  // Extract request_id
  int idStart = body.indexOf("\"request_id\"");
  if (idStart < 0) return;

  int colonPos = body.indexOf(':', idStart);
  int quoteStart = body.indexOf('"', colonPos + 1);
  int quoteEnd = body.indexOf('"', quoteStart + 1);
  if (quoteStart < 0 || quoteEnd < 0) return;

  String requestId = body.substring(quoteStart + 1, quoteEnd);

  // Extract duration_ms (optional, default to DEFAULT_IRRIGATION_MS)
  unsigned long duration = DEFAULT_IRRIGATION_MS;
  int durStart = body.indexOf("\"duration_ms\"");
  if (durStart >= 0) {
    int durColon = body.indexOf(':', durStart);
    if (durColon >= 0) {
      // Skip whitespace after colon
      int numStart = durColon + 1;
      while (numStart < (int)body.length() && body[numStart] == ' ') numStart++;
      String numStr = "";
      while (numStart < (int)body.length() && body[numStart] >= '0' && body[numStart] <= '9') {
        numStr += body[numStart];
        numStart++;
      }
      if (numStr.length() > 0) {
        duration = numStr.toInt();
        if (duration < 1000) duration = 1000;           // min 1 second
        if (duration > 600000) duration = 600000;        // max 10 minutes
      }
    }
  }

  if (irrigate && requestId.length() > 0 && requestId != lastRequestId) {
    // Save request_id IMMEDIATELY to prevent double-trigger from next poll
    lastRequestId = requestId;
    prefs.putString("lastReqId", requestId);
    startIrrigation(requestId, duration);
  }
}

// ------------------------------------------------------------------
// Irrigation control
// ------------------------------------------------------------------
void startIrrigation(const String& requestId, unsigned long duration) {
  if (isIrrigating) {
    Serial.println("[SKIP] Already irrigating, ignoring: " + requestId);
    return;
  }
  Serial.println("[IRRIGATE] Watering " + String(duration / 1000) + "s for request: " + requestId);
  irrigationDurationMs = duration;
  isIrrigating = true;
  irrigationStartMs = millis();
  relayOn();
  recordEvent("irrigate", "pump " + String(duration / 1000) + "s");
}

void readMoisture() {
  if (millis() - lastMoistureReadMs < MOISTURE_READ_INTERVAL_MS) return;
  lastMoistureReadMs = millis();

  if (!seesawReady) {
    Serial.println("[MOISTURE] SeeSaw not ready");
    return;
  }

  // Skip readings during irrigation — pump noise can affect I2C
  if (isIrrigating) {
    Serial.println("[MOISTURE] Skipping read (irrigating)");
    return;
  }

  uint16_t currentRaw = soilSensor.touchRead(0);

  // Exponential moving average (alpha = 0.15 — heavy smoothing)
  if (!moistureInitialized) {
    smoothedMoisture = currentRaw;
    moistureInitialized = true;
  } else {
    smoothedMoisture = 0.15 * currentRaw + 0.85 * smoothedMoisture;
  }
  lastMoistureRaw = (int)(smoothedMoisture + 0.5);

  // SeeSaw capacitive range: ~347 (bone dry) to ~885 (saturated)
  int pct = map(lastMoistureRaw, 347, 885, 0, 100);
  pct = constrain(pct, 0, 100);
  Serial.println("[MOISTURE] SeeSaw raw: " + String(lastMoistureRaw) + "  (" + String(pct) + "%)");
}

void checkIrrigationTimer() {
  if (isIrrigating && (millis() - irrigationStartMs >= irrigationDurationMs)) {
    relayOff();
    isIrrigating = false;
    Serial.println("[IRRIGATE] Done. Pump OFF. Waiting 30s for sensor to settle...");
    // Reset EMA so next reading is clean
    moistureInitialized = false;
    // Delay next read 30 seconds to let sensor settle
    lastMoistureReadMs = millis() + 30000 - MOISTURE_READ_INTERVAL_MS;
  }
}

// ------------------------------------------------------------------
// Local web UI (status page)
// ------------------------------------------------------------------
String htmlPage() {
  String state = isIrrigating ? "<span style='color:blue'>WATERING</span>"
                              : "<span style='color:gray'>IDLE</span>";
  return "<!DOCTYPE html><html><head>"
    "<meta name='viewport' content='width=device-width, initial-scale=1'>"
    "<meta http-equiv='refresh' content='3'>"
    "<title>Irrigation</title>"
    "<style>body{font-family:Arial;text-align:center;padding:40px;}"
    "code{background:#eee;padding:2px 8px;border-radius:4px;}</style>"
    "</head><body>"
    "<h1>Irrigation Controller</h1>"
    "<p>Status: " + state + "</p>"
    "<p>Last request: <code>" + (lastRequestId.length() ? lastRequestId : "none") + "</code></p>"
    "<p>Moisture: <b>" + String(constrain(map(lastMoistureRaw, 40, 110, 0, 100), 0, 100)) + "%</b> (raw: " + String(lastMoistureRaw) + ")</p>"
    "<p>Polling: <code>" + azureBlobUrl() + "</code></p>"
    "</body></html>";
}

void readTemperature() {
  if (millis() - lastTempReadMs < TEMP_READ_INTERVAL_MS) return;
  lastTempReadMs = millis();

  tempSensor.requestTemperatures();
  float temp = tempSensor.getTempCByIndex(0);
  if (temp != DEVICE_DISCONNECTED_C) {
    lastTempC = temp;
    Serial.println("[TEMP] " + String(lastTempC, 1) + "°C / " + String(lastTempC * 9.0 / 5.0 + 32.0, 1) + "°F");
  } else {
    Serial.println("[TEMP] Sensor not found");
  }
}

void readWeight() {
  if (millis() - lastWeightReadMs < WEIGHT_READ_INTERVAL_MS) return;
  lastWeightReadMs = millis();
  if (scale.is_ready()) {
    lastWeightG = scale.get_units(10);
    Serial.print("[WEIGHT] Scale1: " + String(lastWeightG, 1) + "g");
  } else {
    Serial.print("[WEIGHT] Scale1: not ready");
  }
  if (scale2.is_ready()) {
    lastWeight2G = scale2.get_units(10);
    Serial.println("  Scale2: " + String(lastWeight2G, 1) + "g");
  } else {
    Serial.println("  Scale2: not ready");
  }
}

void pollTareCommand() {
  // Share poll timing with valve (every 5s)
  static unsigned long lastTarePollMs = 0;
  if (millis() - lastTarePollMs < VALVE_POLL_MS) return;
  lastTarePollMs = millis();

  String body = downloadBlob(String(TARE_COMMAND_BLOB));
  if (body.length() < 5) return;

  // Extract request_id
  int idStart = body.indexOf("\"request_id\"");
  if (idStart < 0) return;
  int colonPos = body.indexOf(':', idStart);
  int quoteStart = body.indexOf('"', colonPos + 1);
  int quoteEnd = body.indexOf('"', quoteStart + 1);
  if (quoteStart < 0 || quoteEnd < 0) return;
  String requestId = body.substring(quoteStart + 1, quoteEnd);

  if (requestId == lastTareRequestId) return;
  lastTareRequestId = requestId;
  prefs.putString("lastTareReq", requestId);

  // Parse which scale: "1", "2", "all", "scale_1", "scale_2"
  String which = "all";
  int sStart = body.indexOf("\"scale\"");
  if (sStart >= 0) {
    int sQuoteStart = body.indexOf('"', body.indexOf(':', sStart) + 1);
    int sQuoteEnd = body.indexOf('"', sQuoteStart + 1);
    if (sQuoteStart >= 0 && sQuoteEnd >= 0) {
      which = body.substring(sQuoteStart + 1, sQuoteEnd);
    }
  }

  String result = "";
  if (which == "1" || which == "scale_1" || which == "all") {
    if (scale.is_ready()) { scale.tare(); prefs.putLong("scaleOff1", scale.get_offset()); result += "Scale1 tared. "; }
    else result += "Scale1 not ready. ";
  }
  if (which == "2" || which == "scale_2" || which == "all") {
    if (scale2.is_ready()) { scale2.tare(); prefs.putLong("scaleOff2", scale2.get_offset()); result += "Scale2 tared. "; }
    else result += "Scale2 not ready. ";
  }
  Serial.println("[TARE] " + result);
}

void handleRoot()   { server.send(200, "text/html", htmlPage()); }
void handleStatus() {
  int moisturePct = map(lastMoistureRaw, 347, 885, 0, 100);
  moisturePct = constrain(moisturePct, 0, 100);
  String json = "{\"irrigating\":" + String(isIrrigating ? "true" : "false")
              + ",\"last_request_id\":\"" + lastRequestId + "\""
              + ",\"moisture_raw\":" + String(lastMoistureRaw)
              + ",\"moisture_pct\":" + String(moisturePct)
              + ",\"temp_c\":" + String(lastTempC, 1)
              + ",\"weight_g\":" + String(lastWeightG, 1)
              + ",\"weight2_g\":" + String(lastWeight2G, 1) + "}";
  server.send(200, "application/json", json);
}

// ------------------------------------------------------------------
// Setup / Loop
// ------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  pinMode(RELAY_PIN, OUTPUT);
  pinMode(VALVE_A_PIN, OUTPUT);
  digitalWrite(VALVE_A_PIN, HIGH);  // Relay off (active LOW)
  pinMode(VALVE_B_PIN, OUTPUT);
  digitalWrite(VALVE_B_PIN, HIGH);
  pinMode(VALVE_C_PIN, OUTPUT);
  digitalWrite(VALVE_C_PIN, HIGH);
  pinMode(LIGHT_DIM_PIN, OUTPUT);
  analogWrite(LIGHT_DIM_PIN, 0);  // Start at full brightness (inverted: 0 = full)
  relayOff();

  prefs.begin("irrigation", false);
  lastRequestId = prefs.getString("lastReqId", "");
  Serial.println("Restored lastRequestId: " + (lastRequestId.length() ? lastRequestId : "(none)"));

  WiFi.begin(ssid, password);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println("\nConnected! IP: " + WiFi.localIP().toString());

  syncClock();

  server.on("/", handleRoot);
  server.on("/status", handleStatus);
  server.on("/valve-open", []() {
    String v = server.hasArg("v") ? server.arg("v") : "a";
    int pin = v == "b" ? VALVE_B_PIN : v == "c" ? VALVE_C_PIN : VALVE_A_PIN;
    digitalWrite(pin, LOW);
    server.send(200, "text/plain", "Valve " + v + " OPEN. Hit /valve-close to close.");
    Serial.println("[VALVE] " + v + " opened");
  });
  server.on("/valve-close", []() {
    digitalWrite(VALVE_A_PIN, HIGH);
    digitalWrite(VALVE_B_PIN, HIGH);
    digitalWrite(VALVE_C_PIN, HIGH);
    server.send(200, "text/plain", "All valves closed.");
    Serial.println("[VALVE] All closed");
  });
  server.on("/test-valve-a", []() {
    int secs = server.hasArg("s") ? server.arg("s").toInt() : 2;
    server.send(200, "text/plain", "Valve A + Pump ON for " + String(secs) + " seconds...");
    digitalWrite(VALVE_A_PIN, LOW);
    relayOn();  // pump
    delay(secs * 1000);
    relayOff();
    digitalWrite(VALVE_A_PIN, HIGH);
    Serial.println("[VALVE] Test: A + pump for " + String(secs) + "s");
  });
  server.on("/test-valve-b", []() {
    int secs = server.hasArg("s") ? server.arg("s").toInt() : 2;
    server.send(200, "text/plain", "Valve B + Pump ON for " + String(secs) + " seconds...");
    digitalWrite(VALVE_B_PIN, LOW);
    relayOn();
    delay(secs * 1000);
    relayOff();
    digitalWrite(VALVE_B_PIN, HIGH);
    Serial.println("[VALVE] Test: B + pump for " + String(secs) + "s");
  });
  server.on("/test-valve-c", []() {
    int secs = server.hasArg("s") ? server.arg("s").toInt() : 2;
    server.send(200, "text/plain", "Valve C + Pump ON for " + String(secs) + " seconds...");
    digitalWrite(VALVE_C_PIN, LOW);
    relayOn();
    delay(secs * 1000);
    relayOff();
    digitalWrite(VALVE_C_PIN, HIGH);
    Serial.println("[VALVE] Test: C + pump for " + String(secs) + "s");
  });
  server.on("/tare", []() {
    String which = server.hasArg("s") ? server.arg("s") : "all";
    String result = "";
    if (which == "1" || which == "all") {
      if (scale.is_ready()) { scale.tare(); prefs.putLong("scaleOff1", scale.get_offset()); result += "Scale1 tared. "; }
      else result += "Scale1 not ready. ";
    }
    if (which == "2" || which == "all") {
      if (scale2.is_ready()) { scale2.tare(); prefs.putLong("scaleOff2", scale2.get_offset()); result += "Scale2 tared. "; }
      else result += "Scale2 not ready. ";
    }
    server.send(200, "text/plain", result);
    Serial.println("[TARE] " + result);
  });
  server.begin();

  // Don't restore lastLightRequestId — always reload schedule on boot
  lastLightRequestId = "";
  lastValveRequestId = prefs.getString("lastValveReq", "");
  lastTareRequestId = prefs.getString("lastTareReq", "");
  // Don't restore fan request ID — always re-apply fan state on boot
  lastFanRequestId = "";

  Wire.begin(SEESAW_SDA_PIN, SEESAW_SCL_PIN);
  seesawReady = soilSensor.begin(0x36);
  if (seesawReady) {
    Serial.println("SeeSaw soil sensor ready on SDA=" + String(SEESAW_SDA_PIN) + " SCL=" + String(SEESAW_SCL_PIN));
  } else {
    Serial.println("[MOISTURE] SeeSaw not found — check wiring (SDA=" + String(SEESAW_SDA_PIN) + " SCL=" + String(SEESAW_SCL_PIN) + ")");
  }

  tempSensor.begin();
  Serial.println("Temperature sensor on GPIO " + String(TEMP_PIN) + " — " + String(tempSensor.getDeviceCount()) + " device(s) found");

  scale.begin(WEIGHT_DT_PIN, WEIGHT_SCK_PIN);
  scale.set_scale(WEIGHT_CALIBRATION);
  Serial.print("Waiting for HX711");
  unsigned long hx711Wait = millis();
  while (!scale.is_ready() && millis() - hx711Wait < 3000) {
    delay(100);
    Serial.print(".");
  }
  if (scale.is_ready()) {
    // Restore saved tare offset from flash
    int32_t savedOffset1 = prefs.getLong("scaleOff1", 0);
    if (savedOffset1 != 0) {
      scale.set_offset(savedOffset1);
      Serial.println("\nScale1 ready (restored tare offset)");
    } else {
      Serial.println("\nScale1 ready (no saved tare — raw values)");
    }
  } else {
    Serial.println("\n[WEIGHT] Scale1 not found — check wiring on GPIO " + String(WEIGHT_SCK_PIN) + "/" + String(WEIGHT_DT_PIN));
  }

  scale2.begin(WEIGHT2_DT_PIN, WEIGHT2_SCK_PIN);
  scale2.set_scale(WEIGHT_CALIBRATION);
  Serial.print("Waiting for HX711 #2");
  unsigned long hx711Wait2 = millis();
  while (!scale2.is_ready() && millis() - hx711Wait2 < 3000) {
    delay(100);
    Serial.print(".");
  }
  if (scale2.is_ready()) {
    int32_t savedOffset2 = prefs.getLong("scaleOff2", 0);
    if (savedOffset2 != 0) {
      scale2.set_offset(savedOffset2);
      Serial.println("\nScale2 ready (restored tare offset)");
    } else {
      Serial.println("\nScale2 ready (no saved tare — raw values)");
    }
  } else {
    Serial.println("\n[WEIGHT] Scale2 not found — check wiring on GPIO " + String(WEIGHT2_SCK_PIN) + "/" + String(WEIGHT2_DT_PIN));
  }
  Serial.println("Moisture sensor: SeeSaw I2C 0x36 (SDA=" + String(SEESAW_SDA_PIN) + " SCL=" + String(SEESAW_SCL_PIN) + ")");
  Serial.println("Kasa light: " + String(strlen(KASA_LIGHT_IP) ? KASA_LIGHT_IP : "(not configured)"));
  Serial.println("Kasa fan: " + String(KASA_FAN_IP));
  Serial.println("Polling: " + azureBlobUrl());
  // OTA (Over-The-Air) updates — flash wirelessly from Arduino IDE
  ArduinoOTA.setHostname("esp32-irrigation");
  ArduinoOTA.onStart([]() { Serial.println("[OTA] Update starting..."); });
  ArduinoOTA.onEnd([]() { Serial.println("[OTA] Update complete! Rebooting..."); });
  ArduinoOTA.onError([](ota_error_t error) { Serial.printf("[OTA] Error %u\n", error); });
  ArduinoOTA.begin();
  Serial.println("OTA enabled: esp32-irrigation");

  Serial.println("Ready.");
}

void loop() {
  // Reconnect WiFi if dropped (common overnight)
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WIFI] Disconnected, reconnecting...");
    WiFi.disconnect();
    WiFi.begin(ssid, password);

    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
      delay(500);
      Serial.print(".");
    }
    Serial.println();

    if (WiFi.status() == WL_CONNECTED) {
      Serial.println("[WIFI] Reconnected! IP: " + WiFi.localIP().toString());
      syncClock();
    } else {
      Serial.println("[WIFI] Reconnect failed, will retry next loop");
      delay(5000);
      return;
    }
  }

  ArduinoOTA.handle();
  server.handleClient();
  readMoisture();
  readTemperature();
  readWeight();
  uploadMoistureData();
  pollForCommand();
  checkIrrigationTimer();
  pollLightSchedule();
  updateLights();
  pollFanCommand();
  pollValveCommand();
  pollTareCommand();
}
