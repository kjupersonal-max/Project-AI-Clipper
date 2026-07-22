# Project AI Clipper

Private application for analyzing VODs, generating clip candidates, and preparing content for publishing.

## Prerequisites

- **Node.js** 20+ and npm
- **Python** 3.11+
- **FFmpeg** (includes `ffmpeg` and `ffprobe` in PATH)

### Verify FFmpeg installation

```powershell
ffmpeg -version
ffprobe -version
```

Both commands should print version information. If either is missing, install FFmpeg and add it to your PATH before using video inspection or audio extraction.

## Project structure

```
Project AI clipper/
├── frontend/   # Next.js dashboard and upload UI
├── backend/    # FastAPI upload and processing API
└── README.md
```

## Backend setup

From the project root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

On macOS/Linux:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Verify the API is running:

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status":"healthy"}
```

### Backend endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/api/uploads` | Multipart video upload (`file`) |
| GET | `/api/projects/{project_id}` | Project state and metadata |
| GET | `/api/projects/{project_id}/media/video` | Stream uploaded video for preview |
| POST | `/api/projects/{project_id}/inspect` | Inspect video with ffprobe |
| POST | `/api/projects/{project_id}/extract-audio` | Extract mono 16 kHz PCM WAV audio |

Uploaded videos are stored under `backend/uploads/{project_id}/`.  
Project metadata is stored in `backend/uploads/{project_id}/project.json`.  
Extracted audio is stored under `backend/audio/{project_id}/audio.wav`.

### Processing workflow (API)

Replace `{project_id}` with the ID returned from upload.

```powershell
# 1. Inspect uploaded video
curl -X POST http://localhost:8000/api/projects/{project_id}/inspect

# 2. Extract transcription-ready audio
curl -X POST http://localhost:8000/api/projects/{project_id}/extract-audio

# 3. Fetch current project state
curl http://localhost:8000/api/projects/{project_id}
```

Inspection returns structured metadata including duration, resolution, codecs, frame rate, and audio presence.  
Audio extraction outputs mono WAV at 16 kHz, 16-bit PCM.

### Run backend tests

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest
```

## Frontend setup

From the project root:

```powershell
cd frontend
npm install
```

Copy environment variables (if needed):

```powershell
copy .env.example .env.local
```

Start the development server:

```powershell
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

| Page | URL |
|------|-----|
| Dashboard | http://localhost:3000 |
| Upload VOD | http://localhost:3000/upload |
| Project processing | http://localhost:3000/projects/{project_id} |

### Frontend environment

`frontend/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Optional (defaults to 5 GB):

```env
NEXT_PUBLIC_MAX_UPLOAD_SIZE_BYTES=5368709120
```

## Run both services

Use two terminals:

**Terminal 1 — backend**

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Terminal 2 — frontend**

```powershell
cd frontend
npm run dev
```

## End-to-end flow

1. Open `/upload` and upload an MP4, MOV, MKV, or WebM file.
2. Click **Continue to Processing** to open the project page.
3. Click **Inspect Video** to run ffprobe and populate metadata.
4. Click **Extract Audio** to generate mono 16 kHz WAV under `backend/audio/{project_id}/`.
5. Review processing status and the activity log on the project page.

Supported upload formats: `.mp4`, `.mov`, `.mkv`, `.webm`  
Default max upload size: **5 GB**

## Development checks

```powershell
cd frontend
npm run lint
npm run build
```

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest
python -c "from app.main import app; print(app.title)"
```
