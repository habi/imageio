import pytest
from pathlib import Path
import imageio.v3 as iio
import numpy as np
import io

av = pytest.importorskip("av", reason="pyAV is not installed.")

from av.video.format import names as video_format_names  # type: ignore # noqa: E402
from imageio.plugins.pyav import _format_to_dtype  # noqa: E402


def test_mp4_read(test_images: Path):
    with av.open(str(test_images / "cockatoo.mp4"), "r") as container:
        for idx, frame in enumerate(container.decode(video=0)):
            if idx == 4:
                break

    # ImageIO serves the data channel-first
    expected = frame.to_ndarray(format="rgb24")

    result = iio.imread(
        test_images / "cockatoo.mp4", index=42, plugin="pyav", format="rgb24"
    )
    np.allclose(result, expected)

    result = iio.imread(
        test_images / "cockatoo.mp4",
        index=42,
        plugin="pyav",
        constant_framerate=False,
        format="rgb24",
    )
    np.allclose(result, expected)


def test_mp4_read_bytes(test_images):
    encoded_video = (test_images / "cockatoo.mp4").read_bytes()

    img_expected = iio.imread(encoded_video, index=5)
    img = iio.imread(encoded_video, plugin="pyav", index=5)

    np.allclose(img, img_expected)


def test_mp4_writing(tmp_path, test_images):
    frames = iio.imread(test_images / "newtonscradle.gif")

    mp4_bytes = iio.imwrite(
        "<bytes>",
        frames,
        extension=".mp4",
        plugin="pyav",
        codec="libx264",
    )

    # libx264 writing is not deterministic and RGB -> YUV is lossy
    # so I have no good ideas how to do serious assertions on the file
    assert mp4_bytes is not None


def test_metadata(test_images: Path):
    with iio.imopen(str(test_images / "cockatoo.mp4"), "r", plugin="pyav") as plugin:
        meta = plugin.metadata()
        assert meta["profile"] == "High 4:4:4 Predictive"
        assert meta["codec"] == "h264"
        assert meta["encoder"] == "Lavf56.4.101"
        assert meta["duration"] == 14

        meta = plugin.metadata(index=4)
        assert meta["time"] == 0.2
        assert meta["key_frame"] is False


def test_properties(test_images: Path):
    with iio.imopen(str(test_images / "cockatoo.mp4"), "r", plugin="pyav") as plugin:
        with pytest.raises(IOError):
            # subsampled format
            plugin.properties(format="yuv420p")

        with pytest.raises(IOError):
            # components per channel differs
            plugin.properties(format="nv24")

        props = plugin.properties()
        assert props.shape == (280, 720, 1280, 3)
        assert props.dtype == np.uint8
        assert props.is_batch is True

        props = plugin.properties(index=4, format="rgb48")
        assert props.shape == (720, 1280, 3)
        assert props.dtype == np.uint16
        assert props.is_batch is False

        props = plugin.properties(index=5)
        assert props.shape == (720, 1280, 3)
        assert props.dtype == np.uint8
        assert props.is_batch is False


def test_video_format_to_dtype():
    # technically not fake, but mostly hwaccel formats which are unsupported in
    # pyAV at the time of writing (2022/03/06). PyAV can instantiate them, but
    # they have no components. Therefore we can't deduce an appropriate dtype
    # from these so we have to raise instead.
    fake_formats = [
        "vdpau",
        "dxva2_vld",
        "vaapi_moco",
        "drm_prime",
        "mediacodec",
        "qsv",
        "mmal",
        "vulkan",
        "vaapi_vld",
        "d3d11",
        "d3d11va_vld",
        "videotoolbox_vld",
        "vaapi_idct",
        "opencl",
        "cuda",
        "xvmc",
    ]

    for name in video_format_names:
        format = av.VideoFormat(name)

        if name in fake_formats:
            # should fail
            with pytest.raises(ValueError):
                _format_to_dtype(format)
        else:
            # should succseed
            _format_to_dtype(format)


