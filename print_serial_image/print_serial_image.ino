/*
  print_serial_image.ino -- Teensy 3.2 bridge between the Raspberry Pi and an
  Adafruit Mini Thermal Receipt Printer.

  The Pi sends a 1-bit bitmap over USB serial (protocol below, and in
  print_image.py). Once the whole image has arrived and the Pi's
  "transfer complete" ack checks out, the Teensy prints it through its
  hardware UART (Serial1), using the printer's DTR line for hardware flow
  control so the printer itself decides how fast data is sent.

  Protocol (multi-byte values are little-endian, replies end in a newline):
    Pi     -> Teensy   "IMG1" + width:u16 + height:u16 + feed_lines:u8
    Teensy -> Pi       "READY"                  (or "ERR <reason>")
    Pi     -> Teensy   ceil(width / 8) * height bitmap bytes
    Pi     -> Teensy   "DONE" + checksum:u32    (sum of bitmap bytes)
    Teensy -> Pi       "OK"                     (or "ERR <reason>"), then prints
    Teensy -> Pi       "PRINTED"

  Wiring (Teensy 3.2 runs at 3.3 V with 5 V tolerant pins; the printer's
  logic is 3.3 V and 5 V safe, so everything connects directly):
    Teensy pin 1 (TX1)  -> printer RX
    Teensy pin 4        <- printer DTR (the "DTR" pad on the printer's
                           controller board, see
                           https://learn.adafruit.com/mini-thermal-receipt-printer/hacking)
    Teensy GND          -- printer GND
  Power the printer from its own 5-9 V, 2 A supply, not from the Teensy.

  Arduino IDE setup:
    - Install Teensyduino. Tools > Board > Teensy 3.2 / 3.1,
      Tools > USB Type > Serial.
    - Library Manager: install "Adafruit Thermal Printer Library".
*/

#include <Adafruit_Thermal.h>

// ---- Settings ----
// Set USE_DTR to 0 to fall back to the library's timed pacing if the DTR
// wire isn't connected. With USE_DTR 1 and no DTR wire, the input's pull-up
// reads "busy" forever and printing hangs until the Teensy is reset.
#define USE_DTR 1
const uint8_t  DTR_PIN = 4;
const uint32_t PRINTER_BAUD = 19200;   // from the printer's self-test page
const uint8_t  HEAT_DOTS = 11;
const uint8_t  HEAT_TIME = 120;        // higher = darker but slower
const uint8_t  HEAT_INTERVAL = 40;
const uint32_t TRANSFER_TIMEOUT_MS = 5000;

// ---- Protocol (must match print_image.py) ----
const char MAGIC[] = "IMG1";
const char DONE[] = "DONE";
const uint16_t MAX_WIDTH = 384;                 // print head width in dots
const uint16_t MAX_ROW_BYTES = MAX_WIDTH / 8;   // 48
const uint16_t MAX_HEIGHT = 800;                // 38,400-byte buffer; Teensy 3.2 has 64 KB RAM

static uint8_t bitmap[MAX_ROW_BYTES * MAX_HEIGHT];

Adafruit_Thermal printer(&Serial1, USE_DTR ? DTR_PIN : 255);

void setup() {
  Serial.begin(115200);  // native USB serial; the baud rate is ignored
  Serial.setTimeout(TRANSFER_TIMEOUT_MS);
  Serial1.begin(PRINTER_BAUD);
  printer.begin();  // with a DTR pin, this also tells the printer to drive DTR
  printer.setHeatConfig(HEAT_DOTS, HEAT_TIME, HEAT_INTERVAL);
}

void loop() {
  // Scan incoming bytes for the header's magic, then handle one transfer.
  static uint8_t matched = 0;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == MAGIC[matched]) {
      if (++matched == 4) {
        matched = 0;
        receiveAndPrint();
      }
    } else {
      matched = (c == MAGIC[0]) ? 1 : 0;
    }
  }
}

// Discard incoming bytes until the line has been quiet for a moment, so the
// rest of an aborted transfer isn't mistaken for the next header.
void drainInput() {
  uint32_t last = millis();
  while (millis() - last < 100) {
    if (Serial.available()) {
      Serial.read();
      last = millis();
    }
  }
}

void fail(const char *reason) {
  drainInput();
  Serial.print("ERR ");
  Serial.println(reason);
}

void receiveAndPrint() {
  uint8_t header[5];
  if (Serial.readBytes((char *)header, sizeof(header)) != sizeof(header)) {
    fail("timeout reading header");
    return;
  }
  uint16_t width = header[0] | (header[1] << 8);
  uint16_t height = header[2] | (header[3] << 8);
  uint8_t feedLines = header[4];
  if (width == 0 || height == 0 || width > MAX_WIDTH || height > MAX_HEIGHT) {
    fail("bad image size");
    return;
  }
  size_t length = (size_t)((width + 7) / 8) * height;
  Serial.println("READY");

  if (Serial.readBytes((char *)bitmap, length) != length) {
    fail("timeout receiving image data");
    return;
  }

  // Transfer-complete ack: "DONE" followed by the byte sum of the bitmap.
  uint8_t ack[8];
  if (Serial.readBytes((char *)ack, sizeof(ack)) != sizeof(ack) || memcmp(ack, DONE, 4) != 0) {
    fail("missing transfer-complete ack");
    return;
  }
  uint32_t expected = ack[4] | ((uint32_t)ack[5] << 8) | ((uint32_t)ack[6] << 16) | ((uint32_t)ack[7] << 24);
  uint32_t sum = 0;
  for (size_t i = 0; i < length; i++) {
    sum += bitmap[i];
  }
  if (sum != expected) {
    fail("checksum mismatch");
    return;
  }
  Serial.println("OK");

  // With DTR enabled, the library waits on the printer's ready signal before
  // every byte, so the whole image can go out in one call.
  printer.printBitmap(width, height, bitmap, false);
  if (feedLines) {
    printer.feed(feedLines);
  }
  Serial.println("PRINTED");
}
