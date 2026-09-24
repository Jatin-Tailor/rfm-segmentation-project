"""
app.py
Streamlit frontend for the RFM Segmentation Engine.

Talks to the FastAPI backend over HTTP (via `requests`). Run the backend
first, then this app.
"""

import os

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API_BASE_URL = os.environ.get("RFM_API_URL", "http://localhost:8000")

SEGMENT_COLORS = {
    "Champions": "#2ECC71",
    "Loyal Customers": "#3498DB",
    "At-Risk": "#F39C12",
    "Hibernating": "#E74C3C",
}

st.set_page_config(
    page_title="Customer Segmentation & RFM Engine",
    layout="wide",
    page_icon="📊",
)

# --------------------------------------------------------------------------
# Session state
# --------------------------------------------------------------------------
if "active_run" not in st.session_state:
    st.session_state.active_run = None  # dict: run summary
if "segments_df" not in st.session_state:
    st.session_state.segments_df = None  # DataFrame
if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0  # bump to force-reset the file_uploader widget


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def fetch_runs():
    try:
        resp = requests.get(f"{API_BASE_URL}/api/runs", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        st.sidebar.error(f"Could not reach backend at {API_BASE_URL}: {exc}")
        return []


def load_run_segments(run_id: int, run_summary: dict):
    resp = requests.get(f"{API_BASE_URL}/api/runs/{run_id}/segments", timeout=15)
    resp.raise_for_status()
    df = pd.DataFrame(resp.json())
    st.session_state.active_run = run_summary
    st.session_state.segments_df = df


def upload_file(file):
    files = {"file": (file.name, file.getvalue(), "text/csv")}
    resp = requests.post(f"{API_BASE_URL}/api/upload", files=files, timeout=120)
    if resp.status_code != 200:
        detail = resp.json().get("detail", resp.text)
        raise RuntimeError(detail)
    data = resp.json()
    st.session_state.active_run = data["run"]
    st.session_state.segments_df = pd.DataFrame(data["segments"])


def clear_uploaded_file():
    """Resets the file_uploader widget by changing its key, without touching the DB."""
    st.session_state.uploader_key += 1


def delete_run(run_id: int):
    resp = requests.delete(f"{API_BASE_URL}/api/runs/{run_id}", timeout=15)
    if resp.status_code != 200:
        detail = resp.json().get("detail", resp.text)
        raise RuntimeError(detail)
    # If the deleted run was the one currently on screen, clear the dashboard too.
    if st.session_state.active_run and st.session_state.active_run.get("id") == run_id:
        st.session_state.active_run = None
        st.session_state.segments_df = None


# --------------------------------------------------------------------------
# Sidebar: upload + run history
# --------------------------------------------------------------------------
with st.sidebar:
    st.title("📊 RFM Engine")
    st.caption(f"Backend: {API_BASE_URL}")

    st.subheader("Upload transaction log")
    uploaded_file = st.file_uploader(
        "CSV with TransactionID, CustomerID, OrderDate, Amount "
        "(Email optional)",
        type=["csv"],
        key=f"uploader_{st.session_state.uploader_key}",
    )
    if uploaded_file is not None:
        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("Process file", type="primary", use_container_width=True):
                with st.spinner("Cleaning data, computing RFM, and clustering..."):
                    try:
                        upload_file(uploaded_file)
                        st.success("Run completed and saved.")
                    except RuntimeError as exc:
                        st.error(f"Upload rejected: {exc}")
                    except requests.RequestException as exc:
                        st.error(f"Could not reach backend: {exc}")
        with col_b:
            st.button(
                "Clear selection",
                use_container_width=True,
                on_click=clear_uploaded_file,
                help="Removes the selected file from this form. Does not affect saved runs.",
            )

    st.divider()
    st.subheader("Past runs")
    runs = fetch_runs()
    if runs:
        options = {
            f"#{r['id']} · {r['filename']} · {r['total_customers']} customers": r
            for r in runs
        }
        choice = st.selectbox("Load a previous run", list(options.keys()))
        selected = options[choice]

        col_load, col_delete = st.columns(2)
        with col_load:
            if st.button("Load", use_container_width=True):
                with st.spinner("Loading..."):
                    load_run_segments(selected["id"], selected)
        with col_delete:
            if st.button("🗑️ Delete", use_container_width=True):
                st.session_state.pending_delete = selected["id"]

        if st.session_state.get("pending_delete") == selected["id"]:
            st.warning(
                f"Permanently delete run #{selected['id']} "
                f"({selected['filename']}) and all its customer data?"
            )
            confirm_col, cancel_col = st.columns(2)
            with confirm_col:
                if st.button(
                    "Yes, delete permanently",
                    type="primary",
                    use_container_width=True,
                ):
                    try:
                        delete_run(selected["id"])
                        st.session_state.pending_delete = None
                        st.success(f"Run #{selected['id']} deleted.")
                        st.rerun()
                    except RuntimeError as exc:
                        st.error(f"Could not delete: {exc}")
                    except requests.RequestException as exc:
                        st.error(f"Could not reach backend: {exc}")
            with cancel_col:
                if st.button("Cancel", use_container_width=True):
                    st.session_state.pending_delete = None
                    st.rerun()
    else:
        st.caption("No runs yet — upload a CSV to get started.")


# --------------------------------------------------------------------------
# Main dashboard
# --------------------------------------------------------------------------
st.title("Customer Segmentation & RFM Analysis Engine")

run = st.session_state.active_run
df = st.session_state.segments_df

if run is None or df is None or df.empty:
    st.info(
        "Upload a transaction CSV in the sidebar to run the segmentation "
        "pipeline, or load a previous run."
    )
    st.markdown(
        "**Required columns:** `TransactionID`, `CustomerID`, `OrderDate`, "
        "`Amount`  \n**Optional:** `Email`"
    )
    st.stop()

# --- KPI row ---------------------------------------------------------------
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Revenue", f"${run['total_revenue']:,.2f}")
col2.metric("Processed Customers", f"{run['total_customers']:,}")
segment_counts = run.get("segment_counts") or df["segment"].value_counts().to_dict()
champions = segment_counts.get("Champions", 0)
at_risk = segment_counts.get("At-Risk", 0)
col3.metric("Champions", champions)
col4.metric("At-Risk", at_risk)

st.caption(
    f"Run #{run['id']} · file: {run['filename']} · "
    f"uploaded: {run['upload_timestamp']}"
)

st.divider()

# --- Cohort size bar chart --------------------------------------------------
left, right = st.columns([1, 2])
with left:
    st.subheader("Cohort sizes")
    counts_df = (
        pd.Series(segment_counts, name="customers")
        .reindex(["Champions", "Loyal Customers", "At-Risk", "Hibernating"])
        .fillna(0)
        .reset_index()
        .rename(columns={"index": "segment"})
    )
    bar_fig = px.bar(
        counts_df,
        x="segment",
        y="customers",
        color="segment",
        color_discrete_map=SEGMENT_COLORS,
    )
    bar_fig.update_layout(showlegend=False, height=380)
    st.plotly_chart(bar_fig, use_container_width=True)

# --- 3D scatter --------------------------------------------------------------
with right:
    st.subheader("3D RFM cluster view (log-transformed)")
    plot_df = df.copy()
    for col, src in [("log_recency", "recency"), ("log_frequency", "frequency"), ("log_monetary", "monetary")]:
        if col not in plot_df.columns:
            plot_df[col] = plot_df[src].apply(lambda v: pd.NA)
    # Fall back to computing log values client-side if the API didn't include them.
    import numpy as np

    if plot_df["log_recency"].isna().all():
        plot_df["log_recency"] = np.log1p(plot_df["recency"])
        plot_df["log_frequency"] = np.log1p(plot_df["frequency"])
        plot_df["log_monetary"] = np.log1p(plot_df["monetary"])

    scatter_fig = px.scatter_3d(
        plot_df,
        x="log_recency",
        y="log_frequency",
        z="log_monetary",
        color="segment",
        color_discrete_map=SEGMENT_COLORS,
        hover_data=["customer_id"],
        labels={
            "log_recency": "log(Recency)",
            "log_frequency": "log(Frequency)",
            "log_monetary": "log(Monetary)",
        },
    )
    scatter_fig.update_layout(height=420, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(scatter_fig, use_container_width=True)

st.divider()

# --- Actionable export -------------------------------------------------------
st.subheader("Targeted export")
segment_options = ["All"] + sorted(df["segment"].unique().tolist())
selected_segment = st.selectbox("Filter by cohort", segment_options)

filtered = df if selected_segment == "All" else df[df["segment"] == selected_segment]
display_cols = ["customer_id", "email", "recency", "frequency", "monetary", "segment"]
st.dataframe(filtered[display_cols], use_container_width=True, height=320)

export_cols = ["customer_id", "email"]
csv_bytes = filtered[export_cols].rename(
    columns={"customer_id": "CustomerID", "email": "Email"}
).to_csv(index=False).encode("utf-8")

file_suffix = selected_segment.replace(" ", "_").lower()
st.download_button(
    label=f"Download '{selected_segment}' list as CSV ({len(filtered)} customers)",
    data=csv_bytes,
    file_name=f"run_{run['id']}_{file_suffix}.csv",
    mime="text/csv",
    type="primary",
)