def test_filter_sequence(test_images):
    frames = iio.imread(
        test_images / "cockatoo.mp4",
        plugin="pyav",
        filter_sequence=[
            ("drawgrid", "w=iw/3:h=ih/3:t=2:c=white@0.5"),
            ("scale", {"size": "vga", "flags": "lanczos"}),
            ("tpad", "start=3"),
        ],
    )

    assert frames.shape == (283, 480, 640, 3)

    frames = iio.imread(
        test_images / "cockatoo.mp4",
        plugin="pyav",
        filter_sequence=[
            ("framestep", "5"),
            ("scale", {"size": "vga", "flags": "lanczos"}),
        ],
    )

    assert frames.shape == (56, 480, 640, 3)


def test_filter_graph(test_images):
    frames = iio.imread(
        test_images / "cockatoo.mp4",
        plugin="pyav",
        filter_graph=(
            {
                "step": ("framestep", "5"),
                "scale": ("scale", {"size": "vga", "flags": "lanczos"}),
            },
            [
                ("video_in", "step", 0, 0),
                ("step", "scale", 0, 0),
                ("scale", "video_out", 0, 0),
            ],
        ),
    )

    assert frames.shape == (56, 480, 640, 3)


def test_write_bytes(test_images, tmp_path):
    img = iio.imread(
        test_images / "cockatoo.mp4",
        plugin="pyav",
        filter_sequence=[
            ("framestep", "5"),
            ("scale", {"size": "vga", "flags": "lanczos"}),
        ],
    )
    img_bytes = iio.imwrite(
        "<bytes>",
        img,
        extension=".mp4",
        plugin="pyav",
        in_pixel_format="yuv444p",
        codec="libx264",
    )

    assert img_bytes is not None


def test_read_png(test_images):
    img_expected = iio.imread(test_images / "chelsea.png", plugin="pillow")
    img_actual = iio.imread(test_images / "chelsea.png", plugin="pyav")

    assert np.allclose(img_actual, img_expected)


def test_write_png(test_images, tmp_path):
    img_expected = iio.imread(test_images / "chelsea.png", plugin="pyav", index=0)
    iio.imwrite(
        tmp_path / "out.png", img_expected, plugin="pyav", codec="png", is_batch=False
    )
    img_actual = iio.imread(tmp_path / "out.png", plugin="pyav")

    assert np.allclose(img_actual, img_expected)


def test_gif_write(test_images, tmp_path):
    frames_expected = iio.imread(
        test_images / "newtonscradle.gif", plugin="pyav", format="gray"
    )

    # touch the codepath that creates a video from a list of frames
    frame_list = list(frames_expected)

    iio.imwrite(
        tmp_path / "test.gif",
        frame_list,
        plugin="pyav",
        codec="gif",
        out_pixel_format="gray",
        in_pixel_format="gray",
    )
    frames_actual = iio.imread(tmp_path / "test.gif", plugin="pyav", format="gray")
    np.allclose(frames_actual, frames_expected)

    # with iio.v3.imopen("test2.gif", "w", plugin="pyav", container_format="gif", legacy_mode=False) as file:
    #     file.write(frames, codec="gif", out_pixel_format="gray", in_pixel_format="gray")


def test_gif_gen(test_images, tmp_path):
    frames = iio.imread(
        test_images / "realshort.mp4",
        plugin="pyav",
        format="rgb24",
        filter_sequence=[
            ("fps", "50"),
            ("scale", "320:-1:flags=lanczos"),
        ],
    )

    iio.imwrite(
        tmp_path / "test.gif",
        frames,
        plugin="pyav",
        codec="gif",
        fps=50,
        out_pixel_format="pal8",
        filter_graph=(
            {  # Nodes
                "split": ("split", ""),
                "palettegen": ("palettegen", ""),
                "paletteuse": ("paletteuse", ""),
            },
            [  # Edges
                ("video_in", "split", 0, 0),
                ("split", "palettegen", 0, 0),
                ("split", "paletteuse", 1, 0),
                ("palettegen", "paletteuse", 0, 1),
                ("paletteuse", "video_out", 0, 0),
            ],
        ),
    )


