#!/usr/bin/env bash
# Phase 3 data chain: host weights -> weighted PageRank variant -> rank history (waits for downloads).
PY=.venv/Scripts/python.exe
$PY -u -m backend.jobs.build_host_weights >> data/build_host_weights.log 2>&1 || { echo "build_host_weights FAILED" >> data/phase3_chain.log; exit 1; }
echo "build_host_weights done $(date)" >> data/phase3_chain.log
$PY -u -m backend.jobs.compute_all >> data/compute_all.log 2>&1 || { echo "compute_all FAILED" >> data/phase3_chain.log; exit 1; }
echo "compute_all done $(date)" >> data/phase3_chain.log
$PY -u -m backend.jobs.load_history >> data/load_history.log 2>&1 || { echo "load_history FAILED" >> data/phase3_chain.log; exit 1; }
echo "load_history done $(date)" >> data/phase3_chain.log
