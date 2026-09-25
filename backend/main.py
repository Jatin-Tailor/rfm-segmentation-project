import io
from io import StringIO
from typing import Optional

import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import CustomerSegment, Run, get_db, init_db
from rfm_engine import DataValidationError, run_pipeline
from schemas import RunSummaryOut, UploadResponse

app = FastAPI(
    title="RFM Segmentation Engine",
    description="Upload transaction logs, compute RFM metrics, and cluster customers.",
    version="1.0.0",
)

# Streamlit runs on a different port, so allow local cross-origin calls.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def _segment_counts(db: Session, run_id: int) -> dict:
    rows = (
        db.query(CustomerSegment.segment, CustomerSegment.id)
        .filter(CustomerSegment.run_id == run_id)
        .all()
    )
    counts: dict = {}
    for segment, _ in rows:
        counts[segment] = counts.get(segment, 0) + 1
    return counts


def _run_to_summary(db: Session, run: Run) -> RunSummaryOut:
    summary = RunSummaryOut.model_validate(run)
    summary.segment_counts = _segment_counts(db, run.id)
    return summary


@app.post("/api/upload", response_model=UploadResponse)
async def upload_transactions(
    file: UploadFile = File(...), db: Session = Depends(get_db)
):
    # 1. Validate extension for both CSV and XLSX
    if not file.filename.lower().endswith((".csv", ".xlsx")):
        raise HTTPException(status_code=400, detail="Please upload a .csv or .xlsx file.")

    file_bytes = await file.read()

    try:
        # 2. Read the file into a Pandas DataFrame based on its extension
        if file.filename.lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(file_bytes))
        else:
            df = pd.read_excel(io.BytesIO(file_bytes), engine='openpyxl')
            
        # 3. Convert back to CSV bytes so we don't break the existing run_pipeline logic
        standardized_bytes = df.to_csv(index=False).encode('utf-8')
        
        # 4. Pass the standardized data to the engine
        labeled_rfm, report = run_pipeline(standardized_bytes)
        
    except DataValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500, detail=f"Unexpected error while processing file: {exc}"
        ) from exc

    total_revenue = float(labeled_rfm["monetary"].sum())
    total_customers = int(len(labeled_rfm))

    run = Run(
        filename=file.filename,
        total_customers=total_customers,
        total_revenue=total_revenue,
        status="completed",
    )

    try:
        db.add(run)
        db.flush()  # populate run.id without committing yet

        segment_rows = [
            CustomerSegment(
                run_id=run.id,
                customer_id=row.customer_id,
                email=row.email,
                recency=float(row.recency),
                frequency=float(row.frequency),
                monetary=float(row.monetary),
                segment=row.segment,
            )
            for row in labeled_rfm.itertuples(index=False)
        ]
        db.bulk_save_objects(segment_rows)
        db.commit()
        db.refresh(run)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Database error while saving run: {exc}"
        ) from exc

    segments = (
        db.query(CustomerSegment).filter(CustomerSegment.run_id == run.id).all()
    )

    return UploadResponse(
        run=_run_to_summary(db, run),
        segments=segments,
    )


@app.get("/api/runs", response_model=list[RunSummaryOut])
def list_runs(db: Session = Depends(get_db)):
    runs = db.query(Run).order_by(Run.upload_timestamp.desc()).all()
    return [_run_to_summary(db, r) for r in runs]


@app.get("/api/runs/{run_id}", response_model=RunSummaryOut)
def get_run(run_id: int, db: Session = Depends(get_db)):
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    return _run_to_summary(db, run)


@app.get("/api/runs/{run_id}/segments")
def get_run_segments(run_id: int, db: Session = Depends(get_db)):
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")

    segments = (
        db.query(CustomerSegment).filter(CustomerSegment.run_id == run_id).all()
    )
    return [
        {
            "customer_id": s.customer_id,
            "email": s.email,
            "recency": s.recency,
            "frequency": s.frequency,
            "monetary": s.monetary,
            "segment": s.segment,
        }
        for s in segments
    ]


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: int, db: Session = Depends(get_db)):
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")

    try:
        db.delete(run)  # cascade="all, delete-orphan" removes its CustomerSegment rows too
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Database error while deleting run: {exc}"
        ) from exc

    return {"detail": f"Run {run_id} and its segments were deleted."}


@app.get("/api/runs/{run_id}/export")
def export_segment_csv(
    run_id: int,
    segment: Optional[str] = Query(
        default=None, description="Filter to a single segment, e.g. 'At-Risk'"
    ),
    db: Session = Depends(get_db),
):
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")

    query = db.query(CustomerSegment).filter(CustomerSegment.run_id == run_id)
    if segment:
        query = query.filter(CustomerSegment.segment == segment)

    rows = query.all()
    if not rows:
        raise HTTPException(
            status_code=404, detail="No customers found for that run/segment."
        )

    df = pd.DataFrame(
        [{"CustomerID": r.customer_id, "Email": r.email} for r in rows]
    )
    buffer = StringIO()
    df.to_csv(buffer, index=False)
    buffer.seek(0)

    filename_part = segment.replace(" ", "_") if segment else "all_customers"
    filename = f"run_{run_id}_{filename_part}.csv"

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )