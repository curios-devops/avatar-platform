#!/bin/bash
# Setup RunPod endpoint

echo "🚀 Setting up RunPod endpoint for Gaussian Avatar Platform"

# Build and push Docker image to RunPod
echo "Building worker Docker image..."
docker build -f docker/worker.Dockerfile -t avatar-worker:latest .

echo "Tagging image for RunPod..."
docker tag avatar-worker:latest runpod/avatar-worker:latest

echo "Pushing to Docker registry..."
# Note: You'll need to push to a registry accessible by RunPod
# docker push your-registry/avatar-worker:latest

echo ""
echo "📝 Next steps:"
echo "1. Create a RunPod template with the worker image"
echo "2. Set environment variables in RunPod:"
echo "   - RUNPOD_API_KEY (from RunPod dashboard)"
echo "3. Deploy serverless endpoint"
echo "4. Copy endpoint ID to .env file"
echo ""
echo "For more info: https://docs.runpod.io/serverless/overview"
