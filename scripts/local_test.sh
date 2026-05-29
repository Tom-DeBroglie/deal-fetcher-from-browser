#!/usr/bin/env bash
set -e
pip install -r requirements.txt
export SEND_EMPTY_REPORT=true
python web_deal_monitor.py
