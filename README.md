# Driver Drowsiness & Distraction Detection System

A real-time computer vision system that monitors a driver through a webcam or recorded video and detects **drowsiness, yawning, and distraction**.

The system is built using **Python, OpenCV, and MediaPipe** and works without training a custom model or requiring a GPU.

## Features

- 😴 Drowsiness detection using **Eye Aspect Ratio (EAR)**
- 🥱 Yawning detection using **Mouth Aspect Ratio (MAR)**
- 👀 Distraction detection using **head pose estimation**
- 🎯 Consecutive-frame detection to reduce false alerts
- 📊 Real-time EAR, MAR, head pose and FPS display
- 🔊 Audio alarm for detected events
- 🎥 Webcam and recorded-video support
- 💾 Annotated video output
- 📄 CSV event logging
- ⚙️ Configurable detection thresholds
- 🧪 Self-test without requiring a webcam

## Technology Stack

- **Python**
- **OpenCV**
- **MediaPipe**
- **NumPy**
- **Computer Vision**
- **Facial Landmark Detection**

## How It Works

```text
Webcam / Video
      |
      v
MediaPipe Face Mesh
      |
      v
Facial Landmarks
      |
      +------------------+------------------+
      |                  |                  |
      v                  v                  v
     EAR                MAR             Head Pose
      |                  |                  |
      v                  v                  v
Drowsiness             Yawning          Distraction
      |                  |                  |
      +------------------+------------------+
                         |
                         v
                Consecutive-Frame
                  State Machine
                         |
                         v
                 Alert + Logging
                         |
                         v
                Video / CSV Output
```

## Detection Methods

### Drowsiness Detection

The system uses the **Eye Aspect Ratio (EAR)** to measure eye openness.

```text
EAR = (|p2-p6| + |p3-p5|) / (2 × |p1-p4|)
```

When the eyes remain closed and the EAR stays below the configured threshold for a number of consecutive frames, a drowsiness alert is generated.

### Yawning Detection

The **Mouth Aspect Ratio (MAR)** is used to measure the amount of mouth opening.

A high MAR maintained for multiple consecutive frames is used to detect yawning.

### Distraction Detection

The system estimates the driver's head orientation using `cv2.solvePnP`.

It tracks:

- **Yaw** — left/right head rotation
- **Pitch** — up/down head movement
- **Roll** — sideways head rotation

If the driver looks away from the road for a sustained number of frames, a distraction alert is generated.

## Consecutive-Frame Detection

The detector does not trigger an alert from a single frame.

For each condition, a counter is maintained:

```text
Condition detected
       |
       v
Counter increases
       |
       v
Condition continues?
   /           \
 Yes            No
  |              |
  v              v
Continue       Reset
  |
  v
Threshold reached
  |
  v
Alert triggered
```

This helps prevent normal blinking or short head movements from being incorrectly classified as drowsiness or distraction.

## Requirements

- Python 3.9 or newer
- Webcam (for real-time detection)
- Windows, Linux or macOS

A webcam is **not required** when processing a recorded video or running the self-test.

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/Aniketsaxena2828/Driver-drowsiness-detection.git
cd Driver-drowsiness-detection
```

### 2. Create a virtual environment

```bash
python -m venv venv
```

### 3. Activate the virtual environment

**Windows:**

```bash
venv\Scripts\activate
```

**Linux / macOS:**

```bash
source venv/bin/activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

## Run the Project

### Self-test

Run the detector pipeline without using a webcam:

```bash
python test_detector.py
```

### Live webcam

```bash
python main.py
```

### Process a recorded video

```bash
python main.py --source drive.mp4
```

### Save annotated video and event log

```bash
python main.py --source drive.mp4 --output outputs/annotated_output.mp4 --log outputs/events_log.csv
```

### Run without sound

```bash
python main.py --no-sound
```

### Run without display

```bash
python main.py --source drive.mp4 --no-display
```

Press **`q`** or **ESC** to stop the application when the display window is active.

## Configuration

Detection thresholds can be changed directly from the command line.

| Option | Default | Description |
|---|---:|---|
| `--source` | `webcam` | Webcam, camera index, or video file |
| `--output` | — | Path for annotated video |
| `--log` | — | Path for CSV event log |
| `--ear-threshold` | `0.25` | EAR below this value is considered closed |
| `--ear-frames` | `20` | Consecutive closed-eye frames for drowsiness |
| `--mar-threshold` | `0.60` | MAR above this value is considered open |
| `--mar-frames` | `15` | Consecutive frames required for yawning |
| `--yaw-threshold` | `25.0` | Allowed head yaw angle |
| `--pitch-threshold` | `20.0` | Allowed head pitch angle |
| `--pose-frames` | `20` | Consecutive looking-away frames for distraction |
| `--alarm` | `assets/alarm.wav` | Alert sound file |
| `--no-sound` | Off | Disable audio alerts |
| `--no-display` | Off | Disable display window |
| `--no-landmarks` | Off | Disable facial landmark drawing |
| `--max-frames` | `0` | Stop after N frames; `0` means unlimited |

Example:

```bash
python main.py --ear-threshold 0.22 --ear-frames 25 --yaw-threshold 20
```

## Output

The system can generate an annotated video containing:

- Facial landmarks
- EAR value
- MAR value
- Head pose values
- Detection counters
- FPS
- Alert messages

It can also generate a CSV event log.

Example:

```csv
timestamp,video_time_sec,frame,event,details
2026-09-18 13:14:41,2.63,79,DROWSINESS,EAR=0.020
2026-09-18 13:14:42,4.47,134,YAWN,MAR=0.800
```

## Project Structure

```text
Driver-drowsiness-detection/
│
├── main.py
├── detector.py
├── face_mesh.py
├── utils.py
├── test_detector.py
├── requirements.txt
│
├── assets/
│   └── alarm.wav
│
├── outputs/
│
├── README.md
├── LICENSE
└── .gitignore
```

## Troubleshooting

### Camera not detected

If the webcam cannot be opened, check whether another application is using the camera.

You can also try another camera index:

```bash
python main.py --source 1
```

### MediaPipe installation issue

Install the required dependencies again:

```bash
pip install -r requirements.txt
```

If your environment has a MediaPipe compatibility issue, use the version specified in `requirements.txt`.

### No audio

The visual alert will still work if the audio alarm is unavailable.

You can disable audio using:

```bash
python main.py --no-sound
```

### Low FPS

Try disabling landmark visualization:

```bash
python main.py --no-landmarks
```

You can also use a smaller input video resolution.

## Key Concepts

This project demonstrates several important computer vision concepts:

- Facial landmark detection
- Eye Aspect Ratio (EAR)
- Mouth Aspect Ratio (MAR)
- Head pose estimation
- Perspective-n-Point (`solvePnP`)
- Real-time video processing
- Threshold-based classification
- Consecutive-frame state machines
- Event logging and alert generation

## Future Improvements

- Driver-specific threshold calibration
- Improved night-time detection
- Deep-learning based drowsiness classification
- Mobile application
- Vehicle integration
- Cloud-based monitoring
- Driver monitoring dashboard

## License

MIT License
