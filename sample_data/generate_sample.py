"""
generate_sample.py
Creates a synthetic e-commerce transaction CSV for testing the pipeline.
Produces distinct customer archetypes (champions, loyal, at-risk, hibernating,
plus some noisy/dirty rows) so clustering has real structure to find.

Usage:
    python generate_sample.py [output_path] [--customers N]
"""

import argparse
import random
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

RNG_SEED = 42


def generate(num_customers: int = 300) -> pd.DataFrame:
    random.seed(RNG_SEED)
    np.random.seed(RNG_SEED)

    today = datetime(2025, 1, 1)
    rows = []
    txn_id = 100000

    archetypes = [
        # name, share, days_since_last_range, order_count_range, avg_amount_range
        ("champion", 0.15, (0, 10), (15, 40), (80, 250)),
        ("loyal", 0.30, (5, 40), (8, 20), (40, 120)),
        ("at_risk", 0.30, (60, 150), (3, 10), (30, 90)),
        ("hibernating", 0.25, (180, 400), (1, 4), (15, 60)),
    ]

    customer_num = 1
    for name, share, recency_range, freq_range, amt_range in archetypes:
        n = int(num_customers * share)
        for _ in range(n):
            cust_id = f"CUST{customer_num:05d}"
            customer_num += 1
            email = f"{cust_id.lower()}@example.com"

            n_orders = random.randint(*freq_range)
            days_since_last = random.randint(*recency_range)
            last_order_date = today - timedelta(days=days_since_last)

            for i in range(n_orders):
                order_date = last_order_date - timedelta(
                    days=random.randint(0, 300)
                )
                amount = round(np.random.uniform(*amt_range), 2)
                rows.append(
                    {
                        "TransactionID": f"T{txn_id}",
                        "CustomerID": cust_id,
                        "OrderDate": order_date.strftime("%Y-%m-%d"),
                        "Amount": amount,
                        "Email": email,
                    }
                )
                txn_id += 1

    df = pd.DataFrame(rows)

    # --- Inject some intentionally dirty rows to exercise the cleaning step ---
    dirty_rows = []

    # duplicate TransactionID
    dup = df.iloc[0].copy()
    dirty_rows.append(dup.to_dict())

    # missing CustomerID
    dirty_rows.append(
        {
            "TransactionID": f"T{txn_id}",
            "CustomerID": None,
            "OrderDate": "2024-05-01",
            "Amount": 50.0,
            "Email": "orphan@example.com",
        }
    )
    txn_id += 1

    # unparseable date
    dirty_rows.append(
        {
            "TransactionID": f"T{txn_id}",
            "CustomerID": "CUST00001",
            "OrderDate": "not-a-date",
            "Amount": 30.0,
            "Email": "cust00001@example.com",
        }
    )
    txn_id += 1

    # negative amount (refund)
    dirty_rows.append(
        {
            "TransactionID": f"T{txn_id}",
            "CustomerID": "CUST00002",
            "OrderDate": "2024-06-01",
            "Amount": -25.0,
            "Email": "cust00002@example.com",
        }
    )

    df = pd.concat([df, pd.DataFrame(dirty_rows)], ignore_index=True)
    df = df.sample(frac=1, random_state=RNG_SEED).reset_index(drop=True)
    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "output_path", nargs="?", default="sample_transactions.csv"
    )
    parser.add_argument("--customers", type=int, default=300)
    args = parser.parse_args()

    data = generate(args.customers)
    data.to_csv(args.output_path, index=False)
    print(f"Wrote {len(data)} rows to {args.output_path}")
