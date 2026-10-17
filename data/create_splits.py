import pandas as pd
import os

def create_time_based_splits():
    # Load the dataset
    file_path = 'data/HI-Small_Trans.csv'
    df = pd.read_csv(file_path)

    # Convert Date column to datetime
    df['Date'] = pd.to_datetime(df['Date'])

    # Sort by date (time-based split requires sorting by time)
    df = df.sort_values('Date').reset_index(drop=True)

    # Calculate split indices for 60/20/20
    n = len(df)
    train_end = int(0.6 * n)
    val_end = int(0.8 * n)  # 60% + 20%

    # Split the data
    train_df = df.iloc[:train_end]
    val_df = df.iloc[train_end:val_end]
    test_df = df.iloc[val_end:]

    # Ensure the replay directory exists
    replay_dir = 'data/replay'
    os.makedirs(replay_dir, exist_ok=True)

    # Save the splits
    train_df.to_csv(os.path.join(replay_dir, 'hi_small_train.csv'), index=False)
    val_df.to_csv(os.path.join(replay_dir, 'hi_small_validation.csv'), index=False)
    test_df.to_csv(os.path.join(replay_dir, 'hi_small_test.csv'), index=False)

    # Print split information
    print(f"Total rows: {n}")
    print(f"Training rows: {len(train_df)} ({len(train_df)/n*100:.1f}%)")
    print(f"Validation rows: {len(val_df)} ({len(val_df)/n*100:.1f}%)")
    print(f"Test rows: {len(test_df)} ({len(test_df)/n*100:.1f}%)")
    print(f"Training date range: {train_df['Date'].min()} to {train_df['Date'].max()}")
    print(f"Validation date range: {val_df['Date'].min()} to {val_df['Date'].max()}")
    print(f"Test date range: {test_df['Date'].min()} to {test_df['Date'].max()}")
    print(f"Splits saved to {replay_dir}/")

if __name__ == "__main__":
    create_time_based_splits()