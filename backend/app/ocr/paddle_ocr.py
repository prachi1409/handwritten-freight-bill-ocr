"""Optional PaddleOCR engine for scanned / handwritten page images."""

import logging
import tempfile
from pathlib import Path
from typing import Any, List, Optional

from PIL import Image

logger = logging.getLogger(__name__)

_ENGINE = None
_ENGINE_FAILED = False


def paddleocr_available() -> bool:
    try:
        import paddleocr  # noqa: F401
        return True
    except Exception:
        return False


def _make_engine():
    from paddleocr import PaddleOCR

    attempts = (
        {"lang": "en", "use_textline_orientation": True},
        {"lang": "en", "use_angle_cls": True, "show_log": False},
        {"lang": "en", "show_log": False},
        {"lang": "en"},
    )
    last_err: Optional[Exception] = None
    for kwargs in attempts:
        try:
            return PaddleOCR(**kwargs)
        except TypeError as err:
            last_err = err
    raise RuntimeError(f"Could not initialize PaddleOCR: {last_err}")


def get_paddle_engine():
    """Load PaddleOCR once. Returns None if the package or models are unavailable."""
    global _ENGINE, _ENGINE_FAILED
    if _ENGINE_FAILED:
        return None
    if _ENGINE is not None:
        return _ENGINE
    try:
        _ENGINE = _make_engine()
        logger.info("PaddleOCR engine initialized")
        return _ENGINE
    except Exception as err:
        _ENGINE_FAILED = True
        logger.warning("PaddleOCR unavailable (%s). Falling back to PyMuPDF OCR.", err)
        return None


def _line_text(item: Any) -> str:
    if item is None:
        return ""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        rec = item[1]
        if isinstance(rec, str):
            return rec.strip()
        if isinstance(rec, (list, tuple)) and rec:
            return str(rec[0]).strip()
    if isinstance(item, dict):
        for key in ("text", "rec_text", "transcription"):
            val = item.get(key)
            if val:
                return str(val).strip()
    return ""


def parse_paddle_result(result: Any) -> str:
    """Flatten PaddleOCR 2.x / 3.x output into page text."""
    if result is None:
        return ""
    lines: List[str] = []

    if isinstance(result, dict):
        texts = result.get("rec_texts") or result.get("rec_text") or result.get("texts")
        if isinstance(texts, list):
            lines.extend(str(t).strip() for t in texts if t)
        elif texts:
            lines.append(str(texts).strip())
        return "\n".join(t for t in lines if t)

    if not isinstance(result, list):
        return str(result).strip()

    for page in result:
        if page is None:
            continue
        if isinstance(page, dict):
            chunk = parse_paddle_result(page)
            if chunk:
                lines.append(chunk)
            continue
        if isinstance(page, str):
            if page.strip():
                lines.append(page.strip())
            continue
        if isinstance(page, list):
            for item in page:
                text = _line_text(item)
                if text:
                    lines.append(text)

    return "\n".join(lines)


def ocr_images_with_paddle(images: List[Image.Image]) -> str:
    """OCR preprocessed page images. Empty string if PaddleOCR is not usable."""
    if not images:
        return ""
    engine = get_paddle_engine()
    if engine is None:
        return ""

    pages: List[str] = []
    for idx, img in enumerate(images, start=1):
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
                tmp_path = Path(handle.name)
            rgb = img.convert("RGB")
            rgb.save(tmp_path, format="PNG")
            page_text = ""
            if hasattr(engine, "ocr"):
                raw = engine.ocr(str(tmp_path))
                page_text = parse_paddle_result(raw)
            elif hasattr(engine, "predict"):
                raw = engine.predict(str(tmp_path))
                page_text = parse_paddle_result(raw)
            if page_text.strip():
                pages.append(f"--- PAGE {idx} ---\n{page_text.strip()}")
                logger.info("PaddleOCR page %s: %s characters", idx, len(page_text))
            else:
                logger.warning("PaddleOCR page %s returned empty text", idx)
        except Exception as err:
            logger.warning("PaddleOCR failed on page %s: %s", idx, err)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    return "\n\n".join(pages)
