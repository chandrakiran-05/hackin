class Unavailable(Exception):
    """Exception raised when the risk engine is unavailable."""
    pass


# Global variables to hold the precomputed graph features
_fan_in = {}
_fan_out = {}
_degree = {}
_scatter = {}
_gather = {}
_graph_out = {}  # adjacency list for outgoing edges: bank -> set of banks
_graph_in = {}   # adjacency list for incoming edges: bank -> set of banks

# Global variables to hold the ML models
_model_raw = None
_model_gfp = None
_label_encoders = None
_feature_names = None
_threshold_raw = 0.5
_threshold_gfp = 0.5


def load():
    """
    Load the risk engine by building the graph from train and validation data.
    Precomputes graph features for fan-in, fan-out, degree, scatter, gather.
    Also loads the trained ML models.
    Returns the startup time in seconds.
    """
    import pandas as pd
    import time
    from collections import defaultdict
    import math
    from collections import deque
    import pickle
    import os

    global _fan_in, _fan_out, _degree, _scatter, _gather, _graph_out, _graph_in
    global _model_raw, _model_gfp, _label_encoders, _feature_names, _threshold_raw, _threshold_gfp

    start_time = time.perf_counter()

    # Load train and validation data
    train_df = pd.read_csv('data/replay/hi_small_train.csv')
    val_df = pd.read_csv('data/replay/hi_small_validation.csv')

    # Combine and sort by Date
    df = pd.concat([train_df, val_df])
    df['Date'] = pd.to_datetime(df['Date'])
    df = df.sort_values('Date').reset_index(drop=True)

    # Initialize data structures
    graph_out = defaultdict(set)   # bank -> set of banks it has edges to (outgoing)
    graph_in = defaultdict(set)    # bank -> set of banks that have edges to it (incoming)
    outgoing_amounts = defaultdict(list)
    incoming_amounts = defaultdict(list)

    # Build the graph from all transactions
    for _, row in df.iterrows():
        from_bank = row['From Bank']
        to_bank = row['To Bank']
        amount = row['Amount']

        graph_out[from_bank].add(to_bank)
        graph_in[to_bank].add(from_bank)
        outgoing_amounts[from_bank].append(amount)
        incoming_amounts[to_bank].append(amount)

    # Precompute features for each bank
    # Fan-in and fan-out
    _fan_in = {bank: len(in_set) for bank, in_set in graph_in.items()}
    _fan_out = {bank: len(out_set) for bank, out_set in graph_out.items()}
    # Degree (fan-in + fan-out)
    all_banks = set(_fan_in.keys()) | set(_fan_out.keys())
    _degree = {bank: _fan_in.get(bank, 0) + _fan_out.get(bank, 0) for bank in all_banks}

    # Function to compute standard deviation
    def std_dev(lst):
        if len(lst) < 2:
            return 0.0
        mean = sum(lst) / len(lst)
        variance = sum((x - mean) ** 2 for x in lst) / len(lst)
        return math.sqrt(variance)

    # Scatter (std of outgoing amounts) and Gather (std of incoming amounts)
    _scatter = {bank: std_dev(outgoing_amounts[bank]) for bank in outgoing_amounts}
    _gather = {bank: std_dev(incoming_amounts[bank]) for bank in incoming_amounts}
    # For banks with no transactions, we already have default 0.0 from std_dev for empty list?
    # But we want to cover all banks in all_banks for scatter and gather.
    for bank in all_banks:
        if bank not in _scatter:
            _scatter[bank] = 0.0
        if bank not in _gather:
            _gather[bank] = 0.0

    # Store the graph structures for cycle detection
    _graph_out = {bank: neighbors for bank, neighbors in graph_out.items()}
    _graph_in = {bank: neighbors for bank, neighbors in graph_in.items()}

    # Load the trained models
    _load_ml_models()

    end_time = time.perf_counter()
    startup_time = end_time - start_time
    return startup_time


def _load_ml_models():
    """Load the trained ML models from disk"""
    global _model_raw, _model_gfp, _label_encoders, _feature_names, _threshold_raw, _threshold_gfp

    try:
        # Load raw-gbm-v1 model
        with open('data/models/raw-gbm-v1.pkl', 'rb') as f:
            model_data_raw = pickle.load(f)
            _model_raw = model_data_raw['model']
            _threshold_raw = model_data_raw['threshold']

        # Load gfp-gbm-v1 model
        with open('data/models/gfp-gbm-v1.pkl', 'rb') as f:
            model_data_gfp = pickle.load(f)
            _model_gfp = model_data_gfp['model']
            _threshold_gfp = model_data_gfp['threshold']

        # Load label encoders and feature names (from either model, they should be the same)
        _label_encoders = model_data_raw['label_encoders']
        _feature_names = model_data_raw['feature_names']

        print("ML models loaded successfully")
    except Exception as e:
        print(f"Warning: Could not load ML models: {e}")
        print("Using placeholder scoring")
        # Set to None so we know to use fallback
        _model_raw = None
        _model_gfp = None


def _has_path(start, end, graph):
    """
    Check if there is a path from start to end in the directed graph.
    Uses BFS for efficiency.
    """
    from collections import deque
    if start == end:
        return True
    visited = set()
    queue = deque([start])
    while queue:
        node = queue.popleft()
        if node == end:
            return True
        if node in visited:
            continue
        visited.add(node)
        for neighbor in graph.get(node, set()):
            if neighbor not in visited:
                queue.append(neighbor)
    return False


