# Design docs

- [features/](features/): one folder per feature, holding its design and decisions.
- [architecture.md](architecture.md): the system overview, covering the service layout, code layout, and data layout.
- [`../scripts/`](../scripts/README.md): how to deploy to Cloud Run and run locally with the scripts, plus the one-time cloud setup.
- [`../env/`](../env/README.md): env config. `common.env` is shared, `dev.env` / `prod.env` are per environment, and `local.env` holds personal overrides.
