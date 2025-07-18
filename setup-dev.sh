#!/bin/bash

# Check if setenv.sh exists
if [ ! -f "setenv.sh" ]; then
    echo "Error: setenv.sh not found. Please create it from setenv.example.sh first."
    echo "Run: cp setenv.example.sh setenv.sh"
    exit 1
fi

# Check if venv exists
if [ ! -d "venv" ]; then
    echo "Virtual environment not found. Creating it now..."
    python3 -m venv venv
    echo "Virtual environment created."
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Set environment variables
echo "Setting environment variables..."
source setenv.sh

# Set the PYTHONPATH
echo "Setting PYTHONPATH..."
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="$PROJECT_ROOT/backend:$PYTHONPATH"

echo "======================================="
echo "Development environment setup complete!"
echo "Virtual environment: ACTIVATED"
echo "Environment variables: LOADED"
echo "PYTHONPATH: CONFIGURED"
echo "======================================="
echo ""
echo "To deactivate the virtual environment when done, run: deactivate"