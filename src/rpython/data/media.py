"""Image, audio and video data (sections 25-27).

* ``kind: "image"``: ``array`` payload + ``width``, ``height``, ``channels``,
  ``channel_order`` (``RGB``/``RGBA``/``BGR``/``L``...), ``layout``
  (``HWC``/``CHW``), ``dtype``, ``bit_depth``, ``color_space``, ``alpha``,
  ``orientation``, optional ``georeference``.  R: ``magick``/``raster``
  array with the same attributes.  Channels are **never** swapped.
* ``kind: "audio"``: ``array`` payload (samples x channels) + ``sample_rate``,
  ``channels``, ``bit_depth``, ``duration``.  The sample rate always travels.
* ``kind: "video_ref"``: lazy file/stream reference + metadata (codec,
  container, fps, frames, dimensions, duration, audio tracks).
* ``kind: "image_ref"`` / ``"audio_ref"``: file references for large media.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .context import Context
from .registry import Adapter, REGISTRY
from .semantic import Confidence, ConversionPath, Detection, Fidelity


@dataclass
class Image:
    array: np.ndarray                       # HWC (default) or CHW
    channel_order: str = "RGB"              # RGB | RGBA | BGR | BGRA | L | LA | CMYK | YCbCr
    layout: str = "HWC"
    color_space: str | None = None
    orientation: int | None = None          # EXIF orientation 1-8 if known
    georeference: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_pil(cls, im: Any) -> "Image":
        arr = np.asarray(im)
        exif = getattr(im, "getexif", lambda: {})()
        orient = exif.get(274) if exif else None
        return cls(arr, channel_order=im.mode, layout="HWC", color_space=im.mode, orientation=orient,
                   metadata={k: v for k, v in (im.info or {}).items() if isinstance(v, (str, int, float))})

    @property
    def height(self) -> int:
        return int(self.array.shape[0] if self.layout == "HWC" else self.array.shape[1])

    @property
    def width(self) -> int:
        return int(self.array.shape[1] if self.layout == "HWC" else self.array.shape[2])

    @property
    def channels(self) -> int:
        return int(1 if self.array.ndim == 2 else (self.array.shape[2] if self.layout == "HWC" else self.array.shape[0]))

    def to_pil(self) -> Any:
        from PIL import Image as PILImage
        arr = self.array if self.layout == "HWC" else np.moveaxis(self.array, 0, -1)
        return PILImage.fromarray(arr, mode=self.channel_order if self.channel_order in ("RGB", "RGBA", "L", "CMYK") else None)

    def describe_structure(self) -> str:
        return "\n".join(["Type: Image", f"Size: {self.width} x {self.height}", f"Channels: {self.channels} ({self.channel_order})",
                          f"Layout: {self.layout}", f"dtype: {self.array.dtype} ({self.array.dtype.itemsize * 8}-bit)",
                          f"Alpha: {'yes' if 'A' in self.channel_order else 'no'}",
                          f"Orientation: {self.orientation or 'unknown'}",
                          f"Georeferenced: {'yes' if self.georeference else 'no'}"])


@dataclass
class Audio:
    samples: np.ndarray                     # (n,) or (n, channels)
    sample_rate: int
    bit_depth: int | None = None
    channel_names: list[str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def channels(self) -> int:
        return 1 if self.samples.ndim == 1 else int(self.samples.shape[1])

    @property
    def duration(self) -> float:
        return float(self.samples.shape[0] / self.sample_rate)

    def describe_structure(self) -> str:
        return "\n".join(["Type: Audio", f"Sample rate: {self.sample_rate} Hz", f"Channels: {self.channels}",
                          f"Samples: {self.samples.shape[0]:,}", f"Duration: {self.duration:.3f} s",
                          f"Bit depth: {self.bit_depth or 'float'}", f"dtype: {self.samples.dtype}"])


@dataclass
class MediaRef:
    """Lazy reference to an image / audio / video file (nothing decoded)."""

    path: str
    kind: str = "video"                     # image | audio | video
    metadata: dict[str, Any] = field(default_factory=dict)

    def probe(self) -> dict[str, Any]:
        if self.metadata:
            return self.metadata
        if self.kind == "video":
            self.metadata = _ffprobe(self.path)
        elif self.kind == "image":
            try:
                from PIL import Image as PILImage
                with PILImage.open(self.path) as im:
                    self.metadata = {"width": im.width, "height": im.height, "mode": im.mode, "format": im.format}
            except Exception:
                self.metadata = {"note": "install pillow to read image headers"}
        elif self.kind == "audio":
            try:
                import soundfile as sf
                info = sf.info(self.path)
                self.metadata = {"sample_rate": info.samplerate, "channels": info.channels, "frames": info.frames,
                                 "duration": info.duration, "subtype": info.subtype, "format": info.format}
            except Exception:
                self.metadata = {"note": "install soundfile to read audio headers"}
        return self.metadata

    def describe_structure(self) -> str:
        m = self.probe()
        lines = [f"Type: {self.kind.capitalize()} (lazy file reference)", f"Path: {self.path}"]
        lines += [f"{k}: {v}" for k, v in m.items()]
        return "\n".join(lines)


def _ffprobe(path: str) -> dict[str, Any]:
    import json
    import shutil
    import subprocess
    exe = shutil.which("ffprobe")
    if not exe:
        return {"note": "ffprobe not found; metadata unavailable (file shared lazily)"}
    try:
        out = subprocess.run([exe, "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", path],
                             capture_output=True, text=True, timeout=30)
        info = json.loads(out.stdout or "{}")
        video = [s for s in info.get("streams", []) if s.get("codec_type") == "video"]
        audio = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
        v = video[0] if video else {}
        return {"container": info.get("format", {}).get("format_name"), "duration": float(info.get("format", {}).get("duration", 0) or 0),
                "codec": v.get("codec_name"), "width": v.get("width"), "height": v.get("height"),
                "fps": v.get("r_frame_rate"), "frames": v.get("nb_frames"), "audio_tracks": len(audio),
                "audio_codecs": [a.get("codec_name") for a in audio]}
    except Exception as e:
        return {"error": str(e)}


def image(source: Any, **kw: Any) -> Image | MediaRef:
    if isinstance(source, (str, os.PathLike)):
        return MediaRef(str(source), "image", **kw)
    if type(source).__module__.startswith("PIL"):
        return Image.from_pil(source)
    return Image(np.asarray(source), **kw)


def audio(source: Any, sample_rate: int | None = None, **kw: Any) -> Audio | MediaRef:
    if isinstance(source, (str, os.PathLike)):
        return MediaRef(str(source), "audio", **kw)
    if sample_rate is None:
        raise ValueError("rp.audio(samples, sample_rate=...) -- the sample rate is mandatory (never dropped)")
    return Audio(np.asarray(source), int(sample_rate), **kw)


def video(path: str, **kw: Any) -> MediaRef:
    return MediaRef(str(path), "video", **kw)


def _is_pil(obj: Any) -> bool:
    return type(obj).__module__.startswith("PIL") and hasattr(obj, "mode") and hasattr(obj, "size")


class MediaAdapter(Adapter):
    family = "media"
    kinds = ("image", "audio", "video_ref", "image_ref", "audio_ref")
    tier = ConversionPath.ADAPTER
    priority = 14

    def detect(self, obj: Any) -> Detection | None:
        if isinstance(obj, Image) or _is_pil(obj):
            return Detection("image", Confidence.CONFIRMED, "PIL" if _is_pil(obj) else "rpython.Image")
        if isinstance(obj, Audio):
            return Detection("audio", Confidence.CONFIRMED, f"{obj.sample_rate} Hz")
        if isinstance(obj, MediaRef):
            return Detection(f"{obj.kind} (file reference)", Confidence.CONFIRMED, obj.path)
        return None

    def encode(self, obj: Any, ctx: Context) -> dict[str, Any]:
        from .arrays import ArrayAdapter
        if _is_pil(obj):
            obj = Image.from_pil(obj)
        if isinstance(obj, Image):
            env = {"rpx": 1, "kind": "image", "array": ArrayAdapter().encode(obj.array, ctx), "width": obj.width,
                   "height": obj.height, "channels": obj.channels, "channel_order": obj.channel_order, "layout": obj.layout,
                   "dtype": str(obj.array.dtype), "bit_depth": int(obj.array.dtype.itemsize * 8), "color_space": obj.color_space,
                   "alpha": "A" in obj.channel_order, "orientation": obj.orientation, "georeference": obj.georeference,
                   "metadata": obj.metadata, "meta": {"source_class": "rpython.Image"}}
            ctx.record("image", ConversionPath.ADAPTER, ctx.plan.backend,
                       f"{obj.width}x{obj.height} {obj.channel_order} {obj.array.dtype} -> R array + attributes (channels untouched)")
            ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
            ctx.plan.fidelity.set("metadata", Fidelity.LOSSLESS, "channel order / colour space / orientation kept")
            return env
        if isinstance(obj, Audio):
            env = {"rpx": 1, "kind": "audio", "array": ArrayAdapter().encode(obj.samples, ctx), "sample_rate": obj.sample_rate,
                   "channels": obj.channels, "bit_depth": obj.bit_depth, "duration": obj.duration,
                   "channel_names": obj.channel_names, "metadata": obj.metadata, "meta": {"source_class": "rpython.Audio"}}
            ctx.record("audio", ConversionPath.ADAPTER, ctx.plan.backend,
                       f"{obj.samples.shape[0]:,} samples @ {obj.sample_rate} Hz x {obj.channels} ch -> R matrix + sample rate")
            ctx.plan.fidelity.set("values", Fidelity.LOSSLESS)
            ctx.plan.fidelity.set("metadata", Fidelity.LOSSLESS, "sample rate travels with the data")
            return env
        ref: MediaRef = obj
        env = {"rpx": 1, "kind": f"{ref.kind}_ref", "path": os.path.abspath(ref.path), "metadata": ref.probe(),
               "lazy": True, "meta": {"source_class": "rpython.MediaRef"}}
        ctx.record(ref.kind, ConversionPath.LAZY, "shared-file", f"{ref.path} shared lazily; frames never copied")
        ctx.plan.copies = 0
        ctx.plan.fidelity.set("laziness", Fidelity.LOSSLESS)
        return env

    def decode(self, env: dict[str, Any], ctx: Context) -> Any:
        from .arrays import ArrayAdapter
        k = env["kind"]
        if k == "image":
            arr = np.asarray(ArrayAdapter().decode(env["array"], ctx))
            return Image(arr, channel_order=env.get("channel_order", "RGB"), layout=env.get("layout", "HWC"),
                         color_space=env.get("color_space"), orientation=env.get("orientation"),
                         georeference=env.get("georeference"), metadata=env.get("metadata") or {})
        if k == "audio":
            arr = np.asarray(ArrayAdapter().decode(env["array"], ctx))
            return Audio(arr, int(env["sample_rate"]), bit_depth=env.get("bit_depth"), channel_names=env.get("channel_names"),
                         metadata=env.get("metadata") or {})
        return MediaRef(env["path"], k.replace("_ref", ""), metadata=env.get("metadata") or {})


REGISTRY.register(MediaAdapter(), tested=True)
