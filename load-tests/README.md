# Recommendation load tests

Run these scripts against an isolated staging environment. Never point them at production without explicit approval.

```bash
BASE_URL=https://staging-api.example.com k6 run load-tests/smoke.js
BASE_URL=https://staging-api.example.com k6 run load-tests/recommendations.js
BASE_URL=https://staging-api.example.com k6 run load-tests/mixed-traffic.js
BASE_URL=https://staging-api.example.com k6 run load-tests/soak.js
```

Record the app commit, container CPU/memory, worker count, database pool settings, dataset size, and index model with every result.

If k6 is not installed, run the connection-pooled local recommendation test included with the dev dependencies:

```powershell
.\.venv\Scripts\python.exe scripts\load_test_recommendations.py --requests 500 --concurrency 20
```

It exits with a non-zero status when the error rate exceeds 1% or p95 exceeds 1 second.
