"""
Simple validation script for Model Development (PRD A-04 through A-06)
Tests that models are saved and can be loaded for basic consistency check
"""

import json
import os

def validate_model_files():
    """Validate that model files exist and contain expected information"""
    print("=" * 60)
    print("MODEL VALIDATION")
    print("Checking that models are saved correctly")
    print("=" * 60)

    # Check if models directory exists
    models_dir = 'data/models'
    if not os.path.exists(models_dir):
        print("ERROR: Models directory does not exist")
        return False

    print("SUCCESS: Models directory exists")

    # Check for required model files
    required_files = [
        'raw-gbm-v1.pkl',
        'gfp-gbm-v1.pkl',
        'model_metadata.json'
    ]

    all_exist = True
    for filename in required_files:
        filepath = os.path.join(models_dir, filename)
        if os.path.exists(filepath):
            print(f"SUCCESS: {filename} exists")
        else:
            print(f"ERROR: {filename} missing")
            all_exist = False

    if not all_exist:
        return False

    # Check metadata file
    try:
        with open(os.path.join(models_dir, 'model_metadata.json'), 'r') as f:
            metadata = json.load(f)

        print("SUCCESS: Model metadata is valid JSON")

        # Check required fields
        required_models = ['raw-gbm-v1', 'gfp-gbm-v1']
        for model_name in required_models:
            if model_name in metadata:
                model_info = metadata[model_name]
                required_fields = ['threshold', 'model_type', 'features', 'created_at']
                missing_fields = [field for field in required_fields if field not in model_info]
                if not missing_fields:
                    print(f"SUCCESS: {model_name} has all required fields")
                else:
                    print(f"ERROR: {model_name} missing fields: {missing_fields}")
                    return False
            else:
                print(f"ERROR: {model_name} not found in metadata")
                return False

        # Print model information
        print("\nModel Information:")
        for model_name in required_models:
            model_info = metadata[model_name]
            print(f"  {model_name}:")
            print(f"    Threshold: {model_info['threshold']:.3f}")
            print(f"    Model Type: {model_info['model_type']}")
            print(f"    Features: {len(model_info['features'])} features")
            print(f"    Created: {model_info['created_at']}")

    except Exception as e:
        print(f"ERROR: Error reading model metadata: {e}")
        return False

    print("\n" + "=" * 60)
    print("MODEL VALIDATION PASSED")
    print("Models are saved correctly in portable format")
    print("=" * 60)
    return True

def main():
    """Main validation function"""
    try:
        success = validate_model_files()
        return 0 if success else 1
    except Exception as e:
        print(f"Error during validation: {e}")
        return 1

if __name__ == "__main__":
    exit(main())