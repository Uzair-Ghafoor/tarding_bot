#!/bin/bash
cd "$(dirname "$0")"
pip install streamlit -q 2>/dev/null
streamlit run dashboard.py --server.headless true
