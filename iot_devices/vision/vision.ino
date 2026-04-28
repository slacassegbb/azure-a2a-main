#include "esp_camera.h"
#include <WiFi.h>
#include <Preferences.h>
#include <ArduinoOTA.h>
#include "FS.h"
#include "SD_MMC.h"
#include <ESPmDNS.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <time.h>
#include "mbedtls/base64.h"
#include "mbedtls/md.h"

#define CAMERA_MODEL_ESP32S3_EYE
#include "camera_pins.h"

// ===========================
// Wi-Fi
// ===========================
const char* ssid = "Zig420";
const char* password = "hip1hops";

// ===========================
// Azure Blob config
// ===========================
const char* AZURE_ACCOUNT_NAME = "a2astoragefilesa2a";
const char* AZURE_ACCOUNT_KEY  = "CS6udqgXa//vXxtg2oPUGiXrQooHaIPVNqsLD0g8WAO09dTBm4zHm0SCkMDSIRmpTbZBrOjg33q8+AStPTyYGw==";
const char* AZURE_CONTAINER    = "garden-images";
const char* AZURE_BLOB_NAME    = "latest.jpg";

// Shared Key upload API version
const char* AZURE_API_VERSION = "2023-11-03";

// SAS version for generated clickable URL
const char* AZURE_SAS_VERSION = "2023-11-03";

// ===========================
// Capture command polling
// ===========================
const char* CAPTURE_CMD_BLOB = "capture-command.json";
const unsigned long CAPTURE_POLL_INTERVAL_MS = 5000; // poll every 5 seconds
unsigned long lastCapturePollMs = 0;

// ===========================
// Scheduled upload interval
// ===========================
const unsigned long UPLOAD_INTERVAL_MS = 30UL * 60UL * 1000UL; // 30 minutes
unsigned long lastUploadMs = 0;

const char* NTP_SERVER_1 = "pool.ntp.org";
const char* NTP_SERVER_2 = "time.nist.gov";

// ===========================
// Watchdog
// ===========================
const unsigned long WATCHDOG_MAX_UPLOAD_INTERVAL_MS = 45UL * 60UL * 1000UL;  // reboot if no upload for 45 min
const unsigned long WATCHDOG_PERIODIC_REBOOT_MS = 6UL * 60UL * 60UL * 1000UL; // reboot every 6 hours
unsigned long lastSuccessfulUploadMs = 0;
unsigned long bootTimeMs = 0;

// ===========================
// State
// ===========================
Preferences prefs;
String lastCaptureRequestId = "";

void startCameraServer();

// ---------------------------
// Helpers
// ---------------------------
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
  if (!base64Decode(base64Key, keyBytes, sizeof(keyBytes), keyLen)) {
    return "";
  }

  uint8_t hmac[32];
  const mbedtls_md_info_t* mdInfo = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
  if (!mdInfo) return "";

  if (mbedtls_md_hmac(mdInfo,
                      keyBytes, keyLen,
                      (const unsigned char*)message.c_str(), message.length(),
                      hmac) != 0) {
    return "";
  }

  return base64Encode(hmac, sizeof(hmac));
}

String urlEncode(const String& input) {
  const char* hex = "0123456789ABCDEF";
  String out;
  for (size_t i = 0; i < input.length(); i++) {
    char c = input[i];
    bool safe =
      (c >= 'a' && c <= 'z') ||
      (c >= 'A' && c <= 'Z') ||
      (c >= '0' && c <= '9') ||
      c == '-' || c == '_' || c == '.' || c == '~';

    if (safe) {
      out += c;
    } else {
      out += '%';
      out += hex[(c >> 4) & 0x0F];
      out += hex[c & 0x0F];
    }
  }
  return out;
}

String formatRfc1123(time_t rawTime) {
  struct tm tmInfo;
  gmtime_r(&rawTime, &tmInfo);

  char buf[40];
  strftime(buf, sizeof(buf), "%a, %d %b %Y %H:%M:%S GMT", &tmInfo);
  return String(buf);
}

