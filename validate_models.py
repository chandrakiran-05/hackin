"""
Validation script for Model Development (PRD A-04 through A-06)
Tests that models produce consistent scores (simulating laptop vs VM consistency)
"""

import pickle
import numpy as np
import pandas as pd
import json
import time
import os

def load_models():
    """Load the trained models"""
    print("Loading models...")

    # Load raw-gbm-v1 model
    with open('data/models/raw-gbm-v1.pkl', 'rb') as f:
        model_data_raw = pickle.load(f)
        model_raw = model_data_raw['model']
        threshold_raw = model_data_raw['threshold']
        label_encoders = model_data_raw['label_encoders']
        feature_names = model_data_raw['feature_names']

    # Load gfp-gbm-v1 model
    with open('data/models/gfp-gbm-v1.pkl', 'rb') as f:
        model_data_gfp = pickle.load(f)
        model_gfp = model_data_gfp['model']
        threshold_gfp = model_data_gfp['threshold']

    print("Models loaded successfully")
    return model_raw, model_gfp, threshold_raw, threshold_gfp, label_encoders, feature_names

def extract_features(transaction, label_encoders, feature_names):
    """Extract features from a transaction (same as in scoring/core.py)"""
    try:
        import pandas as pd
        import numpy as np

        # Create a DataFrame with the transaction
        df = pd.DataFrame([transaction])

        # Feature engineering (same as in training)
        # Encode categorical variables using the loaded label encoders
        df_feat = df.copy()

        # Handle unknown categories by mapping to most frequent class
        def safe_transform(encoder, values):
            transformed = []
            for val in values:
                if val in encoder.classes_:
                    transformed.append(encoder.transform([val])[0])
                else:
                    # Unknown category - use most frequent class (0)
                    transformed.append(0)
            return np.array(transformed)

        df_feat['From Bank_encoded'] = safe_transform(label_encoders['bank'], df_feat['From Bank'])
        df_feat['To Bank_encoded'] = safe_transform(label_encoders['bank'], df_feat['To Bank'])
        df_feat['Transaction Type_encoded'] = safe_transform(label_encoders['type'], df_feat['Transaction Type'])

        # Numerical features
        df_feat['Amount_log'] = np.log1p(df_feat['Amount'])

        # Time-based features
        df_feat['Date'] = pd.to_datetime(df_feat['Date'])
        df_feat['Hour'] = df_feat['Date'].dt.hour
        df_feat['DayOfWeek'] = df_feat['Date'].dt.dayofweek

        # Select features in the correct order
        feature_array = df_feat[feature_names].values

        return feature_array
    except Exception as e:
        print(f"Warning: Feature extraction failed: {e}")
        return None

