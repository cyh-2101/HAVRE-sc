"""Download only pinned public encoder artifacts and verify their SHA-256."""

from pathlib import Path
import hashlib
import httpx

from companion.memory.semantic import MODEL_FILES, MODEL_REPOSITORY, MODEL_REVISION


def main() -> None:
    root = Path(__file__).resolve().parents[1] / "var/models/memory-minilm-v1"
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        for name, expected in MODEL_FILES.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.is_file():
                with target.open("rb") as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() == expected:
                        print(f"verified {name}")
                        continue
                raise ValueError(f"existing encoder file differs: {target}")
            temporary = target.with_suffix(target.suffix + ".download")
            digest = hashlib.sha256()
            url = f"https://huggingface.co/{MODEL_REPOSITORY}/resolve/{MODEL_REVISION}/{name}"
            with client.stream("GET", url) as response, temporary.open("wb") as stream:
                response.raise_for_status()
                for block in response.iter_bytes():
                    digest.update(block)
                    stream.write(block)
            if digest.hexdigest() != expected:
                raise ValueError(f"download checksum mismatch: {name}")
            temporary.replace(target)
            print(f"verified {name}")


if __name__ == "__main__":
    main()
