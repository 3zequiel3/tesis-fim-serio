# Exact reproduction

```bash
scripts/[REDACTED-OPAQUE].sh
```

The script builds the frontend and isolated images, runs the live key rotation, executes each Playwright case individually, then executes the ordered combined suite. A trap always removes the isolated containers, network, volumes, PKI, agent state, baseline, and temporary watch directory.
