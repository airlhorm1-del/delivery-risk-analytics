"""Simulated live orders (SYNTHETIC DATA).

Learns what a normal Olist day looked like in 2017-2018 (fit.py), then acts as a live shop: every
run creates the orders placed since the last run, dated today, and moves earlier orders through
their life cycle (run.py). Output is written in exactly the Olist file format, clearly labelled
`data_source = 'simulated'` and `is_synthetic = true`, so the pipeline treats it as one more feed.
"""
