"""
rfm_engine.py
The data-science core of the application:

    1. validate_and_clean()  -> raw CSV bytes -> cleaned transaction DataFrame
    2. compute_rfm()         -> cleaned transactions -> per-customer R, F, M
    3. cluster_and_label()   -> RFM table -> KMeans clusters mapped to
                                 permanent business labels

Kept independent of FastAPI/SQLAlchemy so it can be unit-tested in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from typing import Dict, List

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

MANDATORY_COLUMNS = ["TransactionID", "CustomerID", "OrderDate", "Amount"]
OPTIONAL_COLUMNS = ["Email"]
MIN_VALID_CUSTOMERS = 50
N_CLUSTERS = 4

# Ordered worst -> best; used to map composite-score rank to a business label.
SEGMENT_LABELS_BY_RANK = [
    "Hibernating",      # rank 0: lowest composite score
    "At-Risk",          # rank 1
    "Loyal Customers",  # rank 2
    "Champions",        # rank 3: highest composite score
]


class DataValidationError(Exception):
    """Raised when the uploaded CSV fails schema or business-rule validation."""


@dataclass
class CleaningReport:
    rows_in: int = 0
    rows_dropped_duplicate_txn: int = 0
    rows_dropped_missing_ids_or_dates: int = 0
    rows_dropped_negative_amount: int = 0
    rows_out: int = 0
    valid_customers: int = 0
    notes: List[str] = field(default_factory=list)


def validate_and_clean(file_bytes: bytes) -> tuple[pd.DataFrame, CleaningReport]:
    """
    Reads raw CSV bytes, verifies the mandatory schema, and applies the
    cleaning rules described in the spec. Returns the cleaned transaction
    DataFrame plus a report of what was dropped and why.
    """
    report = CleaningReport()

    try:
        df = pd.read_csv(BytesIO(file_bytes))
    except Exception as exc:  # noqa: BLE001 - surface as a validation error
        raise DataValidationError(f"Could not parse file as CSV: {exc}") from exc

    report.rows_in = len(df)

    # --- Subset schema validation ---------------------------------------
    missing = [c for c in MANDATORY_COLUMNS if c not in df.columns]
    if missing:
        raise DataValidationError(
            f"Missing mandatory column(s): {', '.join(missing)}. "
            f"Required columns are: {', '.join(MANDATORY_COLUMNS)}."
        )

    keep_cols = MANDATORY_COLUMNS + [c for c in OPTIONAL_COLUMNS if c in df.columns]
    df = df[keep_cols].copy()
    if "Email" not in df.columns:
        df["Email"] = None
        report.notes.append("No 'Email' column found; export emails will be blank.")

    # --- Drop duplicate TransactionIDs -----------------------------------
    before = len(df)
    df = df.drop_duplicates(subset="TransactionID", keep="first")
    report.rows_dropped_duplicate_txn = before - len(df)

    # --- Drop rows missing critical IDs or with unparseable dates --------
    before = len(df)
    df["OrderDate"] = pd.to_datetime(df["OrderDate"], errors="coerce")
    df["Amount"] = pd.to_numeric(df["Amount"], errors="coerce")
    df = df.dropna(subset=["CustomerID", "TransactionID", "OrderDate"])
    report.rows_dropped_missing_ids_or_dates = before - len(df)

    # --- Filter out negative Amount values (refunds/returns) -------------
    before = len(df)
    df = df.dropna(subset=["Amount"])
    df = df[df["Amount"] >= 0]
    report.rows_dropped_negative_amount = before - len(df)

    df["CustomerID"] = df["CustomerID"].astype(str).str.strip()

    report.rows_out = len(df)
    report.valid_customers = df["CustomerID"].nunique()

    if report.valid_customers < MIN_VALID_CUSTOMERS:
        raise DataValidationError(
            f"Only {report.valid_customers} valid customer(s) remained after "
            f"cleaning; at least {MIN_VALID_CUSTOMERS} are required."
        )

    return df, report


def compute_rfm(df: pd.DataFrame) -> pd.DataFrame:
    """
    Groups cleaned transactions by CustomerID and computes Recency,
    Frequency, and Monetary metrics.
    """
    max_date = df["OrderDate"].max()

    # Keep the first non-null email seen per customer, if any.
    email_map = (
        df.dropna(subset=["Email"])
        .groupby("CustomerID")["Email"]
        .first()
    )

    grouped = df.groupby("CustomerID").agg(
        last_order_date=("OrderDate", "max"),
        frequency=("TransactionID", "nunique"),
        monetary=("Amount", "sum"),
    )

    grouped["recency"] = (max_date - grouped["last_order_date"]).dt.days + 1
    grouped = grouped.drop(columns=["last_order_date"])
    grouped["email"] = grouped.index.map(email_map).where(
        grouped.index.isin(email_map.index), None
    )

    rfm = grouped.reset_index().rename(columns={"CustomerID": "customer_id"})
    return rfm[["customer_id", "email", "recency", "frequency", "monetary"]]


def cluster_and_label(rfm: pd.DataFrame) -> pd.DataFrame:
    """
    Applies log1p normalization, StandardScaler scaling, and KMeans (k=4)
    clustering to the RFM table, then deterministically maps each cluster
    to a permanent business label using a composite centroid score
    (Monetary + Frequency - Recency), computed in scaled space so all three
    dimensions are weighted equally.
    """
    rfm = rfm.copy()

    # --- Log transform to compress right-skewed tails ---------------------
    log_r = np.log1p(rfm["recency"])
    log_f = np.log1p(rfm["frequency"])
    log_m = np.log1p(rfm["monetary"])
    log_features = np.column_stack([log_r, log_f, log_m])

    # --- Scale so Euclidean distance treats R, F, M equally ---------------
    scaler = StandardScaler()
    scaled_features = scaler.fit_transform(log_features)

    rfm["log_recency"] = log_r
    rfm["log_frequency"] = log_f
    rfm["log_monetary"] = log_m

    # --- Fit KMeans ---------------------------------------------------------
    kmeans = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init=10)
    cluster_ids = kmeans.fit_predict(scaled_features)
    rfm["cluster_id"] = cluster_ids

    # --- Deterministic labeling via composite centroid score ---------------
    # centroids are in scaled space, columns ordered [recency, frequency, monetary]
    centroids = kmeans.cluster_centers_
    composite_scores = centroids[:, 2] + centroids[:, 1] - centroids[:, 0]  # M + F - R

    # Rank cluster IDs by composite score, worst -> best
    rank_order = np.argsort(composite_scores)  # ascending: lowest score first
    cluster_id_to_label: Dict[int, str] = {
        cluster_id: SEGMENT_LABELS_BY_RANK[rank]
        for rank, cluster_id in enumerate(rank_order)
    }

    rfm["segment"] = rfm["cluster_id"].map(cluster_id_to_label)

    return rfm.drop(columns=["cluster_id"])


def run_pipeline(file_bytes: bytes) -> tuple[pd.DataFrame, CleaningReport]:
    """Convenience wrapper: clean -> RFM -> cluster, in one call."""
    cleaned, report = validate_and_clean(file_bytes)
    rfm = compute_rfm(cleaned)
    labeled = cluster_and_label(rfm)
    return labeled, report