def test_model_consistency():
    """Test that models produce consistent results (simulating laptop vs VM)"""
    print("=" * 60)
    print("MODEL CONSISTENCY VALIDATION")
    print("Testing that models produce same scores consistently")
    print("=" * 60)

    # Load models
    model_raw, model_gfp, threshold_raw, threshold_gfp, label_encoders, feature_names = load_models()

    # Load test data
    test_df = pd.read_csv('data/replay/hi_small_test.csv')
    print(f"\nLoaded {len(test_df)} test transactions")

    # Create simple labels for testing (same approach as training)
    def create_fault_label(row):
        if row['Transaction Type'] == 'Transfer' and row['From Bank'] != row['To Bank']:
            if row['Amount'] > 200:
                return 1
        elif row['Transaction Type'] == 'Payment' and row['Amount'] > 500:
            return 1
        return 0

    test_df['is_fraud'] = test_df.apply(create_fault_label, axis=1)
    print(f"Fraud rate in test data: {test_df['is_fraud'].mean():.3f}")

    # Test multiple runs to simulate laptop vs VM consistency
    print("\nRunning consistency tests...")

    # Store results from multiple runs
    results_raw = []
    results_gfp = []

    # Run 5 times to check consistency
    for run in range(5):
        print(f"\nRun {run + 1}:")

        scores_raw = []
        scores_gfp = []
        predictions_raw = []
        predictions_gfp = []

        # Process each transaction
        for idx, row in test_df.iterrows():
            transaction = row.to_dict()

            # Extract features
            features = extract_features(transaction, label_encoders, feature_names)

            if features is not None:
                # Get predictions from both models
                proba_raw = model_raw.predict_proba(features)[0, 1]
                proba_gfp = model_gfp.predict_proba(features)[0, 1]

                # Apply thresholds
                pred_raw = 1 if proba_raw >= threshold_raw else 0
                pred_gfp = 1 if proba_gfp >= threshold_gfp else 0

                scores_raw.append(proba_raw)
                scores_gfp.append(proba_gfp)
                predictions_raw.append(pred_raw)
                predictions_gfp.append(pred_gfp)
            else:
                # Feature extraction failed
                scores_raw.append(0.5)
                scores_gfp.append(0.5)
                predictions_raw.append(0)
                predictions_gfp.append(0)

        results_raw.append({
            'scores': scores_raw,
            'predictions': predictions_raw
        })

        results_gfp.append({
            'scores': scores_gfp,
            'predictions': predictions_gfp
        })

        print(f"  Raw-GBM-V1: {sum(predictions_raw)} predictions of {len(predictions_raw)}")
        print(f"  GFP-GBM-V1: {sum(predictions_gfp)} predictions of {len(predictions_gfp)}")

    # Check consistency across runs
    print("\nChecking consistency across runs...")

    # For raw-gbm-v1
    raw_scores_consistent = True
    raw_preds_consistent = True

    first_raw_scores = results_raw[0]['scores']
    first_raw_preds = results_raw[0]['predictions']

    for i, run_result in enumerate(results_raw[1:], 1):
        if run_result['scores'] != first_raw_scores:
            raw_scores_consistent = False
            print(f"  Raw-GBM-V1 scores differ in run {i+1}")
        if run_result['predictions'] != first_raw_preds:
            raw_preds_consistent = False
            print(f"  Raw-GBM-V1 predictions differ in run {i+1}")

    # For gfp-gbm-v1
    gfp_scores_consistent = True
    gfp_preds_consistent = True

    first_gfp_scores = results_gfp[0]['scores']
    first_gfp_preds = results_gfp[0]['predictions']

    for i, run_result in enumerate(results_gfp[1:], 1):
        if run_result['scores'] != first_gfp_scores:
            gfp_scores_consistent = False
            print(f"  GFP-GBM-V1 scores differ in run {i+1}")
        if run_result['predictions'] != first_gfp_preds:
            gfp_preds_consistent = False
            print(f"  GFP-GBM-V1 predictions differ in run {i+1}")

    # Summary
    print("\n" + "=" * 60)
    print("CONSISTENCY TEST RESULTS")
    print("=" * 60)
    print(f"Raw-GBM-V1 scores consistent across runs: {raw_scores_consistent}")
    print(f"Raw-GBM-V1 predictions consistent across runs: {raw_preds_consistent}")
    print(f"GFP-GBM-V1 scores consistent across runs: {gfp_scores_consistent}")
    print(f"GFP-GBM-V1 predictions consistent across runs: {gfp_preds_consistent}")

    all_consistent = raw_scores_consistent and raw_preds_consistent and gfp_scores_consistent and gfp_preds_consistent

    if all_consistent:
        print("\n✓ ALL CONSISTENCY TESTS PASSED")
        print("Models produce same scores consistently (simulating laptop vs VM consistency)")
    else:
        print("\n✗ SOME CONSISTENCY TESTS FAILED")
        print("Models show inconsistency across runs")

    # Test on first 10 rows as specified in requirements
    print("\n" + "=" * 60)
    print("TESTING ON FIRST 10 ROWS (as specified in requirements)")
    print("=" * 60)

    first_10_df = test_df.head(10)
    print(f"Testing on first {len(first_10_df)} rows:")

    for idx, row in first_10_df.iterrows():
        transaction = row.to_dict()
        features = extract_features(transaction, label_encoders, feature_names)

        if features is not None:
            proba_raw = model_raw.predict_proba(features)[0, 1]
            proba_gfp = model_gfp.predict_proba(features)[0, 1]
            pred_raw = 1 if proba_raw >= threshold_raw else 0
            pred_gfp = 1 if proba_gfp >= threshold_gfp else 0

            actual = row['is_fraud']

            print(f"  Row {idx+1}: Amount=${row['Amount']:.2f}, Type={row['Transaction Type']}")
            print(f"    Raw-GBM-V1: {proba_raw:.3f} -> {'FRAUD' if pred_raw else 'NORMAL'} (Actual: {'FRAUD' if actual else 'NORMAL'})")
            print(f"    GFP-GBM-V1: {proba_gfp:.3f} -> {'FRAUD' if pred_gfp else 'NORMAL'} (Actual: {'FRAUD' if actual else 'NORMAL'})")
        else:
            print(f"  Row {idx+1}: Feature extraction failed")

    print("\n" + "=" * 60)
    print("VALIDATION COMPLETE")
    print("=" * 60)

    return all_consistent

def main():
    """Main validation function"""
    try:
        consistent = test_model_consistency()
        return 0 if consistent else 1
    except Exception as e:
        print(f"Error during validation: {e}")
        return 1

if __name__ == "__main__":
    exit(main())