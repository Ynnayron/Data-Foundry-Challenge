"""Entrypoint for `make run` / `docker compose up pipeline`.

Delegates to the Prefect flow in pipeline.py, which replaces the previous
fixed subprocess sequence with a dependency-driven task graph.
"""

from data_foundry.pipeline import data_foundry_flow


def main():
    print("Domínio Público Data Pipeline (Prefect-orchestrated)")
    print("=" * 60)
    run_id = data_foundry_flow()
    print("=" * 60)
    print(f"Done. run_id={run_id}")
    print("Outputs: data/runs/<run_id>/{localized_catalog,universal_metadata}.json")
    print("Pointer: data/output/latest -> data/runs/<run_id>")


if __name__ == "__main__":
    main()
