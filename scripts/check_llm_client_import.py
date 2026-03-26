"""Smoke test that the project environment can import llm_client."""

from pathlib import Path


def main() -> None:
    """Import llm_client and report the resolved module path."""
    import llm_client

    print(Path(llm_client.__file__).resolve())


if __name__ == "__main__":
    main()
