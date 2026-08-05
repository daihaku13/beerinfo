# BeerInfo-AutoCreate

## Phase 1: CSV JSON API prototype

This prototype is designed for VPS/Linux deployment.

Run:

```bash
python csv_api.py
```

Then request:

```bash
curl http://127.0.0.1:8080/beergarden
```

The server reads `/tmp/beer-create.csv` by default. Override it with:

```bash
BEER_CREATE_CSV=/path/to/beer-create.csv python csv_api.py
```
