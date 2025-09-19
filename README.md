# IB SmartPortal

Dark-mode local desktop app built with Python 3.11+ and CustomTkinter. Roles: admin, teacher, student. SQLite persistence, FAISS vector index, Cohere embeddings and rerank. No server.

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
export COHERE_API_KEY=YOUR_KEY
python main.py
```

## Flow

- Admin: 📚 upload PDFs, ⚙️ Train Index, persists to disk, resumable.
- Teacher: 🧪 create assessments, record grades.
- Student: view grades.
- All: 🧠 chat with grounded answers and citations like "📚 Title — p. 123".

## Notes

- Large PDFs supported; background indexing with pause/resume/cancel, progress, ETA, and crash-safe resume.
- Vector store persisted under `data/index`.
- SQLite file at `data/app.db`.
