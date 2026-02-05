#!/bin/bash
cd "$(dirname "$0")"
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 3978 --reload