String formatIso8601(time_t rawTime) {
  struct tm tmInfo;
  gmtime_r(&rawTime, &tmInfo);

  char buf[30];
  strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &tmInfo);
  return String(buf);
}

bool syncClock() {
  configTime(0, 0, NTP_SERVER_1, NTP_SERVER_2);

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

String azureBlobBaseUrl(const String& blobName) {
  return "https://" + String(AZURE_ACCOUNT_NAME) +
         ".blob.core.windows.net/" +
         String(AZURE_CONTAINER) + "/" +
         blobName;
}

String generateTimestampBlobName() {
  time_t now = time(nullptr);
  struct tm tmInfo;
  gmtime_r(&now, &tmInfo);

  char buf[30];
  strftime(buf, sizeof(buf), "%Y-%m-%d_%H-%M-%S", &tmInfo);
  return String(buf) + ".jpg";
}

// ---------------------------
// Azure upload auth (PUT)
// ---------------------------
String buildSharedKeyAuthorization(const String& verb,
                                   size_t contentLength,
                                   const String& contentType,
                                   const String& xMsDate,
                                   const String& canonicalizedResource) {
  String stringToSign =
      verb + "\n" +
      "\n" +                    // Content-Encoding
      "\n" +                    // Content-Language
      String(contentLength) + "\n" +
      "\n" +                    // Content-MD5
      contentType + "\n" +
      "\n" +                    // Date
      "\n" +                    // If-Modified-Since
      "\n" +                    // If-Match
      "\n" +                    // If-None-Match
      "\n" +                    // If-Unmodified-Since
      "\n" +                    // Range
      "x-ms-blob-type:BlockBlob\n" +
      "x-ms-date:" + xMsDate + "\n" +
      "x-ms-version:" + String(AZURE_API_VERSION) + "\n" +
      canonicalizedResource;

  String signature = hmacSha256Base64(stringToSign, AZURE_ACCOUNT_KEY);
  if (signature.length() == 0) return "";

  return "SharedKey " + String(AZURE_ACCOUNT_NAME) + ":" + signature;
}

// ---------------------------
// Azure read auth (GET)
// ---------------------------
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

// ---------------------------
// Azure read SAS URL
// ---------------------------
String generateBlobReadSasUrl(int validHours) {
  time_t now = time(nullptr);
  if (now < 1700000000) return "";

  String st = formatIso8601(now - 300);
  String se = formatIso8601(now + (validHours * 3600));

  String sp  = "r";
  String spr = "https";
  String sv  = AZURE_SAS_VERSION;
  String sr  = "b";

  String blobName = String(AZURE_BLOB_NAME);
  String canonicalizedResource =
      "/blob/" + String(AZURE_ACCOUNT_NAME) +
      "/" + String(AZURE_CONTAINER) +
      "/" + blobName;

  String stringToSign =
      sp + "\n" +
      st + "\n" +
      se + "\n" +
      canonicalizedResource + "\n" +
      "\n" +                     // signedIdentifier
      "\n" +                     // signedIP
      spr + "\n" +
      sv + "\n" +
      sr + "\n" +
      "\n" +                     // signedSnapshotTime
      "\n" +                     // signedEncryptionScope
      "\n" +                     // rscc
      "\n" +                     // rscd
      "\n" +                     // rsce
      "\n" +                     // rscl
      "";                        // rsct

  String sig = hmacSha256Base64(stringToSign, AZURE_ACCOUNT_KEY);
  if (sig.length() == 0) return "";

  String url = azureBlobBaseUrl(blobName);
  url += "?sp=" + urlEncode(sp);
  url += "&st=" + urlEncode(st);
  url += "&se=" + urlEncode(se);
  url += "&spr=" + urlEncode(spr);
  url += "&sv=" + urlEncode(sv);
  url += "&sr=" + urlEncode(sr);
  url += "&sig=" + urlEncode(sig);

  return url;
}

// ---------------------------
// SD card
// ---------------------------
bool initSDCard() {
  Serial.println("Initializing SD card...");

  if (!SD_MMC.setPins(39, 38, 40)) {
    Serial.println("SD_MMC.setPins failed");
    return false;
  }

  if (!SD_MMC.begin("/sdcard", true)) {
    Serial.println("SD Card Mount Failed");
    return false;
  }

  uint8_t cardType = SD_MMC.cardType();
  if (cardType == CARD_NONE) {
    Serial.println("No SD card attached");
    return false;
  }

  Serial.print("SD Card Type: ");
  if (cardType == CARD_MMC) Serial.println("MMC");
  else if (cardType == CARD_SD) Serial.println("SDSC");
  else if (cardType == CARD_SDHC) Serial.println("SDHC");
  else Serial.println("UNKNOWN");

  uint64_t cardSize = SD_MMC.cardSize() / (1024 * 1024);
  Serial.printf("SD Card Size: %lluMB\n", cardSize);

  return true;
}

bool initMDNS() {
  if (!MDNS.begin("esp32cam")) {
    Serial.println("mDNS failed");
    return false;
  }
  Serial.println("mDNS started: http://esp32cam.local");
  return true;
}

// ---------------------------
// Azure upload
// ---------------------------
bool uploadBufferToAzure(const uint8_t* data, size_t len, const String& blobName) {
  if (!data || len == 0) {
    Serial.println("Upload skipped: empty image");
    return false;
  }

  time_t now = time(nullptr);
  if (now < 1700000000) {
    Serial.println("Upload failed: clock not synced");
    return false;
  }

  String url = azureBlobBaseUrl(blobName);
  String xMsDate = formatRfc1123(now);
  String canonicalizedResource =
      "/" + String(AZURE_ACCOUNT_NAME) +
      "/" + String(AZURE_CONTAINER) +
      "/" + blobName;

  String auth = buildSharedKeyAuthorization(
      "PUT",
      len,
      "image/jpeg",
      xMsDate,
      canonicalizedResource
  );

  if (auth.length() == 0) {
    Serial.println("Upload failed: auth header generation failed");
    return false;
  }

  WiFiClientSecure client;
  client.setInsecure(); // prototype only

  HTTPClient http;
  if (!http.begin(client, url)) {
    Serial.println("Upload failed: http.begin() failed");
    return false;
  }

  http.addHeader("x-ms-date", xMsDate);
  http.addHeader("x-ms-version", AZURE_API_VERSION);
  http.addHeader("x-ms-blob-type", "BlockBlob");
  http.addHeader("Content-Type", "image/jpeg");
  http.addHeader("Authorization", auth);

  Serial.printf("Uploading image as %s ...\n", blobName.c_str());
  int httpCode = http.PUT((uint8_t*)data, len);
  String response = http.getString();
  http.end();

  Serial.printf("Azure HTTP code: %d\n", httpCode);

  if (httpCode == 201) {
    Serial.println("Azure upload success");
    Serial.print("Blob URI: ");
    Serial.println(url);
    return true;
  }

  Serial.println("Azure upload failed");
  if (response.length()) {
    Serial.println(response);
  }
  return false;
}

bool captureAndUploadLatest() {
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Capture failed");
    return false;
  }

  const uint8_t* jpgData = nullptr;
  size_t jpgLen = 0;
  uint8_t* convertedBuf = nullptr;

  if (fb->format == PIXFORMAT_JPEG) {
    jpgData = fb->buf;
    jpgLen = fb->len;
  } else {
    bool converted = frame2jpg(fb, 80, &convertedBuf, &jpgLen);
    esp_camera_fb_return(fb);
    fb = nullptr;

    if (!converted || !convertedBuf) {
      Serial.println("JPEG conversion failed");
      return false;
    }
    jpgData = convertedBuf;
  }

  Serial.printf("Captured JPEG: %u bytes\n", (unsigned)jpgLen);

  // Upload timestamped copy first
  String timestampName = generateTimestampBlobName();
  bool okTs = uploadBufferToAzure(jpgData, jpgLen, timestampName);

  // Upload as latest.jpg
  bool okLatest = uploadBufferToAzure(jpgData, jpgLen, String(AZURE_BLOB_NAME));

  if (okLatest) {
    String sasUrl = generateBlobReadSasUrl(24);
    if (sasUrl.length()) {
      Serial.println("Clickable SAS URL (latest.jpg):");
      Serial.println(sasUrl);
    }
  }

  if (fb) esp_camera_fb_return(fb);
  if (convertedBuf) free(convertedBuf);

  if (okTs && okLatest) {
    lastSuccessfulUploadMs = millis();
  }
  return okTs && okLatest;
}

