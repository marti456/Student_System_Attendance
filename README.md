# NFC Student Attendance System

Diploma thesis project, Technical University of Sofia. Students check in to a class by tapping their phone on an NFC reader in the room. The phone acts as a virtual card (Android Host Card Emulation), and the signed packet it sends is verified by the server.

## Architecture

```
┌──────────────────┐   NFC (ISO-DEP / APDU)   ┌─────────────────────┐   HTTP POST /checkin   ┌──────────────────┐
│  Android phone   │ ───────────────────────► │  ESP32 + PN532      │ ─────────────────────► │  FastAPI server  │
│  (HCE service)   │ ◄─────────────────────── │  (reader in room)   │ ◄───────────────────── │  + SQLite        │
└──────────────────┘  Faculty no. + ATC + HMAC└─────────────────────┘     200 / 403 / 404    └────────┬─────────┘
                                                                                                       │
                                                                                              Web panel (HTML/JS)
```

| Component | Technologies |
|---|---|
| Mobile app | Kotlin, Android HCE, Retrofit, EncryptedSharedPreferences (Keystore) |
| Reader | ESP32-WROOM32, PN532 (software SPI), Adafruit_PN532, ArduinoJson v7 |
| Server | FastAPI, SQLAlchemy (async), SQLite, JWT (python-jose), bcrypt (passlib) |
| Web panel | Vanilla JS, HTML, CSS |

## How the protocol works

1. The student logs in to the app (`/auth/login`) and receives a JWT.
2. The app calls `/auth/provision-key` and receives a **unique 256-bit HMAC key**, the faculty number and the current ATC. These are stored encrypted on the phone.
3. When the phone touches the reader, the ESP32 sends a `SELECT AID` APDU (`A0 00 00 02 47 10 01`).
4. `NfcHceService` replies with a binary packet:

   ```
   [1 B faculty no. length][faculty no. (UTF-8)][4 B ATC, big-endian][32 B HMAC-SHA256][SW 90 00]
   ```

   The HMAC is computed over `"facultyNo|ATC"` with the student's key. The packet is about 46–48 bytes, under the 64-byte reader buffer.
5. The ESP32 parses the packet, turns it into `facultyNo|ATC|HMAC_HEX` and posts it to `/checkin` together with the room number.
6. The server checks:
   - the student exists and has a key;
   - **replay protection**: `ATC` must be strictly greater than the stored value and at most `MAX_ATC_WINDOW` (100) above it;
   - the HMAC signature (`hmac.compare_digest`);
   - a class is currently running in that room (biweekly classes are supported; students from other groups are recorded as "make-up" attendance);
   - the student has not already checked in for the same course and class type today.

## Repository structure

```
.
├── backend/
│   ├── main.py             # FastAPI app, static files, DB startup
│   ├── models.py           # SQLAlchemy models
│   ├── schemas.py          # Pydantic schemas
│   ├── auth.py             # Login, JWT, registration, provision-key
│   ├── routers/
│   │   ├── attendance.py   # /checkin and attendance management
│   │   └── administration.py  # Courses, groups, curriculum, schedule
│   ├── index.html, app.js, styles.css   # Web panel
├── android/
│   ├── NfcHceService.kt    # HCE service
│   ├── StudentPrefs.kt     # Encrypted storage
│   ├── MainActivity.kt     # Login + key provisioning
│   ├── HomeActivity.kt     # Main screen, NFC status
│   └── ApiService.kt       # Retrofit client
└── firmware/
    └── main.cpp            # ESP32 + PN532 reader
```

> Adjust the tree if the actual repo layout differs.

## Getting started

### 1. Server

```bash
cd backend
pip install fastapi uvicorn sqlalchemy aiosqlite passlib[bcrypt] "python-jose[cryptography]" python-multipart
uvicorn main:app --host 0.0.0.0 --port 8000
```

- The web panel is at `http://<ip>:8000/` and the API docs at `/docs`.
- On first start `attendance.db` is created together with an administrator `admin` / `admin123`. **Change this password immediately.**
- Replace `SECRET_KEY` in `auth.py` with a long random string.

### 2. Android app

1. Open the project in Android Studio.
2. Set `BASE_URL` in `ApiService.kt` to your server address.
3. In `AndroidManifest.xml`, register `NfcHceService` with an `apduservice.xml` whose AID is `A0000002471001`, and add the `android.permission.NFC` permission.
4. Install on a phone with NFC and HCE support.

The app uses plain HTTP for development. If you point it at a local HTTP server, cleartext traffic must be allowed.

### 3. Reader (ESP32 + PN532)

Wiring:

| ESP32 pin | Connects to |
|---|---|
| 3V3 | PN532 VCC (**3.3 V only**) |
| GND | PN532 GND, LED cathodes (via 220 Ω), buzzer − |
| 14 | PN532 SCK |
| 13 | PN532 MOSI |
| 26 | PN532 MISO |
| 27 | PN532 SS |
| 25 | Green LED + (220 Ω) |
| 32 | Red LED + (220 Ω) |
| 33 | Buzzer + |

PN532 DIP switches for SPI mode: `SEL0 = OFF`, `SEL1 = ON`.

Libraries: `Adafruit PN532`, `ArduinoJson` (v7). In `main.cpp` set `WIFI_SSID`, `WIFI_PASS`, `SERVER_URL` and `ROOM_NUMBER` (different for each room). Do not commit your real Wi-Fi password.

## Main API endpoints

| Method | Path | Role | Description |
|---|---|---|---|
| POST | `/auth/login` | all | Login (OAuth2 form), returns a JWT |
| POST | `/auth/provision-key` | student | Returns the HMAC key, faculty number and ATC |
| POST | `/auth/provision-key/reset` | admin | Resets a student's key (e.g. after a phone change) |
| POST | `/auth/register/{student,teacher,admin}` | admin | Register users |
| POST | `/checkin` | reader | Check-in from an NFC payload |
| GET | `/attendance` | all | Attendance list (pagination, search; students see only their own) |
| POST/PATCH/DELETE | `/attendance` | teacher, admin | Manual management |
| * | `/admin/courses`, `/admin/groups`, `/admin/group-courses`, `/admin/schedules` | admin | Curriculum and schedule |

## Roles

- **Student**: logs in to the app and sees only their own attendance in the web panel.
- **Teacher**: sees their own schedule, adds and edits attendance only for their own courses.
- **Administrator**: manages everything.

## Security notes and known limitations

- The key is unique per student, generated on the server and stored in the Android Keystore (via `EncryptedSharedPreferences`).
- The ATC is incremented on every tap on the phone side. If the phone is tapped several times without a successful `/checkin`, its ATC drifts from the server's. The window of 100 tolerates this. A larger gap requires logging in to the app again or a reset by an administrator.
- The reader talks to the server over HTTP. Production use needs HTTPS and a protected network.
- The reader is not authenticated: `/checkin` is public and accepts any validly signed packet. A rogue reader could forward an intercepted packet, but replay protection rejects it once used.
- CORS is open (`*`) for development.
- This is an academic project and has not been security-reviewed for production use.

## License

Add a license of your choice (e.g. MIT), or leave the repo unlicensed if it is only for the thesis.