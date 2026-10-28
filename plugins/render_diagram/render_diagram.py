"""Render Graphviz DOT source to a PNG without calling an image model."""
import logging
from pathlib import Path
import shutil
import subprocess
import tempfile

logger = logging.getLogger(__name__)
MAX_SOURCE_BYTES = 64_000
MAX_PNG_BYTES = 10_000_000
RENDER_TIMEOUT_SECONDS = 15
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def render_diagram(source, output_directory):
    """Return a verified artifact path, or a DIAGRAM_FAILED status.

    output_directory is supplied by the host's memoryDirectory setting, not
    by the model. Graphviz inherits the host's filesystem security policy.
    """
    if not isinstance(source, str) or not source.strip():
        return "DIAGRAM_FAILED: provide nonempty Graphviz DOT source"
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        return "DIAGRAM_FAILED: DOT source exceeds 64000 UTF-8 bytes"
    executable = shutil.which("dot")
    if executable is None:
        return "DIAGRAM_FAILED: Graphviz is not installed; install dot and add it to PATH"

    artifact_dir = None
    try:
        root = Path(output_directory) / "diagrams"
        root.mkdir(parents=True, exist_ok=True)
        artifact_dir = Path(tempfile.mkdtemp(prefix="diagram-", dir=root))
        image_path = artifact_dir / "diagram.png"
        source_path = artifact_dir / "diagram.dot"
        source_path.write_text(source, encoding="utf-8")
        # Source goes through stdin, never through a shell or command arguments.
        result = subprocess.run(
            [executable, "-Kdot", "-Tpng", "-o", str(image_path.resolve())],
            input=source.encode("utf-8"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd=artifact_dir,
            timeout=RENDER_TIMEOUT_SECONDS,
            check=False,
        )
        if result.returncode:
            detail = result.stderr.decode("utf-8", errors="replace").strip()[:1000]
            raise ValueError(detail or "Graphviz could not render this source")
        size = image_path.stat().st_size
        with image_path.open("rb") as image:
            signature = image.read(len(PNG_SIGNATURE))
        if signature != PNG_SIGNATURE or size <= len(PNG_SIGNATURE):
            raise ValueError("Graphviz did not produce a PNG image")
        if size > MAX_PNG_BYTES:
            raise ValueError("rendered PNG exceeds 10 MB; simplify the diagram")
        return (
            f"DIAGRAM_RENDERED: file={image_path.resolve()} "
            f"source={source_path.resolve()} bytes={size}; "
            "saved locally, not sent to the user"
        )
    except subprocess.TimeoutExpired:
        error = "Graphviz exceeded the 15-second rendering timeout"
    except (OSError, ValueError) as exc:
        error = str(exc)
    if artifact_dir is not None:
        shutil.rmtree(artifact_dir, ignore_errors=True)
    logger.warning("Diagram rendering failed: %s", error)
    return f"DIAGRAM_FAILED: {error}"
