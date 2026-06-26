import os

# Gunicorn configuration file for Render memory optimization.

# Number of worker processes. 
# On Render Free tier (512MB RAM), we strictly limit to 1 worker to minimize baseline memory footprint.
workers = 1

# Number of threads per worker.
# Using threads instead of process workers allows handling concurrent requests 
# within the same memory space, which is highly memory-efficient.
threads = 4

# Preload application code before worker processes are forked.
# This enables Copy-on-Write memory sharing across worker processes (if multiple workers are ever run).
preload_app = True

# Restart workers after a certain number of requests to clear memory leaks/fragmentation.
max_requests = 500
max_requests_jitter = 50

# Timeout for requests
timeout = 120
