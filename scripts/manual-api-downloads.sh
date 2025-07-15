#!/bin/bash
# Manual download of known CAMARA APIs

echo "📥 Downloading CAMARA APIs manually..."

mkdir -p test-data/from-camara

# Quality on Demand
echo "1. Quality on Demand API..."
curl -s -o test-data/from-camara/qod-api.yaml \
  https://raw.githubusercontent.com/camaraproject/QualityOnDemand/main/code/API_definitions/quality-on-demand.yaml

# Device Location
echo "2. Device Location APIs..."
curl -s -o test-data/from-camara/location-verification.yaml \
  https://raw.githubusercontent.com/camaraproject/DeviceLocation/main/code/API_definitions/location-verification.yaml

curl -s -o test-data/from-camara/location-retrieval.yaml \
  https://raw.githubusercontent.com/camaraproject/DeviceLocation/main/code/API_definitions/location-retrieval.yaml

# SIM Swap
echo "3. SIM Swap API..."
curl -s -o test-data/from-camara/sim-swap.yaml \
  https://raw.githubusercontent.com/camaraproject/SimSwap/main/code/API_definitions/sim-swap.yaml

# Number Verification
echo "5. Number Verification API..."
curl -s -o test-data/from-camara/number-verification.yaml \
  https://raw.githubusercontent.com/camaraproject/NumberVerification/main/code/API_definitions/number-verification.yaml

# Home Devices QoD
echo "6. Home Devices QoD API..."
curl -s -o test-data/from-camara/home-devices-qod.yaml \
  https://raw.githubusercontent.com/camaraproject/HomeDevicesQoD/main/code/API_definitions/home-devices-qod.yaml

# Carrier Billing
echo "7. Carrier Billing API..."
curl -s -o test-data/from-camara/carrier-billing.yaml \
  https://raw.githubusercontent.com/camaraproject/CarrierBillingCheckOut/main/code/API_definitions/carrier-billing.yaml

echo ""
echo "✅ Download complete!"
echo ""
echo "📊 APIs downloaded:"
ls -1 test-data/from-camara/*.yaml 2>/dev/null | wc -l
echo ""
ls -la test-data/from-camara/

# Validate downloads
echo ""
echo "🔍 Validating downloads..."
for file in test-data/from-camara/*.yaml; do
    if [ -f "$file" ]; then
        if grep -q "openapi:" "$file" 2>/dev/null; then
            echo "  ✓ $(basename $file)"
        else
            echo "  ✗ $(basename $file) - not a valid OpenAPI file"
            rm "$file"
        fi
    fi
done
