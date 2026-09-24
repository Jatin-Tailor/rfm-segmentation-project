# Customer Segmentation & RFM Analysis Engine

A microservice-based app: non-technical users upload raw e-commerce
transaction CSVs, the backend cleans the data, computes RFM (Recency,
Frequency, Monetary) metrics, clusters customers with K-Means, and the
Streamlit frontend shows a KPI dashboard, 3D cluster visualization, and
segment-filtered CSV export for marketing.

## Structure

```
rfm_engine/
├── backend/
│   ├── main.py          # FastAPI app & endpoints
│   ├── database.py      # SQLAlchemy models (Run, CustomerSegment)
│   ├── rfm_engine.py     # Cleaning, RFM math, K-Means clustering
│   ├── schemas.py        # Pydantic response models
│   └── requirements.txt
├── frontend/
│   ├── app.py             # Streamlit dashboard
│   └── requirements.txt
└── sample_data/
    └── generate_sample.py # Creates a synthetic test CSV
```

## Quick start

See the numbered setup steps in the chat message. In short:

```bash
# Terminal 1 — backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Terminal 2 — frontend
cd frontend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py

# Terminal 3 — generate a test file (optional)
cd sample_data
python3 generate_sample.py
```

Then open http://localhost:8501, upload `sample_data/sample_transactions.csv`,
and click "Process file".

## API endpoints

| Method | Path                          | Purpose                                  |
|--------|-------------------------------|-------------------------------------------|
| POST   | `/api/upload`                 | Upload CSV, run pipeline, persist results |
| GET    | `/api/runs`                   | List past runs                            |
| GET    | `/api/runs/{id}`              | Single run summary                        |
| GET    | `/api/runs/{id}/segments`     | Full per-customer segment data            |
| GET    | `/api/runs/{id}/export?segment=At-Risk` | CSV download, optionally filtered |

Interactive API docs: http://localhost:8000/docs

## Notes

- The database is a single SQLite file (`backend/rfm_engine.db`), created
  automatically on first run.
- `k=4` clusters are deterministically mapped to Champions / Loyal Customers /
  At-Risk / Hibernating using a composite centroid score
  (Monetary + Frequency − Recency) in standardized space, so labels are
  stable across runs regardless of arbitrary cluster ID ordering.
- Required CSV columns: `TransactionID`, `CustomerID`, `OrderDate`, `Amount`.
  Optional: `Email`. Extra columns are ignored.
- Uploads are rejected (HTTP 422) if fewer than 50 valid customers remain
  after cleaning.
