import pandas as pd
import os
from datetime import datetime

def analyze_dataset():
    # Load the dataset
    file_path = 'data/HI-Small_Trans.csv'
    df = pd.read_csv(file_path)

    # Convert Date column to datetime
    df['Date'] = pd.to_datetime(df['Date'])

    # Perform initial analysis
    row_count = len(df)
    column_count = len(df.columns)

    # Check for duplicate rows (potential laundering rows)
    duplicate_rows = df.duplicated().sum()

    # Date range
    min_date = df['Date'].min()
    max_date = df['Date'].max()
    date_range_days = (max_date - min_date).days

    # Determine account ID strategy
    # Check if Account is unique across banks
    account_unique_per_bank = df.groupby(['From Bank', 'Account'])['To Bank'].nunique() == 1
    account_is_unique = account_unique_per_bank.all()

    # Create composite account ID if needed
    if not account_is_unique:
        df['Composite_Account_ID'] = df['From Bank'] + '-' + df['Account'].astype(str)
        account_id_strategy = '<From Bank>-<Account>'
    else:
        df['Composite_Account_ID'] = df['Account']
        account_id_strategy = 'Account'

    # Prepare report content
    report_content = f"""# Data Foundation Analysis Report

## Dataset Overview
- **File**: HI-Small_Trans.csv
- **Row Count**: {row_count}
- **Column Count**: {column_count}
- **Columns**: {', '.join(df.columns.tolist())}

## Data Quality
- **Duplicate Rows**: {duplicate_rows}
- **Date Range**: {min_date.strftime('%Y-%m-%d %H:%M:%S')} to {max_date.strftime('%Y-%m-%d %H:%M:%S')}
- **Date Range (Days)**: {date_range_days}

## Account ID Strategy
- **Account Uniqueness Check**: {'Unique' if account_is_unique else 'Not Unique'}
- **Selected Strategy**: {account_id_strategy}
- **Reasoning**: {'Account column is unique across banks' if account_is_unique else 'Account column is not unique across banks, using composite key'}

## Sample Data (First 5 Rows)
{df.head().to_string(index=False)}

## Analysis Timestamp
{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

    # Write to REPORT.md
    report_path = 'scoring/REPORT.md'
    os.makedirs(os.path.dirname(report_path), exist_ok=True)

    with open(report_path, 'w') as f:
        f.write(report_content)

    print(f"Analysis complete. Report written to {report_path}")
    print(f"Row count: {row_count}")
    print(f"Duplicate rows: {duplicate_rows}")
    print(f"Date range: {min_date} to {max_date}")
    print(f"Account ID strategy: {account_id_strategy}")

if __name__ == "__main__":
    analyze_dataset()