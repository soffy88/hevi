#!/bin/bash
# Build script to force webpack instead of Turbopack

echo "Setting environment variables to disable Turbopack..."
export NEXT_PRIVATE_LOCAL_WEBPACK=1
export NEXT_REDIRECTS_ENABLED=false
export NEXT_REVALIDATE_HEADERS_ENABLED=false

echo "Starting build with webpack instead of Turbopack..."
npx next build