def _extract_features(transaction):
    """
    Extract features from a transaction for ML model scoring.
    Returns feature array or None if feature extraction fails.
    """
    try:
        import pandas as pd
        import numpy as np
        from sklearn.preprocessing import LabelEncoder

        # Create a DataFrame with the transaction
        df = pd.DataFrame([transaction])

        # Feature engineering (same as in training)
        # Encode categorical variables using the loaded label encoders
        df_feat = df.copy()

        # Handle unknown categories by mapping to -1 or most frequent class
        def safe_transform(encoder, values):
            transformed = []
            for val in values:
                if val in encoder.classes_:
                    transformed.append(encoder.transform([val])[0])
                else:
                    # Unknown category - use most frequent class (0) or -1
                    transformed.append(0)  # Default to first class
            return np.array(transformed)

        df_feat['From Bank_encoded'] = safe_transform(_label_encoders['bank'], df_feat['From Bank'])
        df_feat['To Bank_encoded'] = safe_transform(_label_encoders['bank'], df_feat['To Bank'])
        df_feat['Transaction Type_encoded'] = safe_transform(_label_encoders['type'], df_feat['Transaction Type'])

        # Numerical features
        df_feat['Amount_log'] = np.log1p(df_feat['Amount'])

        # Time-based features
        df_feat['Date'] = pd.to_datetime(df_feat['Date'])
        df_feat['Hour'] = df_feat['Date'].dt.hour
        df_feat['DayOfWeek'] = df_feat['Date'].dt.dayofweek

        # Select features in the correct order
        feature_array = df_feat[_feature_names].values

        return feature_array
    except Exception as e:
        print(f"Warning: Feature extraction failed: {e}")
        return None


def score(transaction):
    """
    Score the risk based on graph features of the transaction.
    Returns features matching QML export format (up to 16 named floats).

    Args:
        transaction (dict): A transaction dictionary with keys:
            'From Bank', 'To Bank', 'Amount', etc.

    Returns:
        dict: Features dictionary with up to 16 named float values.
              Features include: classical score (placeholder), and f_ features
              for source and target banks (fan-in, fan-out, degree, scatter, gather)
              and cycle detection flag.
    """
    global _fan_in, _fan_out, _degree, _scatter, _gather, _graph_out, _graph_in

    from_bank = transaction.get('From Bank', '')
    to_bank = transaction.get('To Bank', '')

    # Get features for source bank (from_bank)
    source_fan_in = _fan_in.get(from_bank, 0)
    source_fan_out = _fan_out.get(from_bank, 0)
    source_degree = _degree.get(from_bank, 0)
    source_scatter = _scatter.get(from_bank, 0.0)
    source_gather = _gather.get(from_bank, 0.0)

    # Get features for target bank (to_bank)
    target_fan_in = _fan_in.get(to_bank, 0)
    target_fan_out = _fan_out.get(to_bank, 0)
    target_degree = _degree.get(to_bank, 0)
    target_scatter = _scatter.get(to_bank, 0.0)
    target_gather = _gather.get(to_bank, 0.0)

    # Check if adding this transaction would create a cycle:
    # i.e., is there a path from to_bank to from_bank in the current graph?
    would_create_cycle = 1 if _has_path(to_bank, from_bank, _graph_out) else 0

    # Prepare features dictionary matching QML export format
    # Classical score placeholder (to be replaced by trained model)
    classical_score = 0.5

    features = {
        'classical_score': classical_score,
        'f_source_fan_in': float(source_fan_in),
        'f_source_fan_out': float(source_fan_out),
        'f_source_degree': float(source_degree),
        'f_source_scatter': source_scatter,
        'f_source_gather': source_gather,
        'f_target_fan_in': float(target_fan_in),
        'f_target_fan_out': float(target_fan_out),
        'f_target_degree': float(target_degree),
        'f_target_scatter': target_scatter,
        'f_target_gather': target_gather,
        'f_would_create_cycle': float(would_create_cycle)
    }

    return features


def ingest():
    """Ingest data. Does nothing."""
    pass


if __name__ == "__main__":
    # Simple test when run directly
    import time

    # Test load and measure startup time
    startup_time = load()
    print(f"load() executed successfully in {startup_time:.4f} seconds")
    assert startup_time < 90.0, f"load() took too long: {startup_time:.4f} seconds (must be <90s)"

    # Create a dummy transaction for testing score()
    dummy_transaction = {
        'From Bank': 'Bank of America',
        'To Bank': 'Chase',
        'Amount': 100.50,
        'Currency': 'USD',
        'Transaction Type': 'Payment'
    }

    # Test score with timing
    start = time.perf_counter()
    result = score(dummy_transaction)
    end = time.perf_counter()
    elapsed_ms = (end - start) * 1000

    print(f"score() returned: {result}")
    print(f"score() executed in {elapsed_ms:.4f} ms")
    # Assert that the result has a score and non-empty reasons
    assert 'score' in result, "score() returned missing 'score' key"
    assert 'reasons' in result, "score() returned missing 'reasons' key"
    assert isinstance(result['reasons'], list) and len(result['reasons']) > 0, "score() reasons should be a non-empty list"
    assert elapsed_ms < 10.0, f"score() took too long: {elapsed_ms:.4f} ms (should be under 10ms for feature computation)"

    # Test ingest
    ingest()
    print("ingest() executed successfully")

    # Test Unavailable exception
    try:
        raise Unavailable("Engine unavailable")
    except Unavailable as e:
        print(f"Unavailable exception caught: {e}")

    print("All tests passed!")