// hotflash.ino
// ESP32 test task: USB serial commands, timed "hot flash" LED sequence,
// immediate STOP, and an automatic safety cutoff.
//
// PROTOCOL (plain text, one command per line, case-insensitive, 115200 baud)
//   START   start (or restart) the hot-flash sequence; opens the channel
//   STOP    stop immediately; everything off
//   STATUS  report current state
//   HELP    list commands
//
// Messages sent by the ESP32:
//   READY ...           after boot
//   OK START / OK STOP  command accepted
//   DONE                sequence finished (the channel stays open)
//   CUTOFF ...          safety cutoff: no command for CUTOFF_MS while the channel was open
//   ERR ...             unknown or malformed command
//
// SAFETY CUTOFF
//   START opens the "channel" (think: a heating element being powered). It stays
//   open after the sequence has finished, until STOP or until no command has
//   arrived for CUTOFF_MS (10 s). Then the ESP32 closes the channel and switches
//   the LEDs off by itself. Every valid command resets that timer.
//   The channel has no pin of its own; STATUS reports it as channel=1/0.
//
// WIRING: each LED pin -> 220 ohm resistor -> LED anode, LED cathode -> GND.
// Pins below suit a classic ESP32 DevKit. For ESP32-S3/C3 boards pick free
// GPIOs, and on native-USB boards enable "USB CDC On Boot" in the Arduino IDE.

const uint8_t SEQ_PINS[]  = {4, 16, 17, 5, 18};  // LED 0..4 = rising intensity
const uint8_t NUM_SEQ     = sizeof(SEQ_PINS);
const unsigned long CUTOFF_MS = 10000;

// ---- The hot-flash sequence -------------------------------------------------
// Each step: time (ms from start), LED index, on/off.
// Build-up: LEDs turn on with shrinking gaps (the flash accelerates).
// Then they turn off in reverse order with the same gaps mirrored (it eases off).
struct Step { uint16_t t; uint8_t led; bool on; };

const Step SEQUENCE[] = {
  // build-up
  {    0, 0, true  }, {  800, 1, true  }, { 1500, 2, true  },
  { 2100, 3, true  }, { 2600, 4, true  },
  // all on for a moment, then backwards
  { 3600, 4, false }, { 4100, 3, false }, { 4700, 2, false },
  { 5400, 1, false }, { 6200, 0, false },
};
const uint8_t  NUM_STEPS  = sizeof(SEQUENCE) / sizeof(SEQUENCE[0]);
const uint16_t SEQ_END_MS = 6700;

// ---- State --------------------------------------------------------------------
bool running = false;
bool channelOn = false;               // open from START until STOP or the cutoff
uint8_t stepIdx = 0;
unsigned long seqStart = 0;
unsigned long lastCmd = 0;

char rxBuf[64];
uint8_t rxLen = 0;
bool rxOverflow = false;

// ---- Outputs ------------------------------------------------------------------
void allOff() {
  for (uint8_t i = 0; i < NUM_SEQ; i++) digitalWrite(SEQ_PINS[i], LOW);
  channelOn = false;
}

void startSequence() {
  allOff();
  stepIdx = 0;
  seqStart = millis();
  running = true;
  channelOn = true;
}

void stopSequence() {
  running = false;
  allOff();
}

// ---- Commands -----------------------------------------------------------------
void handleCommand(char *cmd) {
  for (char *p = cmd; *p; p++) *p = toupper(*p);
  bool valid = true;

  if (strcmp(cmd, "START") == 0) {
    bool wasRunning = running;
    startSequence();
    Serial.println(wasRunning ? "OK START (restarted)" : "OK START");
  } else if (strcmp(cmd, "STOP") == 0) {
    stopSequence();
    Serial.println("OK STOP");
  } else if (strcmp(cmd, "STATUS") == 0) {
    Serial.printf("STATUS running=%d channel=%d step=%u/%u elapsed=%lu ms\n",
                  running, channelOn, stepIdx, NUM_STEPS,
                  running ? millis() - seqStart : 0UL);
  } else if (strcmp(cmd, "HELP") == 0) {
    Serial.println("COMMANDS: START STOP STATUS HELP");
  } else {
    valid = false;
    Serial.printf("ERR unknown command: %s\n", cmd);
  }

  if (valid) lastCmd = millis();   // only real commands keep the channel alive
}

// Collects characters into a line without blocking.
// Accepts \n, \r or \r\n endings (phone terminal apps differ).
void readSerial() {
  while (Serial.available()) {
    char c = Serial.read();

    if (c == '\n' || c == '\r') {
      if (rxOverflow) {
        Serial.println("ERR line too long");
      } else {
        while (rxLen && rxBuf[rxLen - 1] == ' ') rxLen--;   // trim end
        rxBuf[rxLen] = '\0';
        if (rxLen) handleCommand(rxBuf);
      }
      rxLen = 0;
      rxOverflow = false;
    } else if (rxLen == 0 && c == ' ') {
      // skip leading spaces
    } else if (rxLen < sizeof(rxBuf) - 1) {
      rxBuf[rxLen++] = c;
    } else {
      rxOverflow = true;   // discard the rest of this line
    }
  }
}

// ---- Main -----------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  for (uint8_t i = 0; i < NUM_SEQ; i++) pinMode(SEQ_PINS[i], OUTPUT);
  allOff();                         // safe state at power-up
  Serial.println("READY hot-flash test. Commands: START STOP STATUS HELP");
}

void loop() {
  readSerial();                     // runs every pass, so STOP acts within ~1 ms
  unsigned long now = millis();

  if (running) {
    unsigned long elapsed = now - seqStart;

    // Apply every step whose time has come (no delay() anywhere)
    while (stepIdx < NUM_STEPS && elapsed >= SEQUENCE[stepIdx].t) {
      const Step &s = SEQUENCE[stepIdx];
      digitalWrite(SEQ_PINS[s.led], s.on ? HIGH : LOW);
      stepIdx++;
    }

    if (stepIdx >= NUM_STEPS && elapsed >= SEQ_END_MS) {
      running = false;              // the channel stays on until STOP or the cutoff
      Serial.println("DONE");
    }
  }

  if (channelOn && now - lastCmd > CUTOFF_MS) {
    stopSequence();
    Serial.printf("CUTOFF no command for %lu ms\n", CUTOFF_MS);
  }
}