// ---------------------------
// Watchdog — reboot if stuck
// ---------------------------
void checkWatchdog() {
  unsigned long uptime = millis() - bootTimeMs;

  // Periodic reboot every 6 hours to prevent memory fragmentation
  if (uptime >= WATCHDOG_PERIODIC_REBOOT_MS) {
    Serial.println("[WATCHDOG] 6-hour periodic reboot");
    delay(1000);
    ESP.restart();
  }

  // Reboot if no successful upload for 45 minutes (scheduled uploads run every 30 min)
  if (lastSuccessfulUploadMs > 0 && (millis() - lastSuccessfulUploadMs) > WATCHDOG_MAX_UPLOAD_INTERVAL_MS) {
    Serial.println("[WATCHDOG] No successful upload in 45 min — rebooting");
    delay(1000);
    ESP.restart();
  }
}

// ---------------------------
// Poll for on-demand capture commands
// ---------------------------
void pollForCaptureCommand() {
  if (millis() - lastCapturePollMs < CAPTURE_POLL_INTERVAL_MS) return;
  lastCapturePollMs = millis();

  time_t now = time(nullptr);
  if (now < 1700000000) return;

  String url = azureBlobBaseUrl(String(CAPTURE_CMD_BLOB));
  String xMsDate = formatRfc1123(now);
  String canonicalizedResource =
      "/" + String(AZURE_ACCOUNT_NAME) +
      "/" + String(AZURE_CONTAINER) +
      "/" + String(CAPTURE_CMD_BLOB);

  String auth = buildGetAuthorization(xMsDate, canonicalizedResource);
  if (auth.length() == 0) return;

  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient http;
  if (!http.begin(client, url)) return;

  http.addHeader("x-ms-date", xMsDate);
  http.addHeader("x-ms-version", AZURE_API_VERSION);
  http.addHeader("Authorization", auth);

  int code = http.GET();
  if (code != 200) {
    http.end();
    return;
  }

  String body = http.getString();
  http.end();

  // Parse capture flag
  bool capture = body.indexOf("\"capture\":true") >= 0
              || body.indexOf("\"capture\": true") >= 0;

  // Extract request_id
  int idStart = body.indexOf("\"request_id\"");
  if (idStart < 0) return;

  int colonPos = body.indexOf(':', idStart);
  int quoteStart = body.indexOf('"', colonPos + 1);
  int quoteEnd = body.indexOf('"', quoteStart + 1);
  if (quoteStart < 0 || quoteEnd < 0) return;

  String requestId = body.substring(quoteStart + 1, quoteEnd);

  if (capture && requestId.length() > 0 && requestId != lastCaptureRequestId) {
    Serial.println("[CAPTURE] On-demand capture requested: " + requestId);
    lastCaptureRequestId = requestId;
    prefs.putString("lastCapReqId", requestId);

    if (captureAndUploadLatest()) {
      Serial.println("[CAPTURE] On-demand capture complete.");
      // Reset the upload timer so we don't double-capture soon after
      lastUploadMs = millis();
    } else {
      Serial.println("[CAPTURE] On-demand capture failed.");
    }
  }
}