def test_variable_fps_seek(test_images):
    expected = iio.imread(test_images / "cockatoo.mp4", index=3, plugin="pyav")
    actual = iio.imread(
        test_images / "cockatoo.mp4", index=3, plugin="pyav", constant_framerate=False
    )

    assert np.allclose(actual, expected)


def test_multiple_writes(test_images):
    out_buffer = io.BytesIO()
    with iio.imopen(out_buffer, "w", plugin="pyav", extension=".mp4") as file:
        for frame in iio.imiter(
            test_images / "newtonscradle.gif",
            plugin="pyav",
        ):
            file.write(frame, is_batch=False, codec="libx264", in_pixel_format="rgba")

    actual = out_buffer.getvalue()
    assert actual is not None


def test_exceptions(tmp_path):
    with pytest.raises(IOError):
        iio.imopen(io.BytesIO(), "w", plugin="pyav", legacy_mode=False)

    with pytest.raises(IOError):
        iio.imopen(b"nonsense", "r", plugin="pyav", legacy_mode=False)

    foo_file = tmp_path / "faulty.mp4"
    foo_file.write_bytes(b"nonsense")
    with pytest.raises(IOError):
        iio.imopen(foo_file, "r", plugin="pyav", legacy_mode=False)


def test_native_pixformat_reading(test_images):
    frames = iio.imread(
        test_images / "cockatoo.mp4",
        index=5,
        plugin="pyav",
        format=None,
    )

    # cockatoo.mp4 uses YUV444p
    assert frames.shape == (3, 720, 1280)


def test_invalid_resource(tmp_path):
    img = np.zeros((100, 100, 3))

    with pytest.raises(IOError):
        iio.imwrite(tmp_path / "foo.abc", img, plugin="pyav")


def test_bayer_write():
    image_shape = (128, 128)
    image = np.zeros(image_shape, dtype="uint8")
    buffer = io.BytesIO()

    with iio.imopen(buffer, "w", plugin="pyav", extension=".mp4") as file:
        image[...] = 0
        for i in range(256):
            image[::2, ::2] = i
            file.write(
                image, is_batch=False, codec="h264", in_pixel_format="bayer_rggb8"
            )

        image[...] = 0
        for i in range(256):
            image[0::2, 1::2] = i
            image[1::2, 0::2] = i
            file.write(
                image, is_batch=False, codec="h264", in_pixel_format="bayer_rggb8"
            )

        image[...] = 0
        for i in range(256):
            image[1::2, 1::2] = i
            file.write(
                image, is_batch=False, codec="h264", in_pixel_format="bayer_rggb8"
            )

    buffer.seek(0)
    img = iio.imread(buffer, plugin="pyav")
    assert img.shape == (768, 128, 128, 3)


def test_sequential_reading(test_images):
    expected_imgs = [
        iio.imread(test_images / "cockatoo.mp4", index=1),
        iio.imread(test_images / "cockatoo.mp4", index=5),
    ]

    with iio.imopen(test_images / "cockatoo.mp4", "r", plugin="pyav") as img_file:
        first_read = img_file.read(index=1, thread_type="FRAME", thread_count=2)
        second_read = img_file.read(index=5)
        actual_imgs = [first_read, second_read]

    np.allclose(actual_imgs, expected_imgs)


def test_uri_reading(test_images):
    uri = "https://dash.akamaized.net/dash264/TestCases/2c/qualcomm/1/MultiResMPEG2.mpd"

    with av.open(uri) as container:
        for idx, frame in enumerate(container.decode(video=0)):
            if idx < 250:
                continue

            expected = frame.to_ndarray(format="rgb24")
            break

    actual = iio.imread(uri, plugin="pyav", index=250)

    np.allclose(actual, expected)


def test_seek_last(test_images):
    frame = iio.imread(test_images / "cockatoo.mp4", plugin="pyav", index=279)
    assert frame.shape == (720, 1280, 3)