// ---------------------------
// Setup / Loop
// ---------------------------
void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(true);
  Serial.println();

  // NVS for capture request persistence
  prefs.begin("vision", false);
  lastCaptureRequestId = prefs.getString("lastCapReqId", "");
  Serial.println("Restored lastCaptureRequestId: " + (lastCaptureRequestId.length() ? lastCaptureRequestId : "(none)"));

  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 10000000;
  config.frame_size = FRAMESIZE_UXGA;     // 1600x1200 (2MP) — max resolution
  config.pixel_format = PIXFORMAT_JPEG;
  config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  config.fb_location = CAMERA_FB_IN_PSRAM;
  config.jpeg_quality = 8;                // Higher quality (lower = better, 0-63)
  config.fb_count = 1;

  if (psramFound()) {
    config.jpeg_quality = 6;              // Best quality with PSRAM
    config.fb_count = 2;
    config.grab_mode = CAMERA_GRAB_LATEST;
    Serial.println("PSRAM FOUND — using UXGA (1600x1200) quality 6");
  } else {
    config.frame_size = FRAMESIZE_SVGA;   // Fall back to 800x600 without PSRAM
    config.fb_location = CAMERA_FB_IN_DRAM;
    config.jpeg_quality = 10;
    Serial.println("NO PSRAM — using SVGA (800x600)");
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x\n", err);
    return;
  }

  sensor_t *s = esp_camera_sensor_get();
  s->set_vflip(s, 1);
  s->set_brightness(s, 1);      // slightly bright for grow light environment
  s->set_contrast(s, 1);        // boost contrast to cut through haze
  s->set_saturation(s, 0);      // neutral saturation
  s->set_sharpness(s, 2);       // sharpen for plant detail
  s->set_exposure_ctrl(s, 1);   // auto exposure on
  s->set_aec2(s, 1);            // advanced auto exposure
  s->set_ae_level(s, 0);        // neutral exposure
  s->set_gainceiling(s, (gainceiling_t)6);  // moderate gain ceiling

  WiFi.begin(ssid, password);
  WiFi.setSleep(false);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.println("WiFi connected");
  Serial.print("Local IP: ");
  Serial.println(WiFi.localIP());

  // Turn off onboard LED
  pinMode(3, OUTPUT);
  digitalWrite(3, LOW);

  initMDNS();
  syncClock();

  // OTA (Over-The-Air) updates — flash wirelessly from Arduino IDE
  ArduinoOTA.setHostname("esp32-vision");
  ArduinoOTA.onStart([]() { Serial.println("[OTA] Update starting..."); });
  ArduinoOTA.onEnd([]() { Serial.println("[OTA] Update complete! Rebooting..."); });
  ArduinoOTA.onError([](ota_error_t error) { Serial.printf("[OTA] Error %u\n", error); });
  ArduinoOTA.begin();
  Serial.println("OTA enabled: esp32-vision");

  if (!initSDCard()) {
    Serial.println("WARNING: SD init failed. Still images will not be saved by the server file.");
  }

  startCameraServer();

  Serial.print("Camera Ready! Use 'http://");
  Serial.print(WiFi.localIP());
  Serial.println("' to connect");

  Serial.print("Target blob URI: ");
  Serial.println(azureBlobBaseUrl(String(AZURE_BLOB_NAME)));

  Serial.print("Polling for capture commands: ");
  Serial.println(azureBlobBaseUrl(String(CAPTURE_CMD_BLOB)));

  Serial.println("Doing initial Azure upload...");
  captureAndUploadLatest();
  lastUploadMs = millis();
  bootTimeMs = millis();
}

void loop() {
  // Reconnect WiFi if dropped
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
      Serial.println("[WIFI] Reconnected");
      syncClock();
    } else {
      delay(5000);
      return;
    }
  }

  // Poll for on-demand capture commands
  pollForCaptureCommand();

  // Scheduled 30-minute upload
  if (millis() - lastUploadMs >= UPLOAD_INTERVAL_MS) {
    Serial.println("Upload interval reached");
    captureAndUploadLatest();
    lastUploadMs = millis();
  }

  // Watchdog — reboot if stuck or after 6 hours
  checkWatchdog();

  // Handle OTA updates
  ArduinoOTA.handle();

  delay(1000);
